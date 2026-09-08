'use client';

import type { AdminJobRead } from '@quantor/api-client';
import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';
import { useState } from 'react';

import { Section } from '@/components/common/Section';
import { Tile } from '@/components/common/Tile';
import { useAdminJobs, useCancelJob, useJobStats, useJobWorkers, useRetryJob } from '@/lib/queries';
import { NOT_MEASURED } from '@/lib/status';

/**
 * Задания и исполнители.
 *
 * Показано то, чего нет в пользовательском виде и без чего не разобрать, почему работа
 * встала: попытка, исполнитель, срок аренды и время, раньше которого задание не возьмут.
 *
 * Полезной нагрузки задания здесь нет: в ней лежат идентификаторы ревизий и ключи
 * в хранилище, и выносить их в интерфейс никто не просил.
 */

const PAGE_SIZE = 25;

const STATUS_VIEW = {
  queued: { label: 'в очереди', tone: 'neutral' },
  running: { label: 'выполняется', tone: 'accent' },
  succeeded: { label: 'выполнено', tone: 'success' },
  failed: { label: 'отказ', tone: 'danger' },
  cancelled: { label: 'отменено', tone: 'warning' },
} as const;

const FILTERS = [
  { value: '', label: 'все' },
  { value: 'queued', label: 'в очереди' },
  { value: 'running', label: 'выполняются' },
  { value: 'failed', label: 'отказы' },
] as const;

const when = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleString('ru-RU') : NOT_MEASURED;

const Row = ({ job }: { job: AdminJobRead }) => {
  const retry = useRetryJob();
  const cancel = useCancelJob();
  const view = STATUS_VIEW[job.status];
  const busy = retry.isPending || cancel.isPending;

  return (
    <tr>
      <td>
        <div className="flex flex-col gap-[2px]">
          <span className="text-xs">{job.job_type}</span>
          <span className="mono text-micro text-muted wrap-anywhere">{job.id}</span>
        </div>
      </td>
      <td>
        <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
        {job.stage && <div className="mt-[var(--s-2)] text-micro text-muted">{job.stage}</div>}
      </td>
      <td className="text-xs">
        {job.attempt} из {job.max_attempts}
      </td>
      <td>
        <div className="flex flex-col gap-[2px]">
          <span className="mono text-micro wrap-anywhere">{job.worker_id ?? NOT_MEASURED}</span>
          {job.lease_expires_at && (
            <span className="text-micro text-muted">аренда до {when(job.lease_expires_at)}</span>
          )}
        </div>
      </td>
      <td>
        {job.error_code ? (
          <div className="flex flex-col gap-[2px]">
            <span className="mono text-micro text-danger">{job.error_code}</span>
            <span className="max-w-[36ch] text-micro text-muted">{job.error_message}</span>
          </div>
        ) : (
          <span className="text-micro text-muted">—</span>
        )}
      </td>
      <td className="mono text-micro whitespace-nowrap">{when(job.created_at)}</td>
      <td>
        <div className="flex flex-wrap gap-[var(--s-3)]">
          <Button
            compact
            disabled={!job.is_retryable || busy}
            title={
              job.is_retryable
                ? undefined
                : 'Этот отказ повтором не чинится: битый архив останется битым'
            }
            onClick={() => retry.mutate(job.id)}
          >
            Повторить
          </Button>
          <Button
            compact
            variant="danger"
            disabled={job.status !== 'queued' || busy}
            title={
              job.status === 'queued'
                ? undefined
                : 'Отменить можно только то, что ещё не начали: прерванный импорт оставит полуразобранный пакет'
            }
            onClick={() => cancel.mutate(job.id)}
          >
            Отменить
          </Button>
        </div>
      </td>
    </tr>
  );
};

const Page = () => {
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);

  const stats = useJobStats();
  const workers = useJobWorkers();
  const jobs = useAdminJobs({ limit: PAGE_SIZE, offset, ...(status ? { status } : {}) });

  return (
    <Section
      title="Задания и воркеры"
      description="Очередь, ход работы и отказы. Повтор доступен там, где он что-то меняет; отмена — только для того, что ещё не начали."
    >
      <div className="grid gap-[var(--s-4)] sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="В очереди" value={stats.data ? String(stats.data.queued) : NOT_MEASURED} />
        <Tile label="Выполняется" value={stats.data ? String(stats.data.running) : NOT_MEASURED} />
        <Tile
          label="Отказы за сутки"
          value={stats.data ? String(stats.data.failed_recently) : NOT_MEASURED}
          tone={stats.data && stats.data.failed_recently > 0 ? 'danger' : 'neutral'}
          hint="Здесь ноль — это настоящий ноль: счётчик считается запросом"
        />
        <Tile
          label="Исполнители"
          value={
            stats.data ? `${stats.data.workers_alive} из ${stats.data.workers_total}` : NOT_MEASURED
          }
          tone={stats.data && stats.data.workers_alive > 0 ? 'success' : 'danger'}
          badge={
            stats.data && stats.data.workers_alive === 0 ? 'новые задания не начнутся' : undefined
          }
        />
      </div>

      {workers.data && workers.data.length > 0 && (
        <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Исполнитель</th>
                <th>Состояние</th>
                <th>Последний пульс</th>
                <th>Занят</th>
              </tr>
            </thead>
            <tbody>
              {workers.data.map((worker) => (
                <tr key={worker.id}>
                  <td>
                    <div className="flex flex-col gap-[2px]">
                      <span className="mono text-micro wrap-anywhere">{worker.id}</span>
                      <span className="text-micro text-muted">
                        {worker.host} · pid {worker.pid} · {worker.version}
                      </span>
                    </div>
                  </td>
                  <td>
                    <StatusBadge tone={worker.is_alive ? 'success' : 'danger'}>
                      {worker.is_alive ? 'на связи' : 'молчит'}
                    </StatusBadge>
                  </td>
                  <td className="mono text-micro whitespace-nowrap">{when(worker.heartbeat_at)}</td>
                  <td className="mono text-micro wrap-anywhere">{worker.current_job_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap gap-[var(--s-3)]">
        {FILTERS.map((filter) => (
          <Button
            key={filter.value}
            compact
            variant={status === filter.value ? 'primary' : 'default'}
            onClick={() => {
              setStatus(filter.value);
              setOffset(0);
            }}
          >
            {filter.label}
          </Button>
        ))}
      </div>

      {jobs.isPending ? (
        <SkeletonRows rows={6} />
      ) : jobs.isError ? (
        <ErrorState
          title="Задания не загрузились"
          onRetry={() => void jobs.refetch()}
          description="Проверьте, что API отвечает."
        />
      ) : jobs.data.items.length === 0 ? (
        <EmptyState
          title="Заданий нет"
          description="Задания появляются при загрузке распознанных пакетов."
        />
      ) : (
        <>
          <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Задание</th>
                  <th>Состояние</th>
                  <th>Попытка</th>
                  <th>Исполнитель</th>
                  <th>Отказ</th>
                  <th>Создано</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((job) => (
                  <Row key={job.id} job={job} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-[var(--s-4)]">
            <span className="text-xs text-muted">
              показано {offset + 1}–{offset + jobs.data.items.length} из {jobs.data.total}
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
                disabled={offset + jobs.data.items.length >= jobs.data.total}
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
