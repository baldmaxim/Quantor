import type { AdminJobRead } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { Button, StatusBadge } from '@/components/ui';
import { formatWhen } from '@/lib/format';
import { jobStatusView, jobTypeLabel, progressPercent } from '@/lib/jobs/job-labels';

/**
 * Строка очереди заданий. Узкий экран - карточкой, от 768 px - строкой таблицы по общей сетке
 * `QUEUE_GRID` (шапка колонок в `QueueBoard`).
 */

/** Колонки таблицы: чекбокс, проект, тип, этап, прогресс, статус, попытка, создано, действие. */
export const QUEUE_GRID =
  'md:grid md:grid-cols-[44px_minmax(0,1.4fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_64px_minmax(0,0.9fr)_112px] md:items-center md:gap-x-[var(--s-4)]';

export interface IQueueRowProps {
  readonly job: AdminJobRead;
  readonly selected: boolean;
  readonly canManage: boolean;
  readonly busy: boolean;
  readonly onToggle: (jobId: string) => void;
  readonly onCancel: (jobId: string) => void;
}

const CELL = 'min-w-0 text-sm [overflow-wrap:anywhere]';

export const QueueRow: FC<IQueueRowProps> = ({
  job,
  selected,
  canManage,
  busy,
  onToggle,
  onCancel,
}) => {
  const status = jobStatusView(job.status);
  const percent = progressPercent(job.progress);
  const projectName = job.project_name ?? 'Без проекта';

  return (
    <li
      className={`flex flex-col gap-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0 md:py-[var(--s-3)] ${QUEUE_GRID}`}
    >
      <div className="flex min-w-0 items-center gap-[var(--s-3)] md:contents">
        {canManage ? (
          <label className="flex size-[44px] shrink-0 cursor-pointer items-center justify-center">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggle(job.id)}
              aria-label={`Выбрать задание: ${jobTypeLabel(job.job_type)}, ${projectName}`}
              className="size-5"
            />
          </label>
        ) : (
          <span aria-hidden="true" className="hidden md:block" />
        )}
        <div className={`${CELL} font-medium`}>
          {job.project_id !== null ? (
            <Link
              href={`/projects/${job.project_id}`}
              className="text-accent hover:underline focus-visible:underline"
            >
              {projectName}
            </Link>
          ) : (
            <span className="text-muted">{projectName}</span>
          )}
        </div>
      </div>

      <div className={CELL}>{jobTypeLabel(job.job_type)}</div>
      <div className={`${CELL} text-muted`}>{job.stage ?? '—'}</div>

      <div className="flex min-w-0 items-center gap-[var(--s-3)]">
        <div
          role="progressbar"
          aria-label="Прогресс задания"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? undefined}
          className="h-[4px] min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken"
        >
          <div className="h-full bg-accent" style={{ width: `${percent ?? 0}%` }} />
        </div>
        <span className="tabular w-[40px] shrink-0 text-right text-xs text-muted">
          {percent === null ? '—' : `${percent} %`}
        </span>
      </div>

      <div>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
      </div>
      <div className="mono text-xs text-muted">
        <span className="md:hidden">Попытка </span>
        {job.attempt}/{job.max_attempts}
      </div>
      <div className="text-xs text-muted">{formatWhen(job.created_at)}</div>

      {canManage ? (
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => onCancel(job.id)}
          aria-label={`Отменить задание: ${jobTypeLabel(job.job_type)}, ${projectName}`}
          className="w-full md:w-auto"
        >
          Отменить
        </Button>
      ) : (
        <span aria-hidden="true" className="hidden md:block" />
      )}
    </li>
  );
};
