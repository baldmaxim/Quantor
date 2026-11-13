'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { cx } from '@quantor/ui';
import { useMemo, type FC } from 'react';

import { alignmentNote, floorKey, formatElevation, splitFloors } from '@/lib/cad/building3d-geometry';

interface IBuildingFloorListProps {
  /** Этажи выбранного здания. */
  readonly floors: readonly CadBuilding3dFloorRead[];
  readonly selectedKey: string | null;
  readonly onSelect: (key: string) => void;
  readonly onHover: (key: string | null) => void;
}

const ROW =
  'flex min-h-[44px] w-full items-center justify-between gap-[var(--s-3)] px-[var(--s-4)] py-[var(--s-2)] text-left text-sm transition-colors motion-reduce:transition-none hover:bg-bg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

/**
 * Список этажей здания: с отметкой сверху вниз, без отметки - внизу (в 3D они не строятся). Выбор и
 * наведение синхронны с холстом.
 */
export const BuildingFloorList: FC<IBuildingFloorListProps> = ({ floors, selectedKey, onSelect, onHover }) => {
  const list = useMemo(() => splitFloors(floors), [floors]);

  const renderRow = (floor: CadBuilding3dFloorRead) => {
    const key = floorKey(floor);
    const selected = key === selectedKey;
    const note = alignmentNote(floor, floors.length);
    return (
      <li key={key}>
        <button
          type="button"
          aria-current={selected ? 'true' : undefined}
          title={note?.title ?? undefined}
          className={cx(ROW, selected ? 'bg-bg text-accent' : 'text-text')}
          onClick={() => onSelect(key)}
          onMouseEnter={() => onHover(key)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(key)}
          onBlur={() => onHover(null)}
        >
          <span className="min-w-0 [overflow-wrap:anywhere]">
            {floor.label}
            {note && (
              <span className={cx('block text-xs', note.warn ? 'text-warning' : 'text-muted')}>{note.text}</span>
            )}
          </span>
          <span className="flex-none text-xs text-muted">
            {floor.elevation_known ? formatElevation(floor.base_z_mm) : 'отметка не определена, в 3D нет'}
          </span>
        </button>
      </li>
    );
  };

  return (
    <ul aria-label="Этажи" className="divide-y divide-border">
      {list.known.map(renderRow)}
      {list.unknown.map(renderRow)}
    </ul>
  );
};
