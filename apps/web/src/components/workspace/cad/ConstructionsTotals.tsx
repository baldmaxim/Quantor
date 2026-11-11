'use client';

import type { CadConstructionsRead } from '@quantor/api-client';
import type { FC } from 'react';

import {
  KIND_LABELS,
  isFramePartition,
  isMonolith,
  materialLabel,
  materialSourceLabel,
  type MaterialSource,
} from '@/lib/cad/construction-labels';
import {
  STATUS_GROUP_PREFIX,
  groupIds,
  groupKeyOf,
  statusIds,
  sumGroups,
  type IGroupSum,
} from '@/lib/cad/constructions';
import { formatNumber } from '@/lib/cad/view-format';

interface IConstructionsTotalsProps {
  data: CadConstructionsRead;
  activeGroup: string | null;
  onSelectGroup: (key: string, ids: readonly string[]) => void;
}

const TH = 'px-[var(--s-2)] py-[var(--s-2)] text-left text-micro font-medium text-muted';
const TD = 'px-[var(--s-2)] py-[var(--s-2)] align-top tabular';
const NUM = `${TD} text-right`;

/** Объём каркасной перегородки не определён: ГКЛ меряется площадью. */
const NO_VOLUME = '—';

const SumRow: FC<{ label: string; sum: IGroupSum; withVolume?: boolean }> = ({
  label,
  sum,
  withVolume = true,
}) => (
  <tr className="border-t border-border-strong font-medium">
    <td className={TD} colSpan={3}>
      {label}
    </td>
    <td className={NUM}>{sum.count}</td>
    <td className={NUM}>{formatNumber(sum.length_m, 2)}</td>
    <td className={NUM}>{formatNumber(sum.wall_area_m2, 2)}</td>
    <td className={NUM}>{withVolume ? formatNumber(sum.volume_m3, 3) : NO_VOLUME}</td>
  </tr>
);

/** Подпись источника материала группы: «(документ)», «(вручную)» или оба, если в группе разные. */
const sourceSuffix = (sources: ReadonlySet<MaterialSource>): string => {
  if (sources.size === 0) return '';
  if (sources.size === 1 && sources.has('manual')) return '';
  return ` (${[...sources].map((source) => materialSourceLabel(source)).join(' и ')})`;
};

/**
 * Свод по группам «вид × толщина × материал» и строки того, что в итоги не вошло. Строка кликабельна:
 * её конструкции подсвечиваются на холсте. В итоги идут только посчитанные конструкции.
 */
export const ConstructionsTotals: FC<IConstructionsTotalsProps> = ({
  data,
  activeGroup,
  onSelectGroup,
}) => {
  const { totals, summary, constructions } = data;
  const masonry = sumGroups(
    totals,
    (group) => !isMonolith(group.kind) && !isFramePartition(group.kind),
  );
  const monolith = sumGroups(totals, (group) => isMonolith(group.kind));
  const frame = sumGroups(totals, (group) => isFramePartition(group.kind));

  const materialCheckIds = constructions
    .filter((item) => item.computed.warnings.includes('material_check'))
    .map((item) => item.id);

  const specials = [
    {
      key: `${STATUS_GROUP_PREFIX}thickness_check`,
      label: 'Толщина не определена',
      count: summary.thickness_check_count,
      ids: statusIds(constructions, 'thickness_check'),
    },
    {
      key: `${STATUS_GROUP_PREFIX}height_missing`,
      label: 'Нет высоты',
      count: summary.height_missing_count,
      ids: statusIds(constructions, 'height_missing'),
    },
    {
      key: `${STATUS_GROUP_PREFIX}material_check`,
      label: 'Проверить материал',
      count: materialCheckIds.length,
      ids: materialCheckIds,
    },
    { key: 'gaps', label: 'Проёмы без данных', count: summary.unaccounted_gap_openings, ids: [] },
    { key: 'doors', label: 'Двери без стены', count: summary.door_openings_without_host, ids: [] },
  ];

  return (
    <section aria-label="Свод конструкций" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Свод</h4>
      {totals.length === 0 ? (
        <p className="text-xs text-muted">Посчитанных конструкций нет: итоги по группам не набраны.</p>
      ) : (
        <div className="scroll-area overflow-x-auto overscroll-x-contain">
          <table className="w-full min-w-[420px] border-collapse text-xs">
            <thead>
              <tr>
                <th className={TH}>Вид</th>
                <th className={TH}>Толщина, мм</th>
                <th className={TH}>Материал</th>
                <th className={`${TH} text-right`}>Шт.</th>
                <th className={`${TH} text-right`}>Длина, м</th>
                <th className={`${TH} text-right`}>Стена, м²</th>
                <th className={`${TH} text-right`}>Объём, м³</th>
              </tr>
            </thead>
            <tbody>
              {totals.map((group) => {
                const key = groupKeyOf(group);
                const active = activeGroup === key;
                const ids = groupIds(constructions, group);
                const sources = new Set<MaterialSource>();
                for (const item of constructions) {
                  if (ids.includes(item.id) && item.material.source !== null) {
                    sources.add(item.material.source);
                  }
                }
                return (
                  <tr
                    key={key}
                    onClick={() => onSelectGroup(key, ids)}
                    className={`cursor-pointer border-t border-border hover:bg-surface-muted ${
                      active ? 'bg-accent-soft' : ''
                    }`}
                  >
                    <td className={TD}>
                      <button
                        type="button"
                        aria-pressed={active}
                        className="min-h-[44px] text-left md:min-h-0"
                      >
                        {KIND_LABELS[group.kind]}
                      </button>
                    </td>
                    <td className={TD}>{group.thickness_mm}</td>
                    <td className={TD}>
                      {materialLabel(group.material)}
                      {group.material !== null && sourceSuffix(sources)}
                    </td>
                    <td className={NUM}>{group.count}</td>
                    <td className={NUM}>{formatNumber(group.length_m, 2)}</td>
                    <td className={NUM}>{formatNumber(group.wall_area_m2, 2)}</td>
                    <td className={NUM}>
                      {group.volume_m3 === null ? NO_VOLUME : formatNumber(group.volume_m3, 3)}
                    </td>
                  </tr>
                );
              })}
              {masonry && <SumRow label="Итого кладка" sum={masonry} />}
              {monolith && <SumRow label="Итого монолит" sum={monolith} />}
              {frame && <SumRow label="Итого ГКЛ (по площади)" sum={frame} withVolume={false} />}
            </tbody>
          </table>
        </div>
      )}

      <ul className="m-0 flex list-none flex-col p-0 text-xs">
        {specials.map((row) => (
          <li key={row.key} className="border-t border-border first:border-t-0">
            {row.ids.length > 0 ? (
              <button
                type="button"
                aria-pressed={activeGroup === row.key}
                onClick={() => onSelectGroup(row.key, row.ids)}
                className={`min-h-[44px] w-full text-left hover:bg-surface-muted md:min-h-[32px] ${
                  activeGroup === row.key ? 'bg-accent-soft' : ''
                }`}
              >
                {row.label} — {row.count}
              </button>
            ) : (
              <span className={`block py-[var(--s-3)] ${row.count === 0 ? 'text-muted' : ''}`}>
                {row.label} — {row.count}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};
