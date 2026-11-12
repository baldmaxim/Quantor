'use client';

import type { FC } from 'react';

import { ErrorState, Skeleton } from '@/components/ui';
import { useCadQueue } from '@/lib/cad/queue-queries';

import { CadQueueRow } from './CadQueueRow';

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
      className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface"
    >
      <h2 className="border-b border-border px-[var(--s-6)] py-[var(--s-5)] text-sm font-medium">
        Очередь CAD
      </h2>

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
            className="m-0 border-b border-border px-[var(--s-6)] py-[var(--s-3)] text-xs text-muted"
          >
            Исполнитель: выполняется {data.running_total}, в очереди {data.queued_total} (все
            проекты)
          </p>
          {data.items.length === 0 ? (
            <p className="m-0 px-[var(--s-6)] py-[var(--s-5)] text-sm text-muted">
              Заданий CAD нет
            </p>
          ) : (
            <ul aria-label="Задания CAD проекта" className="m-0 list-none p-0">
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
