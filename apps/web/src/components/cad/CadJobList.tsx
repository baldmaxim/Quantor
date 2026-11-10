'use client';

import type { CadJobSummaryRead } from '@quantor/api-client';
import type { FC } from 'react';

import { ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import { formatTime, requestedPagesLabel } from '@/lib/cad/format';
import { useCadJobs } from '@/lib/cad/queries';
import { jobLabel, jobTone, resultInfo } from '@/lib/cad/stages';
import { extractCode } from '@/lib/errors';

interface ICadJobListProps {
  projectId: string;
  revisionId: string;
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

/** Очередь и история заданий выбранной ревизии, новые сверху. */
export const CadJobList: FC<ICadJobListProps> = ({
  projectId,
  revisionId,
  selectedJobId,
  onSelect,
}) => {
  const jobs = useCadJobs(projectId, revisionId);

  return (
    // Рамка и заголовок — у вкладки «Задания» в CadScreen.
    <div className="flex flex-col gap-[var(--s-4)]">
      {jobs.isPending ? (
        <SkeletonRows rows={3} />
      ) : jobs.isError ? (
        <ErrorState
          title="Не удалось прочитать задания"
          code={extractCode(jobs.error)}
          onRetry={() => void jobs.refetch()}
        />
      ) : jobs.data.items.length === 0 ? (
        <p className="text-xs text-muted">Заданий пока нет.</p>
      ) : (
        <ul className="flex flex-col rounded-[var(--radius-md)] border border-border">
          {jobs.data.items.map((job) => (
            <JobRow
              key={job.job_id}
              job={job}
              selected={job.job_id === selectedJobId}
              onSelect={() => onSelect(job.job_id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
};

interface IJobRowProps {
  job: CadJobSummaryRead;
  selected: boolean;
  onSelect: () => void;
}

const JobRow: FC<IJobRowProps> = ({ job, selected, onSelect }) => {
  const result = resultInfo(job.result_status);

  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={cx(
          'flex min-h-[44px] w-full flex-col items-start gap-[var(--s-3)] px-[var(--s-5)] py-[var(--s-4)] text-left hover:bg-surface-muted',
          selected && 'bg-accent-soft',
        )}
      >
        <span className="flex flex-wrap items-center gap-[var(--s-3)]">
          <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
          <span className="mono text-xs text-muted">попытка {job.attempt}</span>
          {job.error_code && <span className="mono text-xs text-danger">{job.error_code}</span>}
        </span>
        <span className="text-xs text-muted">
          {formatTime(job.created_at)} · {requestedPagesLabel(job.requested_pages)}
        </span>
        {result && (
          <StatusBadge tone={result.tone} dot={false} wrap>
            {result.label}
          </StatusBadge>
        )}
      </button>
    </li>
  );
};
