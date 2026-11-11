'use client';

import { cx } from '@quantor/ui';
import { useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
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
import type { IFloor3dPick } from '@/lib/cad/floor3d-scene';
import type { CadLayerCategory } from '@/lib/cad/layer-categories';
import { useMepLayerVisibility } from '@/lib/cad/mep-layers';
import { useCadMepRoutes3d } from '@/lib/cad/mep-routes3d-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { extractCode } from '@/lib/errors';

import { CadFloor3dCanvas, type ICadFloor3dRoutes, type IFloor3dViewRequest } from './CadFloor3dCanvas';
import { CadFloor3dDxfButton } from './CadFloor3dDxfButton';
import { CadFloor3dHeights } from './CadFloor3dHeights';
import { CadFloor3dHoleList } from './CadFloor3dHoleList';
import { CadFloor3dInfoPanel } from './CadFloor3dInfoPanel';
import { CadFloor3dPopover } from './CadFloor3dPopover';

export interface ICadFloor3dViewProps {
  /** Лист и вид, которые показывает план: те же задание, страница и вид. */
  readonly params: ICadViewParams;
  /** Общий выбор конструкций плана и 3D: подсвечиваются все его стены и плита. */
  readonly selectedIds?: ReadonlySet<string>;
  /** Клик по стене или плите - выбор этой конструкции; `null` - выбор снят (пустота, Esc, закрытие плашки). */
  readonly onSelectConstruction?: (id: string | null) => void;
  /** Скрытые категории вкладки «Слои». */
  readonly hiddenCategories?: ReadonlySet<CadLayerCategory>;
}

/** Связь 3D-вида с общим выбором и слоями рабочей области: всё, кроме листа. */
export type ICadFloor3dLink = Pick<
  ICadFloor3dViewProps,
  'selectedIds' | 'onSelectConstruction' | 'hiddenCategories'
>;

const NO_IDS: ReadonlySet<string> = new Set<string>();

/** Стена, перегородка или плита: клик по ним меняет общий выбор; перемычки, двери и отверстия - только локально. */
const isConstructionPick = (pick: IFloor3dPick): boolean =>
  pick.kind === 'prism' &&
  (pick.category === 'slab' ||
    pick.category === 'masonry' ||
    pick.category === 'monolith' ||
    pick.category === 'frame_partition');

const LEGEND: readonly { readonly label: string; readonly className: string }[] = [
  { label: 'Плита', className: 'bg-border-strong' },
  { label: 'Кладка', className: 'bg-[var(--cad-construction-masonry)]' },
  { label: 'Монолит', className: 'bg-[var(--cad-construction-monolith)]' },
  // Цвет как у кладки (так же в 2D): перегородка отличается штрихом, отдельного токена нет.
  { label: 'Перегородки ГКЛ', className: 'bg-[var(--cad-construction-masonry)]' },
  { label: 'Перемычки', className: 'bg-[var(--cad-construction-check)]' },
  { label: 'Двери', className: 'bg-[var(--cad-layer-6)]' },
  { label: 'Отверстие (кандидат)', className: 'bg-danger' },
  { label: 'Отверстие (включено)', className: 'bg-success' },
  { label: 'Не отверстие', className: 'bg-[var(--muted)]' },
];

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
}) => {
  const query = useCadFloor3d(params, true);
  const projectLevels = useCadProjectLevels(params.projectId, true);
  const setHole = useSetFloor3dHole(params);
  const saveSheet = useSaveFloor3dSheetLevels(params);
  const saveProject = useSaveCadProjectLevels(params.projectId);
  // Тот же запрос и ключ, что у вкладки «Конструкции»: кеш общий. Из него - длина, площадь, объём стены.
  const constructions = useCadConstructions(params, true);

  const model = query.data ?? null;
  const plan = useMemo(() => (model ? buildFloor3dPlan(model) : null), [model]);

  // Трассы механики листа: сбой чтения или их отсутствие 3D-вид не ломают. Слои трасс скрываются той
  // же маской, что и в 2D (общее хранилище), поэтому одна истина на плане и в 3D.
  const routesState = useCadMepRoutes3d({
    projectId: params.projectId,
    revisionId: params.revisionId,
    pageIndex: params.pageIndex,
    view: params.view,
    enabled: model !== null,
  });
  const routesMask = useMepLayerVisibility().mask;
  const routesData = routesState.status === 'ready' ? routesState.data : null;
  const routes = useMemo<ICadFloor3dRoutes | null>(
    () => (routesData && model ? { polylines: routesData.polylines, baseZMm: model.base_z_mm } : null),
    [routesData, model],
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

  // Локальное: плашка и подсветка перемычки, двери, отверстия.
  const closeLocal = () => {
    setPicked(null);
    setSelected(null);
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
    if (picked === null && selected === null && selectedIds.size === 0 && !measuring) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (measuring) {
        setMeasuring(false);
        return;
      }
      setPicked(null);
      setSelected(null);
      setPopoverError(null);
      onSelectConstruction?.(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [picked, selected, selectedIds, measuring, onSelectConstruction]);

  const request = (kind: IFloor3dViewRequest['kind']) =>
    setViewRequest((current) => ({ kind, seq: (current?.seq ?? 0) + 1 }));

  const onPick = (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => {
    // В режиме измерения клик ставит точку замера и плашку не открывает.
    if (measuring) return;
    setPopoverError(null);
    // Стена и плита выбираются общим выбором (его подсвечивает холст), остальное - локально.
    const construction = pick !== null && isConstructionPick(pick);
    setSelected(pick !== null && !construction ? pick : null);
    if (pick === null || construction) onSelectConstruction?.(pick === null ? null : pick.id);
    const rect = stage.current?.getBoundingClientRect();
    setPicked(
      pick === null || !rect ? null : { pick, anchor, bounds: { width: rect.width, height: rect.height } },
    );
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
          selectedIds={selectedIds}
          hiddenCategories={hiddenCategories}
          measuring={measuring}
          onPick={onPick}
          // Камера пошла - плашка у курсора устарела, а выделение остаётся.
          onMove={() => {
            setPicked(null);
            setPopoverError(null);
          }}
          onError={setCanvasError}
        />
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
        <div className="relative z-30 flex flex-none flex-wrap items-center gap-[var(--s-3)] border-b border-border bg-surface px-[var(--s-4)] py-[var(--s-3)]">
          {floorTitle !== '' && (
            <h3
              data-testid="floor3d-title"
              title={formatFloorTitleFull(model?.title) ?? undefined}
              className="min-w-0 text-sm font-semibold [overflow-wrap:anywhere]"
            >
              {floorTitle}
            </h3>
          )}
          <Button disabled={!interactive} className="max-md:h-[44px]" onClick={() => request('top')}>
            Сверху
          </Button>
          <Button disabled={!interactive} className="max-md:h-[44px]" onClick={() => request('iso')}>
            Изометрия
          </Button>
          <Button disabled={!interactive} className="max-md:h-[44px]" onClick={() => request('fit')}>
            Вписать
          </Button>
          <Button
            disabled={!interactive}
            aria-pressed={measuring}
            className={cx('max-md:h-[44px]', measuring && 'border-accent text-accent')}
            onClick={toggleMeasuring}
          >
            Измерить
          </Button>
          <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-xs md:min-h-0">
            <input
              type="checkbox"
              checked={showSlabCap}
              disabled={!interactive}
              onChange={(event) => setShowSlabCap(event.target.checked)}
              className="h-[20px] w-[20px] accent-[var(--accent)]"
            />
            Плита сверху
          </label>
          <CadFloor3dDxfButton
            params={params}
            model={model}
            title={model?.title}
            disabled={!interactive}
            hasCandidates={model?.slab_holes.some((hole) => hole.state === 'candidate') ?? false}
          />
          {model !== null && (
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
              {model.warnings.length > 0 && (
                <section aria-label="Предупреждения" className="flex min-w-0 flex-col gap-[var(--s-3)]">
                  <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                    Предупреждения
                  </h4>
                  <ul className="flex flex-col gap-[var(--s-2)]">
                    {model.warnings.map((item) => (
                      <li key={`${item.code}:${item.message}`} className="text-xs text-warning [overflow-wrap:anywhere]">
                        {item.message}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
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
          {interactive && (
            <ul
              aria-label="Условные обозначения"
              className="pointer-events-none absolute bottom-[var(--s-4)] left-[var(--s-4)] flex max-w-[calc(100%-16px)] flex-wrap gap-x-[var(--s-4)] gap-y-[var(--s-2)] rounded-[var(--radius-sm)] bg-surface/80 px-[var(--s-3)] py-[var(--s-2)] text-xs"
            >
              {LEGEND.map((item) => (
                <li key={item.label} className="flex items-center gap-[var(--s-2)]">
                  <span aria-hidden="true" className={cx('h-[10px] w-[10px] rounded-[2px]', item.className)} />
                  {item.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};
