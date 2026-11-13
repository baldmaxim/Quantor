'use client';

import type { AdminJobsCancelRequest } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button, EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { JOBS_MANAGE_PERMISSION, QUEUE_ACCESS_PERMISSION } from '@/lib/jobs/permissions';
import { queueCounts, useCancelJobs, useJobQueue } from '@/lib/jobs/queue-queries';
import { useSession } from '@/lib/session';

import { CancelConfirmDialog } from './CancelConfirmDialog';
import { QUEUE_GRID, QueueRow } from './QueueRow';

/**
 * Очередь заданий по всем проектам с отменой: одного, выбранных или всей очереди.
 * Фильтр по проекту приходит и уходит через пропсы: страница держит его в адресе (`?project=`).
 */

export interface IQueueBoardProps {
  readonly projectId: string | null;
  readonly onProjectChange: (projectId: string | null) => void;
}

type Pending = { readonly request: AdminJobsCancelRequest; readonly count: number } | null;

const ALL_PROJECTS = '';
const HEADER_CELL = 'text-xs font-medium text-muted';

export const QueueBoard: FC<IQueueBoardProps> = ({ projectId, onProjectChange }) => {
  const session = useSession();
  const permissions = session.data?.permissions;
  const canRead = permissions?.includes(QUEUE_ACCESS_PERMISSION) ?? false;
  const canManage = permissions?.includes(JOBS_MANAGE_PERMISSION) ?? false;

  const queue = useJobQueue(projectId ?? undefined);
  const cancel = useCancelJobs();

  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [pending, setPending] = useState<Pending>(null);
  const [summary, setSummary] = useState<string | null>(null);
  // Проекты копятся: при фильтре в списке остаётся один, а выбрать другой всё равно надо.
  const [known, setKnown] = useState<Readonly<Record<string, string>>>({});

  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const total = queue.data?.total ?? 0;

  // Накопление при новом ответе — прямо в отрисовке, без эффекта: так React советует
  // выводить состояние из пришедших данных.
  const [seenItems, setSeenItems] = useState(items);
  if (seenItems !== items) {
    setSeenItems(items);
    const next: Record<string, string> = { ...known };
    for (const job of items) {
      if (job.project_id !== null) next[job.project_id] = job.project_name ?? job.project_id;
    }
    setKnown(next);
  }

  // Выбранное, чего уже нет в очереди (завершилось или отменено), в счёт не идёт.
  const selectedIds = useMemo(
    () => items.filter((job) => selected.has(job.id)).map((job) => job.id),
    [items, selected],
  );
  const counts = queueCounts(items);

  const projectOptions = useMemo(() => {
    const entries = new Map(Object.entries(known));
    if (projectId !== null && !entries.has(projectId)) entries.set(projectId, projectId);
    return [...entries].sort((a, b) => a[1].localeCompare(b[1], 'ru'));
  }, [known, projectId]);

  if (session.isPending) return <SkeletonRows rows={4} />;
  if (!canRead) {
    return (
      <EmptyState title="Нет доступа" description="Очередь заданий доступна администраторам." />
    );
  }

  const toggle = (jobId: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(jobId)) next.add(jobId);
      return next;
    });
  const allSelected = items.length > 0 && selectedIds.length === items.length;
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map((j) => j.id)));

  const run = (request: AdminJobsCancelRequest) => {
    setSummary(null);
    cancel.mutate(request, {
      onSuccess: (result) => {
        setSummary(`Отменено ${result.cancelled}, пропущено ${result.skipped}`);
        setSelected(new Set());
        setPending(null);
      },
      onError: () => {
        setSummary('Не удалось отменить задания');
        setPending(null);
      },
    });
  };

  const askSelected = () =>
    setPending({
      request: { job_ids: selectedIds, project_id: projectId },
      count: selectedIds.length,
    });
  const askAll = () =>
    setPending({ request: { all_active: true, project_id: projectId }, count: total });

  const runningInSelection = items.some((j) => j.status === 'running' && selected.has(j.id));
  const pendingHasRunning =
    pending?.request.all_active === true ? counts.running > 0 : runningInSelection;
  const allLabel = projectId === null ? 'Завершить всю очередь' : 'Завершить очередь проекта';

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <div className="flex flex-col gap-[var(--s-4)] md:flex-row md:flex-wrap md:items-center">
        <p data-testid="queue-counts" className="m-0 text-sm text-muted">
          выполняется {counts.running} · в очереди {counts.queued}
          {total > items.length && ` · показаны первые ${items.length} из ${total}`}
        </p>
        <label className="flex min-w-0 items-center gap-[var(--s-3)] text-sm md:ml-auto">
          <span className="shrink-0 text-muted">Проект</span>
          <select
            value={projectId ?? ALL_PROJECTS}
            onChange={(event) => {
              setSelected(new Set());
              onProjectChange(event.target.value === ALL_PROJECTS ? null : event.target.value);
            }}
            className="h-[44px] min-w-0 flex-1 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:h-[var(--h-ctl)] md:flex-none md:text-sm"
          >
            <option value={ALL_PROJECTS}>Все проекты</option>
            {projectOptions.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {canManage && items.length > 0 && (
        <div className="flex flex-col gap-[var(--s-3)] md:flex-row md:items-center">
          <Button onClick={toggleAll}>{allSelected ? 'Снять выбор' : 'Выбрать все'}</Button>
          <Button variant="danger" disabled={selectedIds.length === 0} onClick={askSelected}>
            Отменить выбранные ({selectedIds.length})
          </Button>
          <Button variant="danger" onClick={askAll}>
            {allLabel}
          </Button>
        </div>
      )}

      {summary !== null && (
        <p role="status" className="m-0 text-sm text-text">
          {summary}
        </p>
      )}

      {queue.isPending && <SkeletonRows rows={5} />}
      {queue.isError && (
        <ErrorState title="Не удалось получить очередь" onRetry={() => void queue.refetch()} />
      )}
      {queue.data && items.length === 0 && <EmptyState compact title="Очередь пуста" />}

      {items.length > 0 && (
        <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <div
            aria-hidden="true"
            className={`hidden border-b border-border px-[var(--s-5)] py-[var(--s-3)] ${QUEUE_GRID}`}
          >
            <span />
            <span className={HEADER_CELL}>Проект</span>
            <span className={HEADER_CELL}>Задание</span>
            <span className={HEADER_CELL}>Этап</span>
            <span className={HEADER_CELL}>Прогресс</span>
            <span className={HEADER_CELL}>Статус</span>
            <span className={HEADER_CELL}>Попытка</span>
            <span className={HEADER_CELL}>Создано</span>
            <span />
          </div>
          <ul aria-label="Очередь заданий" className="m-0 list-none p-0">
            {items.map((job) => (
              <QueueRow
                key={job.id}
                job={job}
                selected={selected.has(job.id)}
                canManage={canManage}
                busy={cancel.isPending}
                onToggle={toggle}
                onCancel={(jobId) => run({ job_ids: [jobId] })}
              />
            ))}
          </ul>
        </div>
      )}

      <CancelConfirmDialog
        open={pending !== null}
        title={pending?.request.all_active === true ? allLabel : 'Отменить выбранные'}
        description={`Будет отменено заданий: ${pending?.count ?? 0}.`}
        hasRunning={pendingHasRunning}
        busy={cancel.isPending}
        onConfirm={() => pending && run(pending.request)}
        onClose={() => setPending(null)}
      />
    </div>
  );
};
