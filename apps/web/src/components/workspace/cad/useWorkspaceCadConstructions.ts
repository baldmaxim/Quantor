'use client';

import type { CadConstructionProps, CadSheetLevelsWrite } from '@quantor/api-client';
import { useMemo, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import {
  CAD_CONSTRUCTIONS_VISIBLE_KEY,
  buildConstructionIndex,
  buildShapes,
  doorsOf,
  sameGroupIds,
} from '@/lib/cad/constructions';
import {
  isWallsActive,
  latestWallsFailure,
  latestWallsStatus,
  useBulkConstructionProps,
  useCadConstructions,
  useRecomputeCadWalls,
  useSaveConstructionProps,
  useSaveSheetLevels,
  WALLS_BUSY,
  WALLS_NOT_READY,
  wallsJobStatus,
} from '@/lib/cad/constructions-queries';
import { readConstructionColors, type IConstructionPaintData } from '@/lib/cad/constructions-painter';
import type { ICadFrame } from '@/lib/cad/frame';
import { withoutHiddenCategories, type CadLayerCategory } from '@/lib/cad/layer-categories';
import { useStoredBoolean } from '@/lib/cad/useStoredBoolean';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { extractCode } from '@/lib/errors';
import { useTheme } from '@/lib/theme';
import type { Camera } from '@/lib/viewer/camera';

import type {
  IWorkspaceCadConstructionPicker,
  IWorkspaceCadConstructions,
} from './types';
import { useWorkspaceCadVor } from './useWorkspaceCadVor';

const NO_IDS: ReadonlySet<string> = new Set<string>();

interface IInput {
  /** Родитель вида (задание, лист, вид); `null` - вида нет, запросов нет. */
  params: ICadViewParams | null;
  frame: ICadFrame | null;
  pageSize: { width: number; height: number } | null;
  camera: Camera;
  /** Флаг `cad.export` включён и вкладка CAD открывалась хотя бы раз. */
  load: boolean;
  /** Вкладка CAD открыта: слой рисуется и выбор работает только на ней. */
  active: boolean;
  /** Идёт отметка замечания или рисование зоны: они занимают холст. */
  blocked: boolean;
  /** Скрытые категории вкладки «Слои»: не рисуются и не выбираются кликом. */
  hiddenCategories?: ReadonlySet<CadLayerCategory>;
  /** Имена скрытых слоёв DXF: конструкция скрыта, когда скрыты все её слои-источники. */
  hiddenLayerNames?: ReadonlySet<string>;
}

export interface IWorkspaceCadConstructionsState {
  readonly side: IWorkspaceCadConstructions | null;
  /** Галка «Контуры всех конструкций» панели слоёв (полный показ); `null` - конструкций на листе нет. */
  readonly layers: { visible: boolean; onVisibleChange: (visible: boolean) => void } | null;
  /** Данные рисовальщика; `null` - рисовать нечего. */
  readonly paintData: IConstructionPaintData | null;
  /** Данные выбора по клику и карточки; `null` - выбор выключен. */
  readonly picker: IWorkspaceCadConstructionPicker | null;
  /** Общий выбор плана и 3D: множество id и выбор из 3D (`null` - снять). */
  readonly selection: {
    readonly selectedIds: ReadonlySet<string>;
    readonly onSelectConstruction: (id: string | null) => void;
  };
}

const notReadyText = (status: string | null): string =>
  isWallsActive(status)
    ? 'Конструкции считаются. Результат появится здесь сам.'
    : status === null
      ? 'Конструкции этого листа ещё не считались.'
      : 'Расчёт конструкций не удался. Посчитайте ещё раз.';

/**
 * Конструкции листа: данные сервера, слой на холсте, выбор по клику и свод.
 *
 * Величины приходят с сервера; здесь их показывают и отправляют параметры человека. Выделение,
 * карточка и подсветка группы - локальное состояние листа. Панорама и зум идут мимо React
 * (ADR-0004): карточка хранит точку клика и закрывается, когда камера двинулась.
 */
export const useWorkspaceCadConstructions = ({
  params,
  frame,
  pageSize,
  camera,
  load,
  active,
  blocked,
  hiddenCategories,
  hiddenLayerNames,
}: IInput): IWorkspaceCadConstructionsState => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readConstructionColors();
  }, [theme]);

  const [visible, setVisible] = useStoredBoolean(CAD_CONSTRUCTIONS_VISIBLE_KEY, false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(NO_IDS);
  const [groupKey, setGroupKey] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [actionError, setActionError] = useState<string | null>(null);
  const [popoverError, setPopoverError] = useState<string | null>(null);

  // Выбор принадлежит виду: на другом они означали бы другое место.
  const scope = params ? `${params.jobId}:${params.pageIndex}:${params.view}` : null;
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setSelected(NO_IDS);
    setGroupKey(null);
    setActiveId(null);
    setActionError(null);
    setPopoverError(null);
  }

  const enabled = load && params !== null;
  const query = useCadConstructions(params, enabled);
  const data = query.data ?? null;

  const vor = useWorkspaceCadVor({ params, enabled: enabled && data !== null, stamp: query.dataUpdatedAt });

  const recompute = useRecomputeCadWalls(params);
  const saveProps = useSaveConstructionProps(params);
  const bulkProps = useBulkConstructionProps(params);
  const saveLevels = useSaveSheetLevels(params);

  const allShapes = useMemo(
    () => (data && frame && pageSize ? buildShapes(data.constructions, frame, pageSize) : []),
    [data, frame, pageSize],
  );
  // Скрытая категория не попадает под клик (индекс и выбор строятся без неё); не рисует её сам рисовальщик.
  const shapes = useMemo(
    () => withoutHiddenCategories(allShapes, hiddenCategories, hiddenLayerNames),
    [allShapes, hiddenCategories, hiddenLayerNames],
  );
  const index = useMemo(() => buildConstructionIndex(shapes), [shapes]);

  const live = useMemo<ReadonlySet<string>>(() => {
    if (selected.size === 0) return NO_IDS;
    const known = new Set(shapes.map((shape) => shape.id));
    return new Set([...selected].filter((id) => known.has(id)));
  }, [selected, shapes]);

  const paintData = useMemo<IConstructionPaintData | null>(
    () =>
      active && shapes.length > 0
        ? {
            shapes: allShapes,
            colors,
            selected: live,
            showAll: visible,
            notInVor: vor.notInVor,
            hiddenCategories,
            hiddenLayerNames,
          }
        : null,
    [active, visible, shapes.length, allShapes, colors, live, vor.notInVor, hiddenCategories, hiddenLayerNames],
  );

  // --- карточка ---
  const construction =
    activeId !== null ? (data?.constructions.find((item) => item.id === activeId) ?? null) : null;
  const closePopover = () => setActiveId(null);
  const failure = (setError: (text: string) => void) => (error: unknown) =>
    setError(cadErrorText(error));

  const popover =
    construction !== null && data !== null
      ? {
          construction,
          doors: doorsOf(data.openings, construction).length,
          groupCount: sameGroupIds(data.constructions, construction).length,
          anchor,
          saving: saveProps.isPending || bulkProps.isPending,
          error: popoverError,
          onClose: closePopover,
          onSave: (props: CadConstructionProps) => {
            setPopoverError(null);
            saveProps.mutate({ key: construction.id, props }, { onError: failure(setPopoverError) });
          },
          onBulk: (patch: CadConstructionProps) => {
            setPopoverError(null);
            bulkProps.mutate(
              { keys: sameGroupIds(data.constructions, construction), patch },
              { onError: failure(setPopoverError) },
            );
          },
          onAccept: (accepted: boolean) => {
            setPopoverError(null);
            saveProps.mutate(
              { key: construction.id, props: construction.props, accepted },
              { onError: failure(setPopoverError) },
            );
          },
        }
      : null;

  const picker: IWorkspaceCadConstructionPicker | null =
    active && !blocked && pageSize !== null && shapes.length > 0
      ? {
          camera,
          page: pageSize,
          index,
          onPick: (id, point) => {
            setPopoverError(null);
            setGroupKey(null);
            setSelected(id === null ? NO_IDS : new Set([id]));
            setActiveId(id);
            setAnchor(point);
          },
          onDismiss: closePopover,
          popover,
        }
      : null;

  // --- свод ---
  const status = query.error !== null ? wallsJobStatus(query.error) : null;
  const notReady = query.error !== null && extractCode(query.error) === WALLS_NOT_READY;
  // Свежее задание: при готовом результате - из ответа, без него - из отказа 404.
  const calculating =
    recompute.isPending ||
    isWallsActive(notReady ? status : latestWallsStatus(data ?? undefined));

  const side: IWorkspaceCadConstructions | null = enabled
    ? {
        status: data
          ? 'ready'
          : notReady
            ? 'not-ready'
            : query.isError
              ? 'error'
              : 'loading',
        data,
        notReadyText: notReady ? notReadyText(status) : null,
        loadError: query.isError && !notReady ? cadErrorText(query.error) : null,
        onReload: () => void query.refetch(),
        calculating,
        actionError,
        recomputeFailure: latestWallsFailure(data),
        onCompute: () => {
          setActionError(null);
          recompute.mutate(undefined, {
            onError: (error) => {
              if (extractCode(error) === WALLS_BUSY) {
                setActionError('Конструкции уже считаются. Результат появится здесь сам.');
              } else {
                setActionError(cadErrorText(error));
              }
            },
          });
        },
        levelsSaving: saveLevels.isPending,
        onSaveLevels: (levels: CadSheetLevelsWrite) => {
          setActionError(null);
          saveLevels.mutate(levels, { onError: failure(setActionError) });
        },
        activeGroup: groupKey,
        onSelectGroup: (key, ids) => {
          setActiveId(null);
          if (key === groupKey || ids.length === 0) {
            setGroupKey(null);
            setSelected(NO_IDS);
            return;
          }
          setGroupKey(key);
          setSelected(new Set(ids));
        },
        vor: vor.side,
      }
    : null;

  // Выбор из 3D: как одиночный клик в плане, но без карточки плана (она привязана к точке холста).
  const selectFrom3d = (id: string | null) => {
    setPopoverError(null);
    setGroupKey(null);
    setActiveId(null);
    setSelected(id === null ? NO_IDS : new Set([id]));
  };

  return {
    side,
    layers: data !== null ? { visible, onVisibleChange: setVisible } : null,
    paintData,
    picker,
    selection: { selectedIds: selected, onSelectConstruction: selectFrom3d },
  };
};
