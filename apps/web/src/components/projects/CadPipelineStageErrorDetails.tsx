'use client';

import type { CadPipelineStageRead } from '@quantor/api-client';
import { useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
import { cadCodeText, cadErrorText } from '@/lib/cad/errors';
import { formatTime } from '@/lib/cad/format';
import { useCadStageJob } from '@/lib/cad/pipeline-queries';
import { useCadEvents, useCadJob } from '@/lib/cad/queries';

/**
 * Подробности отказа этапа. Грузятся только при открытии: задание этапа читается общим
 * `GET /jobs/{id}` (годится любому типу), а журнал событий есть только у заданий CAD-маршрутов
 * (преобразование и трассы) - для остальных этапов показаны код, текст, время и номер задания.
 */

export interface ICadPipelineStageErrorDetailsProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly stage: CadPipelineStageRead;
}

const EVENT_LIMIT = 20;

const hasEvents = (stage: CadPipelineStageRead): boolean =>
  stage.job_type === 'cad_pdf_convert' || stage.job_type === 'cad_mep_route';

const Row: FC<{ readonly label: string; readonly children: ReactNode }> = ({ label, children }) => (
  <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-[var(--s-4)]">
    <dt className="flex-none text-muted sm:w-[120px]">{label}</dt>
    <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{children}</dd>
  </div>
);

export const CadPipelineStageErrorDetails: FC<ICadPipelineStageErrorDetailsProps> = ({
  projectId,
  revisionId,
  stage,
}) => {
  const withEvents = hasEvents(stage);
  const generic = useCadStageJob(projectId, revisionId, stage.job_id, !withEvents);
  const cadJob = useCadJob(projectId, revisionId, withEvents ? stage.job_id : null);
  const events = useCadEvents(
    projectId,
    revisionId,
    withEvents ? stage.job_id : null,
    cadJob.data?.attempt ?? null,
    false,
  );
  const [copied, setCopied] = useState(false);

  const job = withEvents ? cadJob : generic;
  const code = job.data?.error_code ?? stage.error_code;
  const message = job.data?.error_message ?? null;
  const stageName = job.data?.stage ?? stage.stage;
  const finishedAt = job.data?.finished_at ?? stage.finished_at;
  const lastEvents = (events.data?.events ?? []).slice(-EVENT_LIMIT);

  const copy = () => {
    void navigator.clipboard?.writeText(stage.job_id).then(() => setCopied(true));
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border bg-surface-muted p-[var(--s-4)] text-xs">
      {job.isPending && !job.isError && <p className="m-0 text-muted">Загрузка…</p>}
      {job.isError && (
        <p role="alert" className="m-0 text-danger [overflow-wrap:anywhere]">
          Не удалось загрузить задание: {cadErrorText(job.error)}
        </p>
      )}
      <dl className="m-0 flex flex-col gap-[var(--s-2)]">
        <Row label="Код ошибки">
          {code ? <span className="font-mono">{code}</span> : <span className="text-muted">нет</span>}
        </Row>
        {code && <Row label="Что значит">{cadCodeText(code)}</Row>}
        {message && <Row label="Сообщение сервера">{message}</Row>}
        {stageName && <Row label="Стадия">{stageName}</Row>}
        {finishedAt && <Row label="Завершено">{formatTime(finishedAt)}</Row>}
        <Row label="Задание">
          <span className="inline-flex flex-wrap items-center gap-x-[var(--s-3)]">
            <span className="font-mono">{stage.job_id}</span>
            <Button compact onClick={copy} className="max-md:h-[44px]">
              {copied ? 'Скопировано' : 'Копировать'}
            </Button>
          </span>
        </Row>
      </dl>
      {lastEvents.length > 0 && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <p className="m-0 text-muted">{`Последние события (${lastEvents.length})`}</p>
          <ul className="m-0 flex max-h-[200px] list-none flex-col gap-0.5 overflow-auto p-0 font-mono text-[11px] [overscroll-behavior:contain]">
            {lastEvents.map((event) => (
              <li key={event.seq} className="[overflow-wrap:anywhere]">
                {[formatTime(event.at), event.status, event.phase ?? event.stage, event.detail]
                  .filter((part) => part)
                  .join(' · ')}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
