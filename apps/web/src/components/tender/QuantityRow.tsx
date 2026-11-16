'use client';

import { useState, type FC } from 'react';

import { cx } from '@/components/ui';
import { BASIS_LABELS, DIFF_STATUS_LABELS, formatDelta, formatQty } from '@/lib/tender/present';
import type { IMergedQuantity } from '@/lib/tender/quantities';

/**
 * Строка объёмов. Раскрытие по этажам — кнопка в ячейке наименования: этажи, основание и примечание
 * лежат в строке версии (`per_floor`, `basis`, `note`). На телефоне ячейки подписаны через `data-label`.
 */

interface IRowProps {
  readonly row: IMergedQuantity;
  readonly compared: boolean;
  readonly className: string;
}

const TD =
  'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm max-md:flex max-md:justify-between max-md:gap-[var(--s-4)] max-md:px-0 max-md:py-[var(--s-1)] max-md:before:text-xs max-md:before:text-muted max-md:before:content-[attr(data-label)]';

export const QuantityRow: FC<IRowProps> = ({ row, compared, className }) => {
  const [open, setOpen] = useState(false);
  const source = row.source;
  const expandable = source !== null && (source.per_floor.length > 0 || source.note !== null);
  const removed = row.status === 'removed';

  return (
    <>
      <tr
        className={cx(
          'border-b border-border max-md:flex max-md:flex-col max-md:px-[var(--s-5)] max-md:py-[var(--s-4)]',
          className,
        )}
      >
        <td data-label="Код" className={cx(TD, 'mono text-xs')}>
          {row.code}
        </td>
        <td data-label="Наименование" className={cx(TD, '[overflow-wrap:anywhere]')}>
          {expandable ? (
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
              className="press min-h-[44px] text-left hover:underline md:min-h-0"
            >
              {open ? '▾ ' : '▸ '}
              {row.name}
            </button>
          ) : (
            <span className={removed ? 'line-through' : undefined}>{row.name}</span>
          )}
          {compared && row.status !== 'same' && (
            <span className="ml-[var(--s-3)] text-xs text-muted">
              {DIFF_STATUS_LABELS[row.status]}
            </span>
          )}
        </td>
        <td data-label="Ед." className={TD}>
          {row.unit}
        </td>
        <td data-label="Кол-во" className={cx(TD, 'tabular justify-end text-right font-medium')}>
          {formatQty(row.qty)}
        </td>
        <td data-label="Было" className={cx(TD, 'tabular justify-end text-right text-muted')}>
          {compared ? formatQty(row.qtyPrev) : '—'}
        </td>
        <td data-label="Δ" className={cx(TD, 'tabular justify-end text-right')}>
          {compared && row.delta !== null ? formatDelta(row.delta) : '—'}
        </td>
      </tr>
      {open && source && (
        <tr className="border-b border-border bg-surface-muted max-md:block">
          <td colSpan={6} className="px-[var(--s-6)] py-[var(--s-4)] text-sm max-md:block">
            <p className="m-0 mb-[var(--s-3)] text-xs text-muted">
              Основание: {BASIS_LABELS[source.basis] ?? source.basis}
              {source.note ? ` · ${source.note}` : ''}
            </p>
            {source.per_floor.length > 0 && (
              <dl className="m-0 grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-[var(--s-3)]">
                {source.per_floor.map((floor) => (
                  <div key={floor.floor} className="flex justify-between gap-[var(--s-3)]">
                    <dt className="text-muted">Этаж {floor.floor}</dt>
                    <dd className="tabular m-0">{formatQty(floor.qty)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </td>
        </tr>
      )}
    </>
  );
};
