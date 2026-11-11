'use client';

import type { SheetPassportOut } from '@quantor/api-client';
import { useEffect, useRef, type FC } from 'react';

import { SheetPassportRow } from './SheetPassportRow';

/**
 * Таблица листов комплекта. На узком экране прокручивается только контейнер таблицы,
 * страница вбок не уезжает.
 */

interface ITableProps {
  readonly rows: readonly SheetPassportOut[];
  readonly selected: ReadonlySet<string>;
  readonly onToggle: (id: string) => void;
  readonly onToggleAll: () => void;
  readonly onEdit: (row: SheetPassportOut) => void;
}

const COLUMNS = [
  'Файл',
  'Стр.',
  'Раздел',
  'Тип',
  'Стадия',
  'Корпус',
  'Секция',
  'Этажи',
  'Отметка',
  'Шифр',
  '№ листа',
  'Заголовок',
  'Статус',
] as const;

export const SheetPassportTable: FC<ITableProps> = ({
  rows,
  selected,
  onToggle,
  onToggleAll,
  onEdit,
}) => {
  const all = rows.length > 0 && rows.every((row) => selected.has(row.id));
  const some = !all && rows.some((row) => selected.has(row.id));
  const head = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (head.current) {
      head.current.indeterminate = some;
    }
  }, [some]);

  return (
    <div className="overflow-x-auto overscroll-x-contain rounded-[var(--radius-md)] border border-border-strong bg-surface">
      <table className="w-full min-w-[72rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            <th scope="col" className="px-[var(--s-4)] py-[var(--s-3)]">
              <label className="grid h-[28px] w-[28px] cursor-pointer place-items-center max-md:h-[44px] max-md:w-[44px]">
                <input
                  ref={head}
                  type="checkbox"
                  checked={all}
                  aria-label="Выбрать все на странице"
                  onChange={onToggleAll}
                  className="h-[16px] w-[16px] accent-[var(--accent)]"
                />
              </label>
            </th>
            {COLUMNS.map((name) => (
              <th key={name} scope="col" className="px-[var(--s-4)] py-[var(--s-3)] font-semibold">
                {name}
              </th>
            ))}
            <th scope="col" className="px-[var(--s-4)] py-[var(--s-3)]">
              <span className="visually-hidden">Действия</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <SheetPassportRow
              key={row.id}
              row={row}
              selected={selected.has(row.id)}
              onToggle={onToggle}
              onEdit={onEdit}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
};
