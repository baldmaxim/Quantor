import type { ProjectJobSummary } from '@quantor/api-client';
import type { FC } from 'react';

import { Field, ProgressRow, StatusBadge } from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { jobStatusView, jobTypeLabel } from '@/lib/jobs/job-labels';

/**
 * Последнее задание проекта (импорт пакета, разбор паспортов листов…): что это за задание и чем
 * кончилось - словами, без кодов типа и стадии.
 */
export const ImportJobCard: FC<{ readonly job: ProjectJobSummary }> = ({ job }) => {
  const running = job.status === 'queued' || job.status === 'running';
  const status = jobStatusView(job.status);

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-[var(--s-6)] gap-y-[var(--s-2)]">
        <Field label="Задание">{jobTypeLabel(job.job_type)}</Field>
        <Field label="Состояние">
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        </Field>
        {job.finished_at && <Field label="Завершено">{formatWhen(job.finished_at)}</Field>}
      </dl>
      {running && <ProgressRow value={job.progress} label={jobTypeLabel(job.job_type)} />}
      {job.error_code && <p className="text-sm text-danger">{errorMessage(job.error_code)}</p>}
      {job.status === 'failed' && job.job_type === 'legacy_import' && (
        <p className="text-sm text-muted">
          Пакет остался в хранилище — повторная загрузка запустит импорт заново.
        </p>
      )}
    </div>
  );
};
