import type { TenderQuantityDiffRead, TenderQuantityRowRead } from '@quantor/api-client';

/** Строки объёмов версии, склеенные с разницей по `code`. */

export type MergedStatus = TenderQuantityDiffRead['status'];

export interface IMergedQuantity {
  readonly code: string;
  readonly name: string;
  readonly unit: string;
  readonly qty: number | null;
  readonly qtyPrev: number | null;
  readonly delta: number | null;
  readonly status: MergedStatus;
  /** Строка версии (этажи, основание, примечание); у удалённых строк её нет. */
  readonly source: TenderQuantityRowRead | null;
}

export interface IQuantityGroup {
  readonly name: string;
  readonly rows: readonly IMergedQuantity[];
}

export const NO_GROUP = 'Без группы';

/**
 * Строки версии по группам. `compared = false` (первая версия) — без разницы: «Было» и Δ пусты,
 * статус `same`. Удалённые против прошлой версии строки попадают в группу «Удалено».
 */
export const mergeQuantities = (
  quantities: readonly TenderQuantityRowRead[],
  diff: readonly TenderQuantityDiffRead[],
  compared: boolean,
  onlyChanges: boolean,
): readonly IQuantityGroup[] => {
  const diffByCode = new Map(diff.map((entry) => [entry.code, entry]));
  const merged: { group: string; row: IMergedQuantity }[] = quantities.map((source) => {
    const entry = compared ? diffByCode.get(source.code) : undefined;
    return {
      group: source.group ?? NO_GROUP,
      row: {
        code: source.code,
        name: source.name,
        unit: source.unit,
        qty: source.qty,
        qtyPrev: entry?.qty_prev ?? null,
        delta: entry ? entry.delta : null,
        status: entry?.status ?? 'same',
        source,
      },
    };
  });

  if (compared) {
    const present = new Set(quantities.map((row) => row.code));
    for (const entry of diff) {
      if (entry.status !== 'removed' || present.has(entry.code)) continue;
      merged.push({
        group: 'Удалено относительно прошлой версии',
        row: {
          code: entry.code,
          name: entry.name,
          unit: entry.unit,
          qty: null,
          qtyPrev: entry.qty_prev,
          delta: entry.delta,
          status: 'removed',
          source: null,
        },
      });
    }
  }

  const groups = new Map<string, IMergedQuantity[]>();
  for (const { group, row } of merged) {
    if (onlyChanges && row.status === 'same') continue;
    const rows = groups.get(group) ?? [];
    rows.push(row);
    groups.set(group, rows);
  }
  return [...groups.entries()].map(([name, rows]) => ({ name, rows }));
};
