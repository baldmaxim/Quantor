'use client';

import { Fragment, useState, type FC } from 'react';

import type { CadFinishTemplateRead, CadFinishZoneRead } from '@quantor/api-client';

import { cx } from '@/components/ui';
import {
  DASH,
  HEIGHT_SOURCE_LABELS,
  TEMPLATE_SOURCE_LABELS,
  finishZoneTitle,
  formatFinishArea,
  formatFinishMm,
  formatMaterialQty,
  templateNameOf,
} from '@/lib/cad/finish-sheet';
import { SURFACE_LABELS, basesText, roomTypeLabel } from '@/lib/cad/room-types';

import { CadFinishWallsBreakdown } from './CadFinishWallsBreakdown';
import { NUM, TD, TH } from './finish-table-styles';

interface ICadFinishSheetTableProps {
  zones: readonly CadFinishZoneRead[];
  templates: readonly CadFinishTemplateRead[];
  activeId: string | null;
  /** Выделить зону на листе, как выбор в списке зон. */
  onActivate: (id: string | null) => void;
}

const ACTION =
  'min-h-[44px] min-w-[44px] text-left text-xs text-accent underline-offset-2 hover:underline';

const LayersTable: FC<{ zone: CadFinishZoneRead }> = ({ zone }) => (
  <table
    className="w-full border-collapse text-xs"
    aria-label={`Слои зоны: ${finishZoneTitle(zone)}`}
  >
    <thead>
      <tr>
        <th className={TH}>Поверхность</th>
        <th className={TH}>Работа</th>
        <th className={TH}>Материал</th>
        <th className={cx(TH, 'text-right')}>Раз</th>
        <th className={cx(TH, 'text-right')}>Толщина, мм</th>
        <th className={cx(TH, 'text-right')}>Площадь, м²</th>
        <th className={cx(TH, 'text-right')}>Материал, кол-во</th>
      </tr>
    </thead>
    <tbody>
      {zone.layers.map((layer, index) => (
        <tr key={`${layer.surface}:${index}`} className="border-t border-border">
          <td className={TD}>{SURFACE_LABELS[layer.surface]}</td>
          <td className={TD}>
            {layer.work}
            {basesText(layer.bases) !== '' && (
              <span className="block text-micro text-muted">{basesText(layer.bases)}</span>
            )}
          </td>
          <td className={TD}>{layer.material ?? DASH}</td>
          <td className={NUM}>{layer.coats}</td>
          <td className={NUM}>{layer.thickness_mm === null ? DASH : layer.thickness_mm}</td>
          <td className={NUM}>{formatFinishArea(layer.area_m2)}</td>
          <td className={NUM}>{formatMaterialQty(layer.material_qty, layer.material_unit)}</td>
        </tr>
      ))}
    </tbody>
  </table>
);

/**
 * Таблица зон ведомости: тип, шаблон и источник назначения, площади пола, стен и потолка, высота
 * стен и её источник. Раскрытие строки - слои зоны. Не определено - «—», не 0. Узкая ширина -
 * горизонтальный скролл внутри контейнера.
 */
export const CadFinishSheetTable: FC<ICadFinishSheetTableProps> = ({
  zones,
  templates,
  activeId,
  onActivate,
}) => {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (id: string) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpen(next);
  };

  if (zones.length === 0) {
    return <p className="text-xs text-muted">На листе нет зон с отделкой.</p>;
  }

  return (
    <div className="scroll-area min-w-0 overflow-x-auto overscroll-x-contain">
      <table
        className="w-full min-w-[640px] border-collapse text-xs"
        aria-label="Зоны ведомости отделки"
      >
        <thead>
          <tr>
            <th className={TH}>Зона</th>
            <th className={TH}>Тип</th>
            <th className={TH}>Шаблон</th>
            <th className={cx(TH, 'text-right')}>Пол, м²</th>
            <th className={cx(TH, 'text-right')}>Стены, м²</th>
            <th className={cx(TH, 'text-right')}>Потолок, м²</th>
            <th className={cx(TH, 'text-right')}>Высота, мм</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((zone) => {
            const expanded = open.has(zone.zone_id);
            const title = finishZoneTitle(zone);
            return (
              <Fragment key={zone.zone_id}>
                <tr
                  className={cx(
                    'border-t border-border',
                    zone.zone_id === activeId && 'bg-surface-muted',
                  )}
                >
                  <td className={TD}>
                    <button
                      type="button"
                      aria-expanded={expanded}
                      aria-label={`Слои зоны: ${title}`}
                      onClick={() => toggle(zone.zone_id)}
                      className={cx(ACTION, 'text-text')}
                    >
                      <span aria-hidden="true">{expanded ? '▾ ' : '▸ '}</span>
                      {title}
                    </button>
                    <button
                      type="button"
                      aria-pressed={zone.zone_id === activeId}
                      aria-label={`Показать на листе: ${title}`}
                      onClick={() => onActivate(zone.zone_id === activeId ? null : zone.zone_id)}
                      className={ACTION}
                    >
                      На листе
                    </button>
                  </td>
                  <td className={TD}>{roomTypeLabel(zone.room_type)}</td>
                  <td className={TD}>
                    {templateNameOf(templates, zone.template_id)}
                    {zone.template_source !== null && (
                      <span className="text-muted">
                        {' '}
                        ({TEMPLATE_SOURCE_LABELS[zone.template_source]})
                      </span>
                    )}
                  </td>
                  <td className={NUM}>{formatFinishArea(zone.floor_area_m2)}</td>
                  <td className={NUM}>
                    {formatFinishArea(zone.wall_area_m2)}
                    {!zone.walls_breakdown.linked && (
                      <span className="block text-micro text-muted">не привязано</span>
                    )}
                  </td>
                  <td className={NUM}>{formatFinishArea(zone.ceiling_area_m2)}</td>
                  <td className={NUM}>
                    {formatFinishMm(zone.wall_height_mm)}
                    {zone.wall_height_source !== null && (
                      <span className="block text-micro text-muted">
                        {HEIGHT_SOURCE_LABELS[zone.wall_height_source]}
                      </span>
                    )}
                  </td>
                </tr>
                {expanded && (
                  <tr className="bg-surface-muted">
                    <td colSpan={7} className="p-[var(--s-2)]">
                      <div className="flex flex-col gap-[var(--s-3)]">
                        {zone.layers.length === 0 ? (
                          <p className="text-xs text-muted">
                            Слоёв нет: шаблон не назначен или в нём нет слоёв.
                          </p>
                        ) : (
                          <LayersTable zone={zone} />
                        )}
                        <CadFinishWallsBreakdown zone={zone} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
