'use client';

import type { SheetPassportOut, SheetPassportStatus } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { EmptyState, SkeletonRows } from '@/components/ui';
import {
  useBulkPassportStatus,
  useConfirmedCount,
  useSheetPassports,
} from '@/lib/consistency/sheet-passport-queries';
import {
  EMPTY_CELL,
  PASSPORT_PAGE_SIZE,
  matchesSearch,
  sectionMarksOf,
} from '@/lib/consistency/sheet-passports';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { SheetPassportBulkBar } from './SheetPassportBulkBar';
import { SheetPassportEditDialog } from './SheetPassportEditDialog';
import { SheetPassportExtractPanel } from './SheetPassportExtractPanel';
import { SheetPassportFilters } from './SheetPassportFilters';
import { SheetPassportPager } from './SheetPassportPager';
import { SheetPassportTable } from './SheetPassportTable';

/**
 * «Листы комплекта» (ADR-0043, С1): разбор, фильтры, таблица, выбор строк и правка.
 *
 * Статус и раздел фильтруются на сервере (страница меняется), поиск — по загруженной странице.
 * Выбор сбрасывается при смене фильтра или страницы: в пачку не должно попасть невидимое.
 */

interface IViewProps {
  readonly projectId: string;
}

const noRows: readonly SheetPassportOut[] = [];

export const SheetPassportsView: FC<IViewProps> = ({ projectId }) => {
  const [status, setStatus] = useState<SheetPassportStatus | null>(null);
  const [sectionMark, setSectionMark] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<SheetPassportOut | null>(null);
  // Марки копятся по мере загрузки: после фильтра по разделу список не должен схлопнуться.
  const [knownMarks, setKnownMarks] = useState<readonly string[]>([]);

  const list = useSheetPassports(
    projectId,
    { status, sectionMark, offset, limit: PASSPORT_PAGE_SIZE },
    true,
  );
  const confirmed = useConfirmedCount(projectId, sectionMark, true);
  const bulk = useBulkPassportStatus(projectId);

  const items = list.data?.items ?? noRows;
  const found = sectionMarksOf(items);
  const merged = [...new Set([...knownMarks, ...found, ...(sectionMark ? [sectionMark] : [])])];
  if (merged.length !== knownMarks.length) {
    setKnownMarks(merged);
  }

  const visible = items.filter((row) => matchesSearch(row, search));
  const total = list.data?.total ?? 0;

  const resetSelection = () => setSelected(new Set());
  const changeStatus = (value: SheetPassportStatus | null) => {
    setStatus(value);
    setOffset(0);
    resetSelection();
  };
  const changeSection = (value: string | null) => {
    setSectionMark(value);
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
      <SheetPassportFilters
        status={status}
        sectionMark={sectionMark}
        marks={knownMarks}
        search={search}
        onStatus={changeStatus}
        onSectionMark={changeSection}
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
          marks={knownMarks}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
};
