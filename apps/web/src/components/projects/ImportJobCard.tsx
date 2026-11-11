import type { ProjectJobSummary } from '@quantor/api-client';
import type { FC } from 'react';

import { Field, ProgressRow } from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { formatWhen } from '@/lib/format';

/** Последнее задание проекта - импорт распознанного пакета. */
export const ImportJobCard: FC<{ readonly job: ProjectJobSummary }> = ({ job }) => {
  const running = job.status === 'queued' || job.status === 'running';

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-6)] gap-y-[var(--s-2)]">
        <Field label="Задание">{job.job_type}</Field>
        <Field label="Состояние">{job.status}</Field>
        {job.stage && <Field label="Стадия">{job.stage}</Field>}
        {job.error_code && <Field label="Код ошибки">{job.error_code}</Field>}
        {job.finished_at && <Field label="Завершено">{formatWhen(job.finished_at)}</Field>}
      </dl>

      {running && <ProgressRow value={job.progress} label="Импорт пакета" />}

      {job.error_code && <p className="text-sm text-danger">{errorMessage(job.error_code)}</p>}

      {job.status === 'failed' && (
        <p className="text-sm text-muted">
          Пакет остался в хранилище — повторная загрузка запустит импорт заново.
        </p>
      )}
    </div>
  );
};
