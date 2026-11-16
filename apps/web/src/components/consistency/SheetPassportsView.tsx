'use client';

import type {
  SheetPassportGroupOut,
  SheetPassportOut,
  SheetPassportStatus,
} from '@quantor/api-client';
import { useState, type FC } from 'react';

import { EmptyState, SkeletonRows } from '@/components/ui';
import {
  useBulkPassportStatus,
  useConfirmedCount,
  useSheetPassports,
  type IPassportScope,
} from '@/lib/consistency/sheet-passport-queries';
import { EMPTY_CELL, PASSPORT_PAGE_SIZE, matchesSearch } from '@/lib/consistency/sheet-passports';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { SheetPassportBulkBar } from './SheetPassportBulkBar';
import { SheetPassportEditDialog } from './SheetPassportEditDialog';
import { SheetPassportExtractPanel } from './SheetPassportExtractPanel';
import { SheetPassportFilters, type IPassportFacets } from './SheetPassportFilters';
import { SheetPassportGroupsPanel } from './SheetPassportGroupsPanel';
import { SheetPassportPager } from './SheetPassportPager';
import { SheetPassportTable } from './SheetPassportTable';

/**
 * «Листы комплекта» (ADR-0043, С1): разбор, группы, фильтры, таблица, выбор строк и правка.
 *
 * Статус, раздел, тип, корпус и секция фильтруются на сервере (страница меняется), поиск — по
 * загруженной странице. «Показать» в группе ставит фильтры группы.
 * Выбор сбрасывается при смене фильтра или страницы: в пачку не должно попасть невидимое.
 */

interface IViewProps {
  readonly projectId: string;
}

const noRows: readonly SheetPassportOut[] = [];
const noValues: readonly string[] = [];

const ALL: IPassportScope = { sectionMark: null, sheetKind: null, building: null, section: null };

/** Ключ группы в фильтр: null группы (поле не указано) - пустая строка фильтра. */
const groupScope = (group: SheetPassportGroupOut): IPassportScope => ({
  sectionMark: group.section_mark ?? '',
  sheetKind: group.sheet_kind ?? '',
  building: group.building ?? '',
  section: group.section ?? '',
});

export const SheetPassportsView: FC<IViewProps> = ({ projectId }) => {
  const [status, setStatus] = useState<SheetPassportStatus | null>(null);
  const [scope, setScope] = useState<IPassportScope>(ALL);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<SheetPassportOut | null>(null);
  const list = useSheetPassports(
    projectId,
    { ...scope, status, offset, limit: PASSPORT_PAGE_SIZE },
    true,
  );
  const confirmed = useConfirmedCount(projectId, scope, true);
  const bulk = useBulkPassportStatus(projectId);

  const items = list.data?.items ?? noRows;
  // Значения фильтров - всего проекта (сервер), а не загруженной страницы.
  const facets: IPassportFacets = {
    marks: list.data?.section_marks ?? noValues,
    kinds: list.data?.sheet_kinds ?? noValues,
    buildings: list.data?.buildings ?? noValues,
    sections: list.data?.sections ?? noValues,
  };

  const visible = items.filter((row) => matchesSearch(row, search));
  const total = list.data?.total ?? 0;

  const resetSelection = () => setSelected(new Set());
  const changeStatus = (value: SheetPassportStatus | null) => {
    setStatus(value);
    setOffset(0);
    resetSelection();
  };
  const changeScope = (value: Partial<IPassportScope>) => {
    setScope((current) => ({ ...current, ...value }));
    setOffset(0);
    resetSelection();
  };
  const showGroup = (group: SheetPassportGroupOut) => {
    setScope(groupScope(group));
    setStatus(null);
    setSearch('');
    setOffset(0);
    resetSelection();
  };
  const changeOffset = (value: number) => {
    setOffset(value);
    resetSelection();
  };

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  const toggleAll = () =>
    setSelected((current) =>
      visible.every((row) => current.has(row.id))
        ? new Set()
        : new Set(visible.map((row) => row.id)),
    );

  const applyStatus = (next: SheetPassportStatus) =>
    bulk.mutate({ ids: [...selected], status: next }, { onSuccess: resetSelection });

  const bulkError = bulk.isError
    ? (extractMessage(bulk.error) ?? errorMessage(extractCode(bulk.error)))
    : null;

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <SheetPassportExtractPanel projectId={projectId} />
      <SheetPassportGroupsPanel projectId={projectId} onShow={showGroup} />
      <SheetPassportFilters
        status={status}
        scope={scope}
        facets={facets}
        search={search}
        onStatus={changeStatus}
        onScope={changeScope}
        onSearch={setSearch}
      />
      {list.isPending && <SkeletonRows rows={6} />}
      {list.isError && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(list.error) ?? errorMessage(extractCode(list.error))}
        </p>
      )}
      {list.data && (
        <>
          <p className="tabular text-sm text-muted" aria-live="polite">
            {total} листов, подтверждено {confirmed.data ?? EMPTY_CELL}
          </p>
          {selected.size > 0 && (
            <SheetPassportBulkBar
              count={selected.size}
              pending={bulk.isPending}
              error={bulkError}
              onStatus={applyStatus}
              onClear={resetSelection}
            />
          )}
          {visible.length === 0 ? (
            <EmptyState
              compact
              title={total === 0 ? 'Листов пока нет' : 'Ничего не найдено'}
              description={
                total === 0
                  ? 'Нажмите «Разобрать листы» — портал прочитает текстовый слой PDF проекта.'
                  : 'Измените фильтры или поиск.'
              }
            />
          ) : (
            <SheetPassportTable
              rows={visible}
              selected={selected}
              onToggle={toggle}
              onToggleAll={toggleAll}
              onEdit={setEditing}
            />
          )}
          <SheetPassportPager
            offset={offset}
            limit={PASSPORT_PAGE_SIZE}
            total={total}
            onOffset={changeOffset}
          />
        </>
      )}
      {editing && (
        <SheetPassportEditDialog
          key={editing.id}
          projectId={projectId}
          row={editing}
          marks={facets.marks}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
};
