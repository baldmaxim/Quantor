'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { alignmentNote, formatElevation } from '@/lib/cad/building3d-geometry';
import { countWalls } from '@/lib/cad/building-viewer-geometry';
import { formatNumber } from '@/lib/cad/view-format';

import { BuildingFloorTotals } from './BuildingFloorTotals';
import type { IFloorViewParams } from './useFloorViewParams';

interface IBuildingFloorPanelProps {
  /** Выбранный этаж; `null` - ничего не выбрано. */
  readonly floor: CadBuilding3dFloorRead | null;
  /** Число этажей выбранного здания: от него зависит пометка «не совмещён». */
  readonly groupFloorCount: number;
  readonly view: IFloorViewParams;
  /** Детальный вид уже открыт: кнопка «Этаж подробно» не нужна. */
  readonly detail: boolean;
  readonly onOpenDetail: () => void;
  readonly onOpenSheet: (floor: CadBuilding3dFloorRead) => void;
}

const Row: FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-[var(--s-3)] py-[var(--s-1)] text-sm">
    <dt className="flex-none text-muted">{label}</dt>
    <dd className="min-w-0 text-right [overflow-wrap:anywhere]">{value}</dd>
  </div>
);

const NOT_DEFINED = 'не определена, показана типовая';

const meters = (mm: number): string => formatNumber(mm / 1000, 3, 'м');

/** Параметры выбранного этажа, число конструкций по видам и итоги листа (считает сервер). */
export const BuildingFloorPanel: FC<IBuildingFloorPanelProps> = ({
  floor,
  groupFloorCount,
  view,
  detail,
  onOpenDetail,
  onOpenSheet,
}) => {
  if (floor === null) {
    return <p className="p-[var(--s-4)] text-sm text-muted">Нажмите на этаж</p>;
  }
  const note = alignmentNote(floor, groupFloorCount);
  const counts = countWalls(floor.walls);
  const place = [floor.corps ? `корпус ${floor.corps}` : null, floor.section ? `секция ${floor.section}` : null]
    .filter((part): part is string => part !== null)
    .join(', ');

  return (
    <section aria-label="Этаж" className="flex min-w-0 flex-col gap-[var(--s-4)] p-[var(--s-4)]">
      <div className="min-w-0">
        <h2 className="text-base font-medium [overflow-wrap:anywhere]">{floor.label}</h2>
        {place !== '' && <p className="text-xs text-muted">{place}</p>}
      </div>
      <dl className="divide-y divide-border">
        <Row label="Отметка" value={floor.elevation_known ? formatElevation(floor.base_z_mm) : 'не определена'} />
        <Row
          label="Высота этажа"
          value={floor.floor_height_known ? meters(floor.floor_height_mm) : `${NOT_DEFINED} (${meters(floor.floor_height_mm)})`}
        />
        <Row
          label="Толщина плиты"
          value={
            floor.slab_thickness_known ? meters(floor.slab_thickness_mm) : `${NOT_DEFINED} (${meters(floor.slab_thickness_mm)})`
          }
        />
        {note && <Row label="Совмещение" value={note.text} />}
        {counts && (
          <>
            <Row label="Монолит, конструкций" value={String(counts.monolith)} />
            <Row label="Кладка, конструкций" value={String(counts.masonry)} />
            {counts.partition > 0 && <Row label="Перегородки ГКЛ, конструкций" value={String(counts.partition)} />}
          </>
        )}
      </dl>
      <div className="flex flex-wrap gap-[var(--s-3)]">
        {!detail && (
          <Button variant="primary" className="min-h-[44px]" disabled={view.params === null} onClick={onOpenDetail}>
            Этаж подробно
          </Button>
        )}
        <Button className="min-h-[44px]" onClick={() => onOpenSheet(floor)}>
          Открыть лист в CAD
        </Button>
      </div>
      <BuildingFloorTotals params={view.params} pending={view.pending} />
    </section>
  );
};
