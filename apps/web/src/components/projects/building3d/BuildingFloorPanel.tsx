'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { alignmentNote, alignmentQuality, formatElevation } from '@/lib/cad/building3d-geometry';
import { countWalls } from '@/lib/cad/building-viewer-geometry';
import { formatNumber } from '@/lib/cad/view-format';

import { BuildingFloorTotals } from './BuildingFloorTotals';
import type { IFloorViewParams } from './useFloorViewParams';

interface IBuildingFloorPanelProps {
  /** Выбранный этаж; `null` - ничего не выбрано. */
  readonly floor: CadBuilding3dFloorRead | null;
  /** Число листов здания выбранного этажа: здание из одного листа совмещать не с чем. */
  readonly groupSheetCount: number;
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
const BY_STACK = 'не определена, показана по отметке следующего этажа';

const meters = (mm: number): string => formatNumber(mm / 1000, 3, 'м');

/** «Окна: принятые N, кандидаты M» (кандидат - вид фасада не принят); окон не запрошено - «—». */
export const windowsSummary = (windows: CadBuilding3dFloorRead['windows']): string => {
  if (windows === null || windows === undefined) return '—';
  const candidates = windows.filter((window) => !window.accepted).length;
  return `принятые ${windows.length - candidates}, кандидаты ${candidates}`;
};

/** Параметры выбранного этажа, число конструкций по видам и итоги листа (считает сервер). */
export const BuildingFloorPanel: FC<IBuildingFloorPanelProps> = ({
  floor,
  groupSheetCount,
  view,
  detail,
  onOpenDetail,
  onOpenSheet,
}) => {
  if (floor === null) {
    // Пока этаж не выбран - что значат пометки списка и что с ними делать.
    return (
      <div className="flex flex-col gap-[var(--s-3)] p-[var(--s-4)] text-sm text-muted">
        <p className="m-0">Нажмите на этаж</p>
        <ul className="m-0 flex list-disc flex-col gap-[var(--s-2)] pl-[var(--s-5)] text-xs">
          <li>
            «по осям …» — этаж совмещён с эталонным по общим осям; цвет точки — качество совмещения.
          </li>
          <li>
            «не совмещён по осям» — общих осей с эталоном не нашлось, этаж стоит условно: откройте
            его лист и проверьте оси.
          </li>
          <li>
            «отметка не определена» — этажа нет в 3D: проверьте этаж и отметку в паспорте листа
            («Листы комплекта»).
          </li>
          <li>
            «не поставлен на объект» у корпуса — место корпуса условное: «Привязать вручную» под
            названием корпуса (корпус «Весь объект»).
          </li>
        </ul>
      </div>
    );
  }
  const note = alignmentNote(floor, groupSheetCount);
  const typical = floor.typical_of ?? null;
  const heightUnknown = floor.floor_height_source === 'derived_stack' ? BY_STACK : NOT_DEFINED;
  const counts = countWalls(floor.walls);
  const place = [
    floor.corps ? `корпус ${floor.corps}` : null,
    floor.section ? `секция ${floor.section}` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(', ');

  return (
    <section aria-label="Этаж" className="flex min-w-0 flex-col gap-[var(--s-4)] p-[var(--s-4)]">
      <div className="min-w-0">
        <h2 className="text-base font-medium [overflow-wrap:anywhere]">{floor.label}</h2>
        {place !== '' && <p className="text-xs text-muted">{place}</p>}
        {typical !== null && (
          <p className="text-xs text-muted [overflow-wrap:anywhere]">
            Этаж показан по типовому листу «{typical}»: геометрия листа на отметке этого этажа. В
            объёмы листа этаж не входит.
          </p>
        )}
      </div>
      <dl className="divide-y divide-border">
        <Row
          label="Отметка"
          value={floor.elevation_known ? formatElevation(floor.base_z_mm) : 'не определена'}
        />
        <Row
          label="Высота этажа"
          value={
            floor.floor_height_known
              ? meters(floor.floor_height_mm)
              : `${heightUnknown} (${meters(floor.floor_height_mm)})`
          }
        />
        <Row
          label="Толщина плиты"
          value={
            floor.slab_thickness_known
              ? meters(floor.slab_thickness_mm)
              : `${NOT_DEFINED} (${meters(floor.slab_thickness_mm)})`
          }
        />
        {note && <Row label="Совмещение" value={note.text} />}
        {floor.alignment === 'axes' && (
          <Row label="Качество совмещения" value={alignmentQuality(floor)} />
        )}
        {counts && (
          <>
            <Row label="Монолит, конструкций" value={String(counts.monolith)} />
            <Row label="Кладка, конструкций" value={String(counts.masonry)} />
            {counts.partition > 0 && (
              <Row label="Перегородки ГКЛ, конструкций" value={String(counts.partition)} />
            )}
            <Row label="Окна" value={windowsSummary(floor.windows)} />
          </>
        )}
      </dl>
      <div className="flex flex-wrap gap-[var(--s-3)]">
        {!detail && (
          <Button
            variant="primary"
            className="min-h-[44px]"
            disabled={view.params === null}
            onClick={onOpenDetail}
          >
            Этаж подробно
          </Button>
        )}
        <Button className="min-h-[44px]" onClick={() => onOpenSheet(floor)}>
          Открыть лист в CAD
        </Button>
      </div>
      {typical === null && <BuildingFloorTotals params={view.params} pending={view.pending} />}
    </section>
  );
};
