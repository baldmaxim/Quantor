'use client';

import { useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
import { ToolButton, ToolDivider } from '@/components/workspace/Toolbar';
import { WALLS_NOT_READY, isWallsActive, useCadConstructions, wallsJobStatus } from '@/lib/cad/constructions-queries';
import { cadErrorText } from '@/lib/cad/errors';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';
import { buildFloor3dPlan } from '@/lib/cad/floor3d-geometry';
import {
  useCadFloor3d,
  useCadProjectLevels,
  useSaveCadProjectLevels,
  useSaveFloor3dSheetLevels,
  useSetFloor3dHole,
} from '@/lib/cad/floor3d-queries';
import type { IMepPick } from '@/lib/cad/floor3d-mep-pick';
import { routesBaseZMm } from '@/lib/cad/floor3d-routes';
import type { IFloor3dPick } from '@/lib/cad/floor3d-scene';
import { layerGroupKeys, type CadLayerCategory } from '@/lib/cad/layer-categories';
import { useMepLayerVisibility } from '@/lib/cad/mep-layers';
import { useCadEomRoutes3d } from '@/lib/cad/eom-queries';
import { useCadMepRoutes3d } from '@/lib/cad/mep-routes3d-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { extractCode } from '@/lib/errors';

import { CadFloor3dCanvas, type ICadFloor3dRoutes, type IFloor3dViewRequest } from './CadFloor3dCanvas';
import { CadFloor3dDxfButton } from './CadFloor3dDxfButton';
import { CadFloor3dHeights } from './CadFloor3dHeights';
import { CadFloor3dHoleList } from './CadFloor3dHoleList';
import { CadFloor3dInfoPanel } from './CadFloor3dInfoPanel';
import { CadFloor3dLegend } from './CadFloor3dLegend';
import { CadFloor3dMepPopover } from './CadFloor3dMepPopover';
import { CadFloor3dPopover } from './CadFloor3dPopover';
import { CadFloor3dWarnings } from './CadFloor3dWarnings';
import { useFloor3dMepPick } from './useFloor3dMepPick';

export interface ICadFloor3dViewProps {
  /** Лист и вид, которые показывает план: те же задание, страница и вид. */
  readonly params: ICadViewParams;
  /** Общий выбор конструкций плана и 3D: подсвечиваются все его стены и плита. */
  readonly selectedIds?: ReadonlySet<string>;
  /** Клик по стене или плите - выбор этой конструкции; `null` - выбор снят (пустота, Esc, закрытие плашки). */
  readonly onSelectConstruction?: (id: string | null) => void;
  /** Скрытые категории вкладки «Слои». */
  readonly hiddenCategories?: ReadonlySet<CadLayerCategory>;
  /** Конструкции, скрытые вкладкой «Слои» (категория или все слои-источники). */
  readonly hiddenConstructionIds?: ReadonlySet<string>;
  /** Только просмотр (страница объекта): без правки высот, отверстий и выгрузки DXF. */
  readonly readOnly?: boolean;
  /**
   * Route-задание, которое показывает план: 3D рисует те же трассы. `null` - на плане трасс нет.
   * Не задано (страница объекта) - автовыбор плана по заданию листа.
   */
  readonly routeJobId?: string | null;
}

/** Связь 3D-вида с общим выбором, слоями и трассами рабочей области: всё, кроме листа. */
export type ICadFloor3dLink = Pick<
  ICadFloor3dViewProps,
  'selectedIds' | 'onSelectConstruction' | 'hiddenCategories' | 'hiddenConstructionIds' | 'routeJobId'
>;

const NO_IDS: ReadonlySet<string> = new Set<string>();

/** Стена, перегородка или плита: клик по ним меняет общий выбор; перемычки, двери и отверстия - только локально. */
const isConstructionPick = (pick: IFloor3dPick): boolean =>
  pick.kind === 'prism' &&
  (pick.category === 'slab' ||
    pick.category === 'masonry' ||
    pick.category === 'monolith' ||
    pick.category === 'frame_partition');

const notReadyText = (error: unknown): string => {
  const status = wallsJobStatus(error);
  return isWallsActive(status)
    ? 'Конструкции считаются. Вид появится сам.'
    : 'Сначала постройте конструкции листа (раздел «Конструкции» справа).';
};

/**
 * 3D-вид этажа открытого листа (ADR-0039): плита с отверстиями, кладка и монолит, перемычки над
 * проёмами, панель высот. Модель собирает сервер; вид только показывает и принимает решения
 * человека (отверстия, высоты листа, толщина плиты проекта). Грузится лениво вместе с three.js.
 */
export const CadFloor3dView: FC<ICadFloor3dViewProps> = ({
  params,
  selectedIds = NO_IDS,
  onSelectConstruction,
  hiddenCategories,
  hiddenConstructionIds,
  readOnly = false,
  routeJobId,
}) => {
  const query = useCadFloor3d(params, true);
  const projectLevels = useCadProjectLevels(params.projectId, true);
  const setHole = useSetFloor3dHole(params);
  const saveSheet = useSaveFloor3dSheetLevels(params);
  const saveProject = useSaveCadProjectLevels(params.projectId);
  // Тот же запрос и ключ, что у вкладки «Конструкции»: кеш общий. Из него - длина, площадь, объём стены.
  const constructions = useCadConstructions(params, true);

  // Ключи подгрупп сцены по слоям-источникам: пересборка только при смене содержимого, не данных.
  const keysNow = useMemo(
    () => layerGroupKeys(constructions.data?.constructions ?? []),
    [constructions.data],
  );
  const [groupKeys, setGroupKeys] = useState(keysNow);
  if (groupKeys.signature !== keysNow.signature) setGroupKeys(keysNow);

  const model = query.data ?? null;
  const plan = useMemo(() => (model ? buildFloor3dPlan(model) : null), [model]);

  // Трассы механики листа: сбой чтения или их отсутствие 3D-вид не ломают. Задание трасс - то же,
  // что рисует план, слои скрываются той же маской (общее хранилище): одна истина на плане и в 3D.
  const routesState = useCadMepRoutes3d({
    projectId: params.projectId,
    revisionId: params.revisionId,
    pageIndex: params.pageIndex,
    view: params.view,
    parentJobId: params.jobId,
    routeJobId,
    enabled: model !== null,
  });
  // ЭОМ и СС этажа (генератор cad_eom) - теми же слоями и маской, что трассы механики.
  const eomState = useCadEomRoutes3d(
    {
      projectId: params.projectId,
      revisionId: params.revisionId,
      pageIndex: params.pageIndex,
      view: params.view,
    },
    model !== null,
  );
  const routesMask = useMepLayerVisibility().mask;
  const routesData = routesState.status === 'ready' ? routesState.data : null;
  const eomData = eomState.status === 'ready' ? eomState.data : null;
  const routes = useMemo<ICadFloor3dRoutes | null>(
    () => (model && (routesData || eomData)
        ? {
            polylines: [...(routesData?.polylines ?? []), ...(eomData?.polylines ?? [])],
            elements: [...(routesData?.elements ?? []), ...(eomData?.elements ?? [])],
            baseZMm: routesBaseZMm(model),
          }
        : null),
    [routesData, eomData, model],
  );

  const [showSlabCap, setShowSlabCap] = useState(false);
  const [viewRequest, setViewRequest] = useState<IFloor3dViewRequest | null>(null);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [popoverError, setPopoverError] = useState<string | null>(null);
  const [picked, setPicked] = useState<{
    pick: IFloor3dPick;
    anchor: { x: number; y: number };
    bounds: { width: number; height: number };
  } | null>(null);
  // Выбранный элемент подсвечивается, пока не снят: клик в пустоту, Esc, закрытие плашки.
  const [selected, setSelected] = useState<IFloor3dPick | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const mep = useFloor3dMepPick(routesData, stage);
  const { clear: clearMep } = mep;

  // Локальное: плашка и подсветка перемычки, двери, отверстия.
  const closeLocal = () => {
    setPicked(null);
    setSelected(null);
    mep.clear();
    setPopoverError(null);
  };
  // Плашка закрыта или выбор снят: общий выбор конструкций тоже очищается.
  const closePick = () => {
    closeLocal();
    onSelectConstruction?.(null);
  };

  const toggleMeasuring = () => {
    closeLocal();
    setMeasuring((on) => !on);
  };

  useEffect(() => {
    if (picked === null && selected === null && mep.pick === null && selectedIds.size === 0 && !measuring) {
      return undefined;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (measuring) {
        setMeasuring(false);
        return;
      }
      setPicked(null);
      setSelected(null);
      clearMep();
      setPopoverError(null);
      onSelectConstruction?.(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [picked, selected, mep.pick, clearMep, selectedIds, measuring, onSelectConstruction]);

  const request = (kind: IFloor3dViewRequest['kind']) =>
    setViewRequest((current) => ({ kind, seq: (current?.seq ?? 0) + 1 }));

  const onPick = (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => {
    // В режиме измерения клик ставит точку замера и плашку не открывает.
    if (measuring) return;
    // Решение по отверстию - запись: в режиме просмотра плашка отверстия не открывается.
    if (readOnly && pick?.kind === 'hole') return;
    setPopoverError(null);
    mep.clear();
    // Повторный клик по уже выбранному элементу снимает выбор и в 3D, и в плане.
    // Признак - открытая плашка этого же элемента (выбор из плана плашку не открывает).
    const again =
      pick !== null &&
      picked !== null &&
      picked.pick.kind === pick.kind &&
      picked.pick.id === pick.id &&
      (onSelectConstruction === undefined || !isConstructionPick(pick) || selectedIds.has(pick.id));
    if (again) {
      closePick();
      return;
    }
    // Стена и плита выбираются общим выбором (его подсвечивает холст), остальное - локально.
    const construction = pick !== null && isConstructionPick(pick);
    setSelected(pick !== null && !construction ? pick : null);
    if (pick === null || construction) onSelectConstruction?.(pick === null ? null : pick.id);
    const rect = stage.current?.getBoundingClientRect();
    setPicked(
      pick === null || !rect ? null : { pick, anchor, bounds: { width: rect.width, height: rect.height } },
    );
  };

  // Трасса или элемент ВИС: повторный клик по выбранному снимает выбор; иначе выбор заменяет
  // конструкцию (общий выбор очищается), плашка открывается у курсора.
  const onPickMep = (pick: IMepPick, anchor: { x: number; y: number }) => {
    if (measuring || routesData === null) return;
    if (mep.isSelected(pick)) {
      closePick();
      return;
    }
    setPicked(null);
    setSelected(null);
    setPopoverError(null);
    onSelectConstruction?.(null);
    mep.select(pick, anchor);
  };

  // «Выбрать стену» в плашке проёма: локальный выбор снимается, стена уходит в общий выбор,
  // плашка переключается на неё в той же точке.
  const selectHost = (id: string) => {
    const prism = plan?.prisms.find(
      (item) => item.id === id && item.category !== 'lintel' && item.category !== 'door',
    );
    setSelected(null);
    setPopoverError(null);
    setPicked((current) =>
      prism === undefined || current === null
        ? null
        : { ...current, pick: { kind: 'prism', category: prism.category, id } },
    );
    onSelectConstruction?.(id);
  };

  // Плашка стены или плиты живёт, пока конструкция в общем выборе: выбор сняли в панели - плашка уходит.
  const popup =
    picked !== null &&
    (onSelectConstruction === undefined ||
      !isConstructionPick(picked.pick) ||
      selectedIds.has(picked.pick.id))
      ? picked
      : null;

  const notReady = query.isError && extractCode(query.error) === WALLS_NOT_READY;
  const outdated = model?.warnings.some((item) => item.code === 'walls_outdated') ?? false;
  const skipped = plan?.skipped.wallsWithoutTop ?? 0;
  const routesStale = routesState.status === 'stale';
  const routesMismatch = routesData !== null && !routesData.heights_match;

  let content: ReactNode;
  if (query.isPending) {
    content = (
      <p role="status" className="p-[var(--s-6)] text-sm text-muted">
        Читаем модель этажа…
      </p>
    );
  } else if (notReady) {
    content = (
      <p role="status" className="p-[var(--s-6)] text-sm text-muted">
        {notReadyText(query.error)}
      </p>
    );
  } else if (query.isError || model === null || plan === null) {
    content = (
      <div className="flex flex-col items-start gap-[var(--s-4)] p-[var(--s-6)]">
        <p role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
          {cadErrorText(query.error)}
        </p>
        <Button className="max-md:h-[44px]" onClick={() => void query.refetch()}>
          Повторить
        </Button>
      </div>
    );
  } else if (canvasError !== null) {
    content = (
      <p role="alert" className="p-[var(--s-6)] text-sm text-danger">
        {canvasError}
      </p>
    );
  } else if (plan.prisms.length === 0) {
    content = (
      <p role="status" className="p-[var(--s-6)] text-sm text-muted">
        {outdated ? 'Пересчитайте конструкции: в прежнем результате нет модели этажа.' : 'В модели этажа нет элементов для показа.'}
      </p>
    );
  } else {
    content = (
      <>
        <CadFloor3dCanvas
          plan={plan}
          routes={routes}
          hiddenRoutesMask={routesMask}
          showSlabCap={showSlabCap}
          viewRequest={viewRequest}
          selected={selected}
          selectedMep={mep.pick}
          selectedIds={selectedIds}
          hiddenCategories={hiddenCategories}
          hiddenConstructionIds={hiddenConstructionIds}
          groupKeyOf={groupKeys.keyOf}
          hostCategoryOf={groupKeys.categoryOf}
          measuring={measuring}
          onPick={onPick}
          onPickMep={onPickMep}
          // Камера пошла - плашка у курсора устарела, а выделение остаётся.
          onMove={() => {
            setPicked(null);
            setPopoverError(null);
            mep.hidePopup();
          }}
          onError={setCanvasError}
        />
        {mep.popup !== null && mep.info !== null && (
          <CadFloor3dMepPopover info={mep.info} anchor={mep.popup.anchor} bounds={mep.popup.bounds} onClose={closePick} />
        )}
        {popup !== null && (
          <CadFloor3dPopover
            pick={popup.pick}
            model={model}
            constructions={constructions.data}
            anchor={popup.anchor}
            bounds={popup.bounds}
            saving={setHole.isPending}
            error={popoverError}
            onDecide={(key, enabled) => {
              setPopoverError(null);
              setHole.mutate(
                { key, enabled },
                { onSuccess: closePick, onError: (error) => setPopoverError(cadErrorText(error)) },
              );
            }}
            onSelectHost={selectHost}
            onClose={closePick}
          />
        )}
      </>
    );
  }

  // Подпись этажом из заголовка плана; заголовка нет - без подписи, как раньше.
  const floorTitle = formatFloorTitle(model?.title, '');
  const interactive = model !== null && plan !== null && plan.prisms.length > 0 && canvasError === null;

  return (
    <div
      data-testid="floor3d-view"
      className="absolute inset-0 z-20 flex min-h-0 flex-col bg-bg"
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="relative z-30 flex flex-none flex-wrap items-center gap-x-[var(--s-2)] gap-y-[var(--s-1)] border-b border-border bg-surface px-[var(--s-4)] py-[var(--s-2)]">
          {floorTitle !== '' && (
            <>
              <h3
                data-testid="floor3d-title"
                title={formatFloorTitleFull(model?.title) ?? undefined}
                className="min-w-0 text-xs font-semibold [overflow-wrap:anywhere]"
              >
                {floorTitle}
              </h3>
              <ToolDivider />
            </>
          )}
          <ToolButton wide label="Сверху" hint="вид сверху на план" disabled={!interactive} onClick={() => request('top')}>
            Сверху
          </ToolButton>
          <ToolButton wide label="Изометрия" hint="вид под углом" disabled={!interactive} onClick={() => request('iso')}>
            Изометрия
          </ToolButton>
          <ToolButton wide label="Вписать" hint="весь этаж в экран" disabled={!interactive} onClick={() => request('fit')}>
            Вписать
          </ToolButton>
          <ToolButton
            wide
            label="Измерить"
            hint="две точки на модели, Esc — выход"
            active={measuring}
            disabled={!interactive}
            onClick={toggleMeasuring}
          >
            Измерить
          </ToolButton>
          <ToolDivider />
          <ToolButton
            wide
            label="Плита сверху"
            hint="показать или скрыть плиту перекрытия"
            active={showSlabCap}
            disabled={!interactive}
            onClick={() => setShowSlabCap((v) => !v)}
          >
            Плита сверху
          </ToolButton>
          {!readOnly && (
            <>
              <ToolDivider />
              <CadFloor3dDxfButton
                params={params}
                model={model}
                title={model?.title}
                disabled={!interactive}
                hasCandidates={model?.slab_holes.some((hole) => hole.state === 'candidate') ?? false}
              />
            </>
          )}
          {model !== null && readOnly && model.warnings.length > 0 && (
            <CadFloor3dInfoPanel label="Предупреждения модели этажа">
              <CadFloor3dWarnings warnings={model.warnings} />
            </CadFloor3dInfoPanel>
          )}
          {model !== null && !readOnly && (
            <CadFloor3dInfoPanel>
              <CadFloor3dHeights
                heights={model.heights}
                elevationKnown={model.elevation_known}
                projectLevels={projectLevels.data}
                sheetSaving={saveSheet.isPending}
                projectSaving={saveProject.isPending}
                error={panelError}
                onSaveSheet={(write) => {
                  setPanelError(null);
                  saveSheet.mutate(write, { onError: (error) => setPanelError(cadErrorText(error)) });
                }}
                onSaveProject={(write) => {
                  setPanelError(null);
                  saveProject.mutate(write, { onError: (error) => setPanelError(cadErrorText(error)) });
                }}
              />
              <CadFloor3dHoleList
                holes={model.slab_holes}
                saving={setHole.isPending}
                onDecide={(key, enabled) => {
                  setPanelError(null);
                  setHole.mutate({ key, enabled }, { onError: (error) => setPanelError(cadErrorText(error)) });
                }}
              />
              <CadFloor3dWarnings warnings={model.warnings} />
            </CadFloor3dInfoPanel>
          )}
        </div>
        {(outdated || skipped > 0 || routesStale || routesMismatch) && (
          <div className="flex flex-none flex-col gap-[var(--s-2)] border-b border-border bg-surface px-[var(--s-4)] py-[var(--s-3)]">
            {outdated && (
              <p role="alert" className="text-xs text-danger">
                Пересчитайте конструкции: результат построен прежней версией, плиты и перемычек в нём нет.
              </p>
            )}
            {routesStale && (
              <p role="note" className="text-xs text-warning">
                Трассы построены старой версией генератора — перестройте трассы.
              </p>
            )}
            {routesMismatch && (
              <p role="note" className="text-xs text-warning">
                Высоты трасс не совпадают с уровнями листа — перестройте трассы.
              </p>
            )}
            {skipped > 0 && (
              <p role="note" className="text-xs text-muted">
                Стены без высоты не построены: {skipped}.
              </p>
            )}
          </div>
        )}
        <div ref={stage} className="relative min-h-0 flex-1 overflow-hidden">
          {content}
          {interactive && measuring && (
            <p
              role="status"
              className="pointer-events-none absolute top-[var(--s-4)] left-[var(--s-4)] max-w-[calc(100%-16px)] rounded-[var(--radius-sm)] bg-surface/80 px-[var(--s-3)] py-[var(--s-2)] text-xs"
            >
              Измерение: укажите две точки. Esc - выход.
            </p>
          )}
          {interactive && <CadFloor3dLegend />}
        </div>
      </div>
    </div>
  );
};
