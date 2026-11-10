'use client';

import type { FC } from 'react';

import type { IWorkspaceCadMepRoute } from '@/components/workspace/cad/types';
import { StatusBadge } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import { jobLabel, jobTone } from '@/lib/cad/stages';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepAccept } from './CadMepAccept';
import { CadMepCandidate } from './CadMepCandidate';
import { CadMepHistory } from './CadMepHistory';
import { CadMepRecompute } from './CadMepRecompute';

interface ICadMepRouteProps {
  route: IWorkspaceCadMepRoute;
  /** Вид родителя: проект и ревизия для пересчёта. */
  parent: ICadViewParams;
  /** Открытые замечания на route-задании; `null` - ещё не прочитаны. */
  openRemarks: number | null;
}

/** Выбранное route-задание: ход, отказ, итоги генератора, принятие и скачивание. */
export const CadMepRoute: FC<ICadMepRouteProps> = ({ route, parent, openRemarks }) => {
  const { job, params, acceptance, error } = route;
  const running = job !== null && (job.status === 'queued' || job.status === 'running');

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="mep-route">
      {error && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
      {job === null && !error && (
        <p role="status" className="text-xs text-muted">
          Загрузка задания…
        </p>
      )}
      {job && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]" role="status" aria-live="polite">
          <span className="flex flex-wrap items-center gap-[var(--s-3)]">
            <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
            <span className="mono text-xs text-muted">попытка {job.attempt}</span>
          </span>
          {running && (
            <p className="text-xs text-muted">
              Трассы строятся{job.stage ? ` (${job.stage})` : ''}. Страница обновится сама.
            </p>
          )}
          {job.status === 'failed' && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {job.error_code ? cadCodeText(job.error_code) : 'Трассы не построены.'}
              {job.error_message ? ` ${job.error_message}` : ''}
            </p>
          )}
          {job.generator_version && (
            <p className="mono text-xs text-muted">{job.generator_version}</p>
          )}
          {job.approval_revoked && (
            <p role="note" className="text-xs text-danger" data-testid="mep-approval-revoked">
              Одобрение вида отозвано: принять эти трассы нельзя, просмотр доступен.
            </p>
          )}
        </div>
      )}
      {job && (
        <CadMepRecompute
          target={{ ...parent, jobId: route.summaryId, attempt: job.attempt }}
          job={job}
          accepted={acceptance !== null}
        />
      )}
      {params && (
        <>
          <CadMepCandidate params={params} />
          <CadMepAccept
            params={params}
            acceptance={acceptance}
            openRemarks={openRemarks}
            approvalRevoked={job?.approval_revoked ?? false}
            revoked={route.revokedDecisions}
          />
        </>
      )}
      {job && <CadMepHistory params={params} job={job} />}
    </div>
  );
};
