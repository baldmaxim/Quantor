import type { VorFillItemRead } from '@quantor/api-client';
import type { FC } from 'react';

import { vorItemTitle } from '@/lib/cad/vor';
import { differenceText, quantityText, STATUS_CLASSES, STATUS_LABELS } from '@/lib/vor-fill/format';

/**
 * Позиции ВОР, связанные с объектами Quantor: количество Заказчика, количество Quantor, разница и
 * статус. Количество Заказчика только показано; Quantor - сумма связанных объектов от движка.
 */

interface ITableProps {
  readonly items: readonly VorFillItemRead[];
}

const CELL = 'px-[var(--s-3)] py-[var(--s-2)] align-top';

export const VorFillTable: FC<ITableProps> = ({ items }) => {
  if (items.length === 0) {
    return (
      <p className="text-xs text-muted">
        Связанных позиций пока нет: свяжите объекты Quantor со строками ВОР ниже.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto overscroll-contain rounded-[var(--r-2)] border border-border">
      <table className="w-full min-w-[720px] border-collapse text-left text-xs">
        <thead className="bg-surface text-muted">
          <tr>
            <th className={CELL}>Позиция ВОР</th>
            <th className={`${CELL} text-right`}>Заказчик</th>
            <th className={`${CELL} text-right`}>Quantor</th>
            <th className={`${CELL} text-right`}>Разница</th>
            <th className={CELL}>Статус</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.item.id} className="border-t border-border">
              <td className={`${CELL} min-w-0 [overflow-wrap:anywhere]`}>
                <span className="text-text">{vorItemTitle(row.item)}</span>
                {row.sources.length > 0 && (
                  <span className="block text-muted">{row.sources.slice(0, 3).join('; ')}</span>
                )}
                {row.missing_group_keys.length > 0 && (
                  <span className="block text-warning">
                    Связанных объектов нет в проекте: {row.missing_group_keys.length}
                  </span>
                )}
              </td>
              <td className={`${CELL} text-right tabular-nums`}>
                {row.item.quantity === null
                  ? '—'
                  : `${quantityText(row.customer_quantity, null)} ${row.item.unit ?? ''}`.trim()}
              </td>
              <td className={`${CELL} text-right tabular-nums`}>
                {quantityText(row.quantor_quantity, row.unit)}
              </td>
              <td className={`${CELL} text-right tabular-nums`}>{differenceText(row)}</td>
              <td className={`${CELL} font-semibold ${STATUS_CLASSES[row.status]}`}>
                {STATUS_LABELS[row.status]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
