'use client';

import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';
import { useState } from 'react';

import { AuditFilters } from '@/components/common/AuditFilters';
import { Section } from '@/components/common/Section';
import { useAuditEvents, type AuditQuery } from '@/lib/queries';

/**
 * Журнал административных действий.
 *
 * Только чтение — в API нет ни одной операции изменения, а база отвергает `update`
 * и `delete` триггером. Страница это не обеспечивает и не может обеспечить; она лишь
 * не предлагает того, чего нет.
 *
 * Страницами, а не целиком: журнал растёт всё время работы установки, и «показать всё»
 * здесь означает запрос, который однажды не вернётся.
 */

const PAGE_SIZE = 50;

const RESULT_TONE = {
  success: 'success',
  failure: 'danger',
  denied: 'warning',
} as const;

const RESULT_LABEL = {
  success: 'выполнено',
  failure: 'отказ',
  denied: 'запрещено',
} as const;

const Summary = ({ label, value }: { label: string; value: unknown }) => {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex flex-col gap-[2px]">
      <span className="text-micro text-muted">{label}</span>
      <span className="mono text-micro wrap-anywhere">{JSON.stringify(value)}</span>
    </div>
  );
};

const Page = () => {
  const [query, setQuery] = useState<AuditQuery>({ limit: PAGE_SIZE, offset: 0 });
  const events = useAuditEvents(query);
  const offset = query.offset;
  const setOffset = (next: number) => setQuery((current) => ({ ...current, offset: next }));

  if (events.isPending) return <SkeletonRows rows={8} />;
  if (events.isError) {
    return (
      <ErrorState
        title="Журнал не загрузился"
        onRetry={() => void events.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  const { items, total } = events.data;
  const shown = offset + items.length;

  return (
    <Section
      title="Журнал"
      description="Кто и что менял. Записи не редактируются и не удаляются — ни отсюда, ни через API."
    >
      <AuditFilters value={query} onChange={setQuery} />

      {items.length === 0 ? (
        <EmptyState
          title="Записей нет"
          description={
            query.action || query.result || query.since || query.until
              ? 'По этим условиям ничего не нашлось. Попробуйте снять часть фильтров.'
              : 'Журнал заполняется административными действиями: изменением настроек, флагов и связей.'
          }
        />
      ) : (
        <>
          <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Когда</th>
                  <th>Кто</th>
                  <th>Действие</th>
                  <th>Объект</th>
                  <th>Итог</th>
                  <th>Изменение</th>
                </tr>
              </thead>
              <tbody>
                {items.map((event) => (
                  <tr key={event.id}>
                    <td className="mono text-micro whitespace-nowrap">
                      {new Date(event.created_at).toLocaleString('ru-RU')}
                    </td>
                    <td>
                      <div className="flex flex-col gap-[2px]">
                        <span className="text-xs wrap-anywhere">{event.actor_label ?? '—'}</span>
                        <span className="text-micro text-muted">{event.actor_role ?? ''}</span>
                      </div>
                    </td>
                    <td className="mono text-micro">{event.action}</td>
                    <td>
                      <div className="flex flex-col gap-[2px]">
                        <span className="text-xs">{event.resource_type}</span>
                        <span className="mono text-micro text-muted wrap-anywhere">
                          {event.resource_id ?? ''}
                        </span>
                      </div>
                    </td>
                    <td>
                      <StatusBadge tone={RESULT_TONE[event.result]}>
                        {RESULT_LABEL[event.result]}
                      </StatusBadge>
                      {event.error_code && (
                        <div className="mono mt-[var(--s-2)] text-micro text-muted">
                          {event.error_code}
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="flex max-w-[36ch] flex-col gap-[var(--s-2)]">
                        <Summary label="было" value={event.before_summary} />
                        <Summary label="стало" value={event.after_summary} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-[var(--s-4)]">
            <span className="text-xs text-muted">
              показано {offset + 1}–{shown} из {total}
            </span>
            <div className="flex gap-[var(--s-3)]">
              <Button
                compact
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Назад
              </Button>
              <Button
                compact
                disabled={shown >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Дальше
              </Button>
            </div>
          </div>
        </>
      )}
    </Section>
  );
};

export default Page;
