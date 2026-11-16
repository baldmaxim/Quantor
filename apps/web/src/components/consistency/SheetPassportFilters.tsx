'use client';

import type { SheetPassportStatus } from '@quantor/api-client';
import type { FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';
import type { IPassportScope } from '@/lib/consistency/sheet-passport-queries';
import { STATUS_LABELS, sheetKindLabel } from '@/lib/consistency/sheet-passports';

/**
 * Фильтры «Листов комплекта»: статус, раздел, тип, корпус и секция — на сервере, поиск по шифру и
 * заголовку — на клиенте. Значения списков — все значения проекта, а не загруженной страницы.
 */

export interface IPassportFacets {
  readonly marks: readonly string[];
  readonly kinds: readonly string[];
  readonly buildings: readonly string[];
  readonly sections: readonly string[];
}

interface IFiltersProps {
  readonly status: SheetPassportStatus | null;
  readonly scope: IPassportScope;
  readonly facets: IPassportFacets;
  readonly search: string;
  readonly onStatus: (status: SheetPassportStatus | null) => void;
  readonly onScope: (scope: Partial<IPassportScope>) => void;
  readonly onSearch: (value: string) => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const SELECT =
  'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

const STATUSES = Object.keys(STATUS_LABELS) as SheetPassportStatus[];

/** Значение пункта «Не указан» в списке; на сервер уходит пустой строкой. */
const NOT_SET_OPTION = '__not_set__';

const toOption = (value: string | null): string =>
  value === null ? '' : value === '' ? NOT_SET_OPTION : value;

const fromOption = (option: string): string | null =>
  option === '' ? null : option === NOT_SET_OPTION ? '' : option;

const ScopeSelect: FC<{
  readonly label: string;
  readonly value: string | null;
  readonly values: readonly string[];
  readonly text?: (value: string) => string;
  readonly onChange: (value: string | null) => void;
}> = ({ label, value, values, text, onChange }) => {
  // Выбранное значение остаётся в списке, даже если в проекте его уже нет.
  const options = value && !values.includes(value) ? [value, ...values] : values;
  return (
    <label className={LABEL}>
      {label}
      <select
        className={SELECT}
        value={toOption(value)}
        onChange={(event) => onChange(fromOption(event.target.value))}
      >
        <option value="">Все</option>
        <option value={NOT_SET_OPTION}>Не указан</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {text ? text(option) : option}
          </option>
        ))}
      </select>
    </label>
  );
};

export const SheetPassportFilters: FC<IFiltersProps> = ({
  status,
  scope,
  facets,
  search,
  onStatus,
  onScope,
  onSearch,
}) => (
  <div className="grid gap-[var(--s-4)] sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-[repeat(5,minmax(0,10rem))_minmax(0,1fr)]">
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
    <ScopeSelect
      label="Раздел"
      value={scope.sectionMark}
      values={facets.marks}
      onChange={(sectionMark) => onScope({ sectionMark })}
    />
    <ScopeSelect
      label="Тип листа"
      value={scope.sheetKind}
      values={facets.kinds}
      text={sheetKindLabel}
      onChange={(sheetKind) => onScope({ sheetKind })}
    />
    <ScopeSelect
      label="Корпус"
      value={scope.building}
      values={facets.buildings}
      onChange={(building) => onScope({ building })}
    />
    <ScopeSelect
      label="Секция"
      value={scope.section}
      values={facets.sections}
      onChange={(section) => onScope({ section })}
    />
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
