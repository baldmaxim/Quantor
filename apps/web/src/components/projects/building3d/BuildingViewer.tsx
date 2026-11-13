'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
import { CadFloor3dLazy } from '@/components/workspace/cad/floor3d/CadFloor3dLazy';
import { Splitter } from '@/components/workspace/Splitter';
import { filterFloorsByGroup, floorKey, resolveGroupKey, splitFloors } from '@/lib/cad/building3d-geometry';
import { useCadBuilding3dWalls } from '@/lib/cad/building3d-queries';
import { ALL_GROUPS_KEY } from '@/lib/cad/building-viewer-layout';
import { useCadConstructions } from '@/lib/cad/constructions-queries';
import { doorsOf } from '@/lib/cad/constructions';
import { cadErrorText } from '@/lib/cad/errors';
import { findConstruction } from '@/lib/cad/floor3d-volume';

import { BuildingConstructionPanel } from './BuildingConstructionPanel';
import { BuildingFloorList } from './BuildingFloorList';
import { BuildingFloorPanel } from './BuildingFloorPanel';
import { BuildingViewerCanvas } from './BuildingViewerCanvas';
import { BuildingViewerToolbar } from './BuildingViewerToolbar';
import { useFloorViewParams } from './useFloorViewParams';
import { useResizableWidth } from './useResizableWidth';

export interface IBuildingViewerSelection {
  /** Выбранное здание (`group_key`) или `all` - «Весь объект»; `null` - по умолчанию. */
  readonly group: string | null;
  /** Ключ выбранного этажа (`floorKey`); `null` - ничего не выбрано. */
  readonly floor: string | null;
  /** Детальный 3D этажа на этой же странице. */
  readonly detail: boolean;
  /** Выбранная конструкция выбранного этажа (`id` из walls.json); `null` - не выбрана. */
  readonly construction: string | null;
}

/** Правая панель: ширину меняют разделителем, хранится в `localStorage`. */
const SIDE_WIDTH = { min: 240, max: 640, initial: 320 } as const;
const SIDE_WIDTH_KEY = 'quantor.building3d.sideWidth';

export interface IBuildingViewerProps {
  readonly projectId: string;
  /** Выбор живёт в адресе страницы: им управляет родитель. */
  readonly selection: IBuildingViewerSelection;
  readonly onSelectionChange: (next: IBuildingViewerSelection) => void;
  /** Открыть лист этажа в рабочей области (вкладка CAD). */
  readonly onOpenSheet: (floor: CadBuilding3dFloorRead) => void;
}

// Холст: на телефоне ~60dvh под панелью инструментов, от lg - вся свободная площадь.
const STAGE =
  'relative h-[60dvh] min-h-[320px] min-w-0 flex-none overflow-hidden lg:h-auto lg:min-h-0 lg:flex-1';
const SIDE =
  'min-w-0 flex-none divide-y divide-border border-t border-border bg-surface lg:min-h-0 lg:w-[var(--bv-side)] lg:overflow-y-auto lg:border-t-0 lg:[overscroll-behavior:contain]';

const Message: FC<{ children: ReactNode; alert?: boolean }> = ({ children, alert = false }) => (
  <p role={alert ? 'alert' : 'status'} className={alert ? 'p-[var(--s-5)] text-sm text-danger' : 'p-[var(--s-5)] text-sm text-muted'}>
    {children}
  </p>
);

/**
 * Просмотрщик объекта: здание из настоящих стен всех этажей (вращение, наклон, зум), клик по этажу -
 * параметры этажа справа или под холстом, двойной клик или «Этаж подробно» - детальный 3D этажа на этой
 * же странице (только чтение). Корпус и секция выбираются переключателем; «Разнести этажи» раздвигает
 * этажи по вертикали. «Весь объект» ставит все корпуса в один ряд (раскладка условная). Клик по стене
 * выбранного этажа выбирает конструкцию: её параметры - над панелью этажа. Правая панель тянется
 * разделителем.
 */
export const BuildingViewer: FC<IBuildingViewerProps> = ({ projectId, selection, onSelectionChange, onOpenSheet }) => {
  const query = useCadBuilding3dWalls(projectId);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [exploded, setExploded] = useState(false);
  const [fitSeq, setFitSeq] = useState(0);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [sideWidth, setSideWidth] = useResizableWidth(SIDE_WIDTH_KEY, SIDE_WIDTH);
  const container = useRef<HTMLDivElement>(null);

  const groups = useMemo(() => query.data?.groups ?? [], [query.data]);
  const allFloors = query.data?.floors;
  // Здание выбранного этажа из адреса важнее умолчания, но не ручного выбора.
  const sheetGroup = useMemo(
    () => (allFloors ?? []).find((item) => floorKey(item) === selection.floor)?.group_key ?? null,
    [allFloors, selection.floor],
  );
  const groupKey = resolveGroupKey(groups, selection.group, sheetGroup);
  // Одно здание - «всего объекта» не отличить от него: режим только при двух и более группах.
  const isAll = groups.length > 1 && selection.group === ALL_GROUPS_KEY;
  const floors = useMemo(
    () => (isAll ? (allFloors ?? []) : filterFloorsByGroup(allFloors ?? [], groupKey)),
    [allFloors, groupKey, isAll],
  );
  const selected = useMemo(
    () => floors.find((item) => floorKey(item) === selection.floor) ?? null,
    [floors, selection.floor],
  );
  const hasKnown = useMemo(() => splitFloors(floors).known.length > 0, [floors]);
  const view = useFloorViewParams(projectId, selected);
  const detail = selection.detail && selected !== null;
  // Тот же запрос и ключ, что у итогов этажа: кеш общий, лишнего чтения нет.
  const constructions = useCadConstructions(view.params, true);
  const groupFloorCount = useMemo(
    () => (selected === null ? 0 : floors.filter((item) => item.group_key === selected.group_key).length),
    [floors, selected],
  );

  const select = (key: string): void =>
    onSelectionChange({ ...selection, floor: key, detail, construction: key === selection.floor ? selection.construction : null });
  const selectConstruction = (id: string | null): void => onSelectionChange({ ...selection, construction: id });
  const openDetail = (key: string): void => {
    setHoverKey(null);
    onSelectionChange({ ...selection, floor: key, detail: true, construction: null });
  };

  // Esc: сначала конструкция, вторым нажатием - этаж. Детальный вид Esc обрабатывает сам.
  useEffect(() => {
    if (detail || selection.floor === null) return undefined;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (event.target instanceof HTMLSelectElement || event.target instanceof HTMLInputElement) return;
      onSelectionChange(
        selection.construction !== null
          ? { ...selection, construction: null }
          : { ...selection, floor: null, detail: false, construction: null },
      );
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detail, selection, onSelectionChange]);

  const construction =
    selection.construction === null ? null : findConstruction(constructions.data, selection.construction);
  const doors =
    construction === null || constructions.data === undefined
      ? 0
      : doorsOf(constructions.data.openings, construction).length;
  let constructionNote: string | null = null;
  if (construction === null) {
    if (view.params === null) constructionNote = view.pending ? 'Читаем лист этажа…' : 'У листа этажа нет готового результата CAD.';
    else if (constructions.isPending) constructionNote = 'Читаем конструкцию…';
    else if (constructions.isError) constructionNote = cadErrorText(constructions.error);
    else constructionNote = 'Конструкции нет в расчёте листа: пересчитайте конструкции или снимите выбор.';
  }

  const sideStyle: Record<string, string> = { '--bv-side': `${sideWidth}px` };

  let stage: ReactNode;
  if (detail && selected !== null) {
    stage =
      view.params === null ? (
        <Message>{view.pending ? 'Загружаем лист этажа…' : 'У листа этажа нет готового результата CAD.'}</Message>
      ) : (
        <CadFloor3dLazy key={floorKey(selected)} params={view.params} readOnly />
      );
  } else if (canvasError !== null) {
    stage = <Message alert>{canvasError}</Message>;
  } else if (!hasKnown) {
    stage = <Message>Ни у одного этажа не определена отметка: в 3D нечего строить.</Message>;
  } else {
    stage = (
      <>
        <BuildingViewerCanvas
          floors={floors}
          allGroups={isAll ? groups : null}
          selectedKey={selection.floor}
          hoverKey={hoverKey}
          constructionId={selection.construction}
          exploded={exploded}
          fitSeq={fitSeq}
          onHover={setHoverKey}
          onSelect={select}
          onSelectConstruction={selectConstruction}
          onOpenDetail={openDetail}
          onError={setCanvasError}
        />
        {isAll && (
          <p className="pointer-events-none absolute top-[var(--s-3)] left-[var(--s-3)] max-w-[calc(100%-24px)] rounded-[var(--radius-sm)] border border-border bg-surface/90 px-[var(--s-3)] py-[var(--s-1)] text-xs text-muted">
            Взаимное расположение корпусов условное
          </p>
        )}
        {selected !== null && (
          <div className="pointer-events-none absolute right-[var(--s-3)] bottom-[var(--s-3)] left-[var(--s-3)] flex items-center justify-between gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border bg-surface/90 px-[var(--s-3)] py-[var(--s-2)] text-sm lg:hidden">
            <span className="min-w-0 [overflow-wrap:anywhere]">{selected.label}</span>
            <Button
              variant="primary"
              className="pointer-events-auto min-h-[44px] flex-none"
              disabled={view.params === null}
              onClick={() => openDetail(floorKey(selected))}
            >
              Подробно
            </Button>
          </div>
        )}
      </>
    );
  }

  let body: ReactNode;
  if (query.isPending) {
    body = <Message>Загружаем здание…</Message>;
  } else if (query.isError) {
    body = (
      <div className="flex flex-col items-start gap-[var(--s-3)] p-[var(--s-5)]">
        <p role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
          {cadErrorText(query.error)}
        </p>
        <Button className="min-h-[44px]" onClick={() => void query.refetch()}>
          Повторить
        </Button>
      </div>
    );
  } else if (floors.length === 0) {
    body = <Message>Нет листов с конструкциями</Message>;
  } else {
    body = (
      <div
        ref={container}
        // Ширина правой панели меняется пользователем - динамическое значение.
        style={sideStyle}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto [overscroll-behavior:contain] lg:flex-row lg:overflow-hidden"
      >
        <div className={STAGE}>{stage}</div>
        {/* Ручки на телефоне нет: панель под холстом на всю ширину. */}
        <div className="hidden lg:flex">
          <Splitter
            side="right"
            label="Ширина правой панели"
            width={sideWidth}
            min={SIDE_WIDTH.min}
            max={SIDE_WIDTH.max}
            previewTarget={container}
            previewVariable="--bv-side"
            onResize={setSideWidth}
          />
        </div>
        <aside aria-label="Этаж и список этажей" className={SIDE}>
          {selection.construction !== null && selected !== null && (
            <BuildingConstructionPanel
              construction={construction}
              doors={doors}
              note={constructionNote}
              onClear={() => selectConstruction(null)}
            />
          )}
          <BuildingFloorPanel
            floor={selected}
            groupFloorCount={groupFloorCount}
            view={view}
            detail={detail}
            onOpenDetail={() => selected !== null && openDetail(floorKey(selected))}
            onOpenSheet={onOpenSheet}
          />
          <BuildingFloorList
            floors={floors}
            groups={isAll ? groups : undefined}
            selectedKey={selection.floor}
            onSelect={select}
            onHover={setHoverKey}
          />
        </aside>
      </div>
    );
  }

  return (
    <section aria-label="Просмотрщик объекта" className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-surface">
      <BuildingViewerToolbar
        groups={groups}
        groupValue={isAll ? ALL_GROUPS_KEY : (groupKey ?? '')}
        detail={detail}
        exploded={exploded}
        disabled={!hasKnown || canvasError !== null}
        onGroupChange={(key) => {
          setHoverKey(null);
          onSelectionChange({ group: key, floor: null, detail: false, construction: null });
        }}
        onToggleExploded={() => setExploded((value) => !value)}
        onFit={() => setFitSeq((value) => value + 1)}
        onBack={() => onSelectionChange({ ...selection, detail: false })}
      />
      {body}
    </section>
  );
};
