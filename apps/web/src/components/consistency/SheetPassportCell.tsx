import type { SheetPassportOut } from '@quantor/api-client';
import type { FC } from 'react';

import { cx } from '@/components/ui';
import { EMPTY_CELL, fieldSource } from '@/lib/consistency/sheet-passports';

/**
 * Ячейка паспорта: значение («—» для пустого) и маленькая метка источника из `evidence`.
 * Цитата, по которой значение найдено, — во всплывающей подсказке метки.
 */

interface ICellProps {
  readonly row: SheetPassportOut;
  /** Поле, чьё доказательство показывает метка. */
  readonly field: string;
  readonly text: string;
  readonly className?: string;
}

export const SheetPassportCell: FC<ICellProps> = ({ row, field, text, className }) => {
  const source = text === EMPTY_CELL ? null : fieldSource(row, field);

  return (
    <td className={cx('px-[var(--s-4)] py-[var(--s-3)] align-top text-sm', className)}>
      <span className={cx('[overflow-wrap:anywhere]', text === EMPTY_CELL && 'text-muted')}>
        {text}
      </span>
      {source && (
        <span
          title={source.snippet || undefined}
          className={cx(
            'mt-[2px] block text-micro whitespace-nowrap',
            source.manual ? 'text-accent' : 'text-muted',
          )}
        >
          {source.label}
        </span>
      )}
    </td>
  );
};
