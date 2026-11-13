'use client';

import type { FC } from 'react';

import { ErrorState, Skeleton } from '@/components/ui';
import { useCadQueue } from '@/lib/cad/queue-queries';

import { CadQueueRow } from './CadQueueRow';
import { CadRecognitionSummary } from './CadRecognitionSummary';

/**
 * Очередь CAD проекта на главной: исполнитель берёт задания по одному, поэтому видно, что
 * выполняется, что ждёт и сколько заданий впереди (в том числе чужих проектов - только числом).
 */

export interface ICadQueueCardProps {
  readonly projectId: string;
}

export const CadQueueCard: FC<ICadQueueCardProps> = ({ projectId }) => {
  const queue = useCadQueue(projectId, true);
  const data = queue.data;

  return (
    <section
      aria-label="Очередь CAD"
      className="min-w-0 overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface xl:flex xl:max-h-full xl:flex-col"
    >
      <h2 className="shrink-0 border-b border-border px-[var(--s-6)] py-[var(--s-5)] text-sm font-medium">
        Очередь CAD
      </h2>

      <CadRecognitionSummary projectId={projectId} />

      {queue.isPending && <Skeleton className="m-[var(--s-6)] h-[48px] w-auto" />}

      {queue.isError && (
        <div className="px-[var(--s-6)] py-[var(--s-5)]">
          <ErrorState
            title="Не удалось получить очередь CAD"
            onRetry={() => void queue.refetch()}
          />
        </div>
      )}

      {data && (
        <>
          <p
            data-testid="cad-queue-summary"
            className="m-0 shrink-0 border-b border-border px-[var(--s-6)] py-[var(--s-3)] text-xs text-muted"
          >
            Исполнитель: выполняется {data.running_total}, в очереди {data.queued_total} (все
            проекты)
          </p>
          {data.items.length === 0 ? (
            <p className="m-0 px-[var(--s-6)] py-[var(--s-5)] text-sm text-muted">
              Заданий CAD нет
            </p>
          ) : (
            <ul
              aria-label="Задания CAD проекта"
              className="m-0 max-h-[60dvh] list-none overflow-y-auto overscroll-contain p-0 xl:max-h-none xl:min-h-0"
            >
              {data.items.map((item) => (
                <CadQueueRow key={item.job_id} projectId={projectId} item={item} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
};
