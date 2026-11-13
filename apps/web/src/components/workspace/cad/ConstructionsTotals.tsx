'use client';

import type { CadConstructionsRead } from '@quantor/api-client';
import type { FC } from 'react';

import {
  KIND_LABELS,
  isFloorSlab,
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
  type ConstructionGroup,
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

/**
 * Перемычка - часть стены: в своде отдельной строки нет, её объём входит в строку стен того же вида
 * и толщины (признак «в т.ч. перемычки» остаётся подписью). Данные API и ВОР по-прежнему делят их.
 */
const LINTEL_NOTE = 'в т.ч. перемычки';

const roundVolume = (value: number): number => Math.round(value * 10_000) / 10_000;

/** Строка свода: группа стен и объём перемычек, вошедший в неё (`null` - перемычек нет). */
interface IWallRow {
  readonly group: ConstructionGroup;
  readonly lintelVolume: number | null;
  /** Строка из одних перемычек: стен такого вида и толщины нет. */
  readonly lintelOnly: boolean;
}

/** Объём строки: стены плюс перемычки; обоих нет - `null`. */
const rowVolume = (row: IWallRow): number | null =>
  row.lintelOnly
    ? row.lintelVolume
    : row.group.volume_m3 === null && row.lintelVolume === null
      ? null
      : roundVolume((row.group.volume_m3 ?? 0) + (row.lintelVolume ?? 0));

/**
 * Строки свода: группы перемычек прибавляются к группе стен того же вида и толщины (материал
 * предпочтительно тот же); без такой группы - строка из одних перемычек на месте группы перемычек.
 */
const wallRowsOf = (groups: readonly ConstructionGroup[]): IWallRow[] => {
  const walls = groups.filter((group) => group.element !== 'lintel');
  const added = new Map<ConstructionGroup, number>();
  const rows: IWallRow[] = [];
  const hostOf = (lintel: ConstructionGroup): ConstructionGroup | undefined => {
    const sameSize = walls.filter(
      (group) => group.kind === lintel.kind && group.thickness_mm === lintel.thickness_mm,
    );
    return sameSize.find((group) => group.material === lintel.material) ?? sameSize[0];
  };
  for (const lintel of groups) {
    const host = lintel.element === 'lintel' ? hostOf(lintel) : undefined;
    if (host !== undefined && lintel.volume_m3 !== null) {
      added.set(host, (added.get(host) ?? 0) + lintel.volume_m3);
    }
  }
  for (const group of groups) {
    if (group.element !== 'lintel') {
      rows.push({ group, lintelVolume: added.has(group) ? (added.get(group) ?? null) : null, lintelOnly: false });
    } else if (hostOf(group) === undefined) {
      rows.push({ group, lintelVolume: group.volume_m3, lintelOnly: true });
    }
  }
  return rows;
};

/** Итог по группам: шт., длина, площадь - только стен, объём - со стенами и перемычками. */
const sumWithLintels = (
  groups: readonly ConstructionGroup[],
  pick: (group: ConstructionGroup) => boolean,
): IGroupSum | null => {
  const walls = sumGroups(groups, (group) => group.element !== 'lintel' && pick(group));
  const lintels = groups.filter((group) => group.element === 'lintel' && pick(group));
  if (lintels.length === 0) return walls;
  const volume = lintels.reduce((total, group) => total + (group.volume_m3 ?? 0), 0);
  const base = walls ?? { count: 0, length_m: 0, wall_area_m2: 0, volume_m3: 0 };
  return { ...base, volume_m3: roundVolume(base.volume_m3 + volume) };
};

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
  const slabGroups = totals.filter((group) => isFloorSlab(group.kind));
  const wallGroups = totals.filter((group) => !isFloorSlab(group.kind));
  const wallRows = wallRowsOf(wallGroups);
  const masonry = sumWithLintels(
    wallGroups,
    (group) => !isMonolith(group.kind) && !isFramePartition(group.kind),
  );
  const monolith = sumWithLintels(wallGroups, (group) => isMonolith(group.kind));
  const frame = sumWithLintels(wallGroups, (group) => isFramePartition(group.kind));

  /** Подпись источников материала для строки группы: берётся по конструкциям группы. */
  const sourcesOf = (ids: readonly string[]): Set<MaterialSource> => {
    const sources = new Set<MaterialSource>();
    for (const item of constructions) {
      if (ids.includes(item.id) && item.material.source !== null) sources.add(item.material.source);
    }
    return sources;
  };

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
    {
      key: 'lintels',
      label: 'Перемычки без объёма',
      count: summary.lintels_without_volume ?? 0,
      ids: [],
    },
  ];

  return (
    <section aria-label="Свод конструкций" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Свод</h4>
      {totals.length === 0 ? (
        <p className="text-xs text-muted">
          Посчитанных конструкций нет: итоги по группам не набраны.
        </p>
      ) : (
        wallGroups.length > 0 && (
          <div className="scroll-area overflow-x-auto overflow-y-hidden overscroll-x-contain overscroll-y-auto">
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
                {wallRows.map((row) => {
                  const { group } = row;
                  const volume = rowVolume(row);
                  const volumeCell = (
                    <td className={NUM}>
                      {volume === null ? NO_VOLUME : formatNumber(volume, 3)}
                      {row.lintelVolume !== null && (
                        <span className="block text-micro font-normal text-muted">
                          {LINTEL_NOTE} {formatNumber(row.lintelVolume, 3)} м³
                        </span>
                      )}
                    </td>
                  );
                  if (row.lintelOnly) {
                    // Стен такого вида и толщины нет: строка из одних перемычек, на холсте подсвечивать нечего.
                    return (
                      <tr key={`${groupKeyOf(group)}|lintel`} className="border-t border-border">
                        <td className={TD}>{KIND_LABELS[group.kind]}</td>
                        <td className={TD}>{group.thickness_mm}</td>
                        <td className={TD}>{materialLabel(group.material)}</td>
                        <td className={NUM}>{NO_VOLUME}</td>
                        <td className={NUM}>{NO_VOLUME}</td>
                        <td className={NUM}>{NO_VOLUME}</td>
                        {volumeCell}
                      </tr>
                    );
                  }
                  const key = groupKeyOf(group);
                  const active = activeGroup === key;
                  const ids = groupIds(constructions, group);
                  const sources = sourcesOf(ids);
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
                      {volumeCell}
                    </tr>
                  );
                })}
                {masonry && <SumRow label="Итого кладка" sum={masonry} />}
                {monolith && <SumRow label="Итого монолит" sum={monolith} />}
                {frame && <SumRow label="Итого ГКЛ (по площади)" sum={frame} withVolume={false} />}
              </tbody>
            </table>
          </div>
        )
      )}

      {slabGroups.length > 0 && (
        <div
          role="group"
          aria-label="Плита перекрытия"
          className="flex min-w-0 flex-col gap-[var(--s-2)]"
        >
          <h5 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            {KIND_LABELS.floor_slab}
          </h5>
          <div className="scroll-area overflow-x-auto overflow-y-hidden overscroll-x-contain overscroll-y-auto">
            <table className="w-full min-w-[320px] border-collapse text-xs">
              <thead>
                <tr>
                  <th className={TH}>Толщина, мм</th>
                  <th className={TH}>Материал</th>
                  <th className={`${TH} text-right`}>Площадь, м²</th>
                  <th className={`${TH} text-right`}>Объём, м³</th>
                </tr>
              </thead>
              <tbody>
                {slabGroups.map((group) => {
                  const key = groupKeyOf(group);
                  const active = activeGroup === key;
                  const ids = groupIds(constructions, group);
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
                          {group.thickness_mm}
                        </button>
                      </td>
                      <td className={TD}>
                        {materialLabel(group.material)}
                        {group.material !== null && sourceSuffix(sourcesOf(ids))}
                      </td>
                      <td className={NUM}>
                        {group.area_m2 === null || group.area_m2 === undefined
                          ? NO_VOLUME
                          : formatNumber(group.area_m2, 2)}
                      </td>
                      <td className={NUM}>
                        {group.volume_m3 === null ? NO_VOLUME : formatNumber(group.volume_m3, 3)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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
