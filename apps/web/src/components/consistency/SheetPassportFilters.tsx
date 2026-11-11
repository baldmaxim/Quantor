'use client';

import type { SheetPassportStatus } from '@quantor/api-client';
import type { FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';
import { STATUS_LABELS } from '@/lib/consistency/sheet-passports';

/** Фильтры «Листов комплекта»: статус и раздел — на сервере, поиск по шифру и заголовку — на клиенте. */

interface IFiltersProps {
  readonly status: SheetPassportStatus | null;
  readonly sectionMark: string | null;
  readonly marks: readonly string[];
  readonly search: string;
  readonly onStatus: (status: SheetPassportStatus | null) => void;
  readonly onSectionMark: (mark: string | null) => void;
  readonly onSearch: (value: string) => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const SELECT =
  'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

const STATUSES = Object.keys(STATUS_LABELS) as SheetPassportStatus[];

export const SheetPassportFilters: FC<IFiltersProps> = ({
  status,
  sectionMark,
  marks,
  search,
  onStatus,
  onSectionMark,
  onSearch,
}) => (
  <div className="grid gap-[var(--s-4)] sm:grid-cols-2 lg:grid-cols-[12rem_12rem_minmax(0,1fr)]">
    <label className={LABEL}>
      Статус
      <select
        className={SELECT}
        value={status ?? ''}
        onChange={(event) => onStatus((event.target.value || null) as SheetPassportStatus | null)}
      >
        <option value="">Все</option>
        {STATUSES.map((value) => (
          <option key={value} value={value}>
            {STATUS_LABELS[value]}
          </option>
        ))}
      </select>
    </label>
    <label className={LABEL}>
      Раздел
      <select
        className={SELECT}
        value={sectionMark ?? ''}
        onChange={(event) => onSectionMark(event.target.value || null)}
      >
        <option value="">Все</option>
        {marks.map((mark) => (
          <option key={mark} value={mark}>
            {mark}
          </option>
        ))}
      </select>
    </label>
    <div className={`${LABEL} sm:col-span-2 lg:col-span-1`}>
      <span aria-hidden="true">Поиск по шифру и заголовку</span>
      <ClearableInput
        type="search"
        label="Поиск по шифру и заголовку"
        value={search}
        placeholder="Шифр или заголовок"
        wrapperClassName="w-full"
        onChange={(event) => onSearch(event.target.value)}
        onClear={() => onSearch('')}
      />
    </div>
  </div>
);
