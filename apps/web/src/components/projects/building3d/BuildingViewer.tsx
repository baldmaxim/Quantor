'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useMemo, useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
import { CadBuilding3dGroupSelect } from '@/components/workspace/cad/building3d/CadBuilding3dGroupSelect';
import { CadFloor3dLazy } from '@/components/workspace/cad/floor3d/CadFloor3dLazy';
import { filterFloorsByGroup, floorKey, resolveGroupKey, splitFloors } from '@/lib/cad/building3d-geometry';
import { useCadBuilding3dWalls } from '@/lib/cad/building3d-queries';
import { cadErrorText } from '@/lib/cad/errors';

import { BuildingFloorList } from './BuildingFloorList';
import { BuildingFloorPanel } from './BuildingFloorPanel';
import { BuildingViewerCanvas } from './BuildingViewerCanvas';
import { useFloorViewParams } from './useFloorViewParams';

export interface IBuildingViewerSelection {
  /** Ключ выбранного этажа (`floorKey`); `null` - ничего не выбрано. */
  readonly floor: string | null;
  /** Детальный 3D этажа на этой же странице. */
  readonly detail: boolean;
}

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
  'min-w-0 flex-none divide-y divide-border border-t border-border bg-surface lg:min-h-0 lg:w-[320px] lg:overflow-y-auto lg:border-l lg:border-t-0 lg:[overscroll-behavior:contain]';

const Message: FC<{ children: ReactNode; alert?: boolean }> = ({ children, alert = false }) => (
  <p role={alert ? 'alert' : 'status'} className={alert ? 'p-[var(--s-5)] text-sm text-danger' : 'p-[var(--s-5)] text-sm text-muted'}>
    {children}
  </p>
);

/**
 * Просмотрщик объекта: здание из настоящих стен всех этажей (вращение, наклон, зум), клик по этажу -
 * параметры этажа справа или под холстом, двойной клик или «Этаж подробно» - детальный 3D этажа на этой
 * же странице (только чтение). Корпус и секция выбираются переключателем; «Разнести этажи» раздвигает
 * этажи по вертикали.
 */
export const BuildingViewer: FC<IBuildingViewerProps> = ({ projectId, selection, onSelectionChange, onOpenSheet }) => {
  const query = useCadBuilding3dWalls(projectId);
  const [chosenGroup, setChosenGroup] = useState<string | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [exploded, setExploded] = useState(false);
  const [fitSeq, setFitSeq] = useState(0);
  const [canvasError, setCanvasError] = useState<string | null>(null);

  const groups = useMemo(() => query.data?.groups ?? [], [query.data]);
  const allFloors = query.data?.floors;
  // Здание выбранного этажа из адреса важнее умолчания, но не ручного выбора.
  const sheetGroup = useMemo(
    () => (allFloors ?? []).find((item) => floorKey(item) === selection.floor)?.group_key ?? null,
    [allFloors, selection.floor],
  );
  const groupKey = resolveGroupKey(groups, chosenGroup, sheetGroup);
  const floors = useMemo(() => filterFloorsByGroup(allFloors ?? [], groupKey), [allFloors, groupKey]);
  const selected = useMemo(
    () => floors.find((item) => floorKey(item) === selection.floor) ?? null,
    [floors, selection.floor],
  );
  const hasKnown = useMemo(() => splitFloors(floors).known.length > 0, [floors]);
  const view = useFloorViewParams(projectId, selected);
  const detail = selection.detail && selected !== null;

  const select = (key: string): void => onSelectionChange({ floor: key, detail });
  const openDetail = (key: string): void => {
    setHoverKey(null);
    onSelectionChange({ floor: key, detail: true });
  };

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
          selectedKey={selection.floor}
          hoverKey={hoverKey}
          exploded={exploded}
          fitSeq={fitSeq}
          onHover={setHoverKey}
          onSelect={select}
          onOpenDetail={openDetail}
          onError={setCanvasError}
        />
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
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto [overscroll-behavior:contain] lg:flex-row lg:overflow-hidden">
        <div className={STAGE}>{stage}</div>
        <aside aria-label="Этаж и список этажей" className={SIDE}>
          <BuildingFloorPanel
            floor={selected}
            groupFloorCount={floors.length}
            view={view}
            detail={detail}
            onOpenDetail={() => selected !== null && openDetail(floorKey(selected))}
            onOpenSheet={onOpenSheet}
          />
          <BuildingFloorList floors={floors} selectedKey={selection.floor} onSelect={select} onHover={setHoverKey} />
        </aside>
      </div>
    );
  }

  return (
    <section aria-label="Просмотрщик объекта" className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-surface">
      <div className="flex flex-none flex-wrap items-end gap-x-[var(--s-4)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-4)] py-[var(--s-2)]">
        <div className="min-w-0 max-w-full flex-none sm:w-[260px]">
          <CadBuilding3dGroupSelect
            groups={groups}
            value={groupKey ?? ''}
            onChange={(key) => {
              setChosenGroup(key);
              setHoverKey(null);
              onSelectionChange({ floor: null, detail: false });
            }}
          />
        </div>
        {detail ? (
          <Button className="min-h-[44px]" onClick={() => onSelectionChange({ floor: selection.floor, detail: false })}>
            ← К зданию
          </Button>
        ) : (
          <>
            <Button
              className="min-h-[44px]"
              aria-pressed={exploded}
              variant={exploded ? 'primary' : 'default'}
              disabled={!hasKnown || canvasError !== null}
              onClick={() => setExploded((value) => !value)}
            >
              Разнести этажи
            </Button>
            <Button
              className="min-h-[44px]"
              disabled={!hasKnown || canvasError !== null}
              onClick={() => setFitSeq((value) => value + 1)}
            >
              Вписать
            </Button>
          </>
        )}
      </div>
      {body}
    </section>
  );
};
