'use client';

import type { TenderCalcVersionRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { EmptyState } from '@/components/ui';
import { DIFF_ROW_CLASSES } from '@/lib/tender/present';
import { mergeQuantities } from '@/lib/tender/quantities';

import { QuantityRow } from './QuantityRow';

/**
 * Объёмы версии: группы, колонки «Код, Наименование, Ед., Кол-во, Было, Δ». Разница — с прошлой
 * действующей версией (`diff`); у первой версии сравнивать не с чем, подсветки нет. Фильтр «только
 * изменения» прячет строки без разницы. На телефоне строка — карточка.
 */

interface ITableProps {
  readonly version: TenderCalcVersionRead;
}

const TH = 'px-[var(--s-4)] py-[var(--s-3)] font-semibold';

export const QuantitiesTable: FC<ITableProps> = ({ version }) => {
  const [onlyChanges, setOnlyChanges] = useState(false);
  const compared = version.prev_version_id !== null;
  const groups = mergeQuantities(version.quantities, version.diff, compared, onlyChanges);

  if (version.quantities.length === 0 && version.diff.length === 0) {
    return <EmptyState compact title="Объёмов в версии нет" />;
  }

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      {compared && (
        <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-[var(--s-4)] text-sm md:min-h-[var(--h-ctl)]">
          <input
            type="checkbox"
            checked={onlyChanges}
            onChange={(event) => setOnlyChanges(event.target.checked)}
            className="h-[16px] w-[16px] accent-[var(--accent)]"
          />
          Только изменения
        </label>
      )}
      {groups.length === 0 && <EmptyState compact title="Изменений нет" />}
      {groups.length > 0 && (
        <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <table aria-label="Объёмы" className="w-full border-collapse text-left max-md:block">
            <thead className="max-md:sr-only">
              <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                <th scope="col" className={`${TH} md:w-[14%]`}>
                  Код
                </th>
                <th scope="col" className={TH}>
                  Наименование
                </th>
                <th scope="col" className={`${TH} md:w-[6%]`}>
                  Ед.
                </th>
                <th scope="col" className={`${TH} text-right md:w-[12%]`}>
                  Кол-во
                </th>
                <th scope="col" className={`${TH} text-right md:w-[12%]`}>
                  Было
                </th>
                <th scope="col" className={`${TH} text-right md:w-[10%]`}>
                  Δ
                </th>
              </tr>
            </thead>
            {groups.map((group) => (
              <tbody key={group.name} className="max-md:block">
                <tr className="max-md:block">
                  <th
                    scope="colgroup"
                    colSpan={6}
                    className="bg-surface-sunken px-[var(--s-4)] py-[var(--s-3)] text-left text-xs font-semibold"
                  >
                    {group.name}
                  </th>
                </tr>
                {group.rows.map((row) => (
                  <QuantityRow
                    key={row.code}
                    row={row}
                    compared={compared}
                    className={compared ? DIFF_ROW_CLASSES[row.status] : ''}
                  />
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
};
