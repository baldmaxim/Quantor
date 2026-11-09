'use client';

import type { CadAttemptRead, CadJobRead } from '@quantor/api-client';
import type { FC } from 'react';

import { CadEventTimeline } from '@/components/cad/CadEventTimeline';
import { CadViewStages } from '@/components/cad/CadViewStages';
import { StatusBadge } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import { documentEvents, type ICadEventLog } from '@/lib/cad/events';
import { attemptElapsedSeconds, pageNumber } from '@/lib/cad/format';
import { formatElapsed, jobLabel, jobTone, outcomeLabel, phaseLabel } from '@/lib/cad/stages';
import { useHeldElapsed } from '@/lib/cad/useServerClock';

interface ICadPipelineProps {
  job: CadJobRead;
  attempt: CadAttemptRead;
  /** Часы браузера, тикающие раз в секунду, и смещение часов сервера. */
  nowMs: number;
  offsetMs: number;
  eventLog: ICadEventLog | undefined;
  eventsLoading: boolean;
  eventsFailed: boolean;
  selectedPage: number | null;
  selectedView: number | null;
  onSelectView: (page: number, view: number) => void;
}

const pagesText = (indexes: readonly number[]): string =>
  indexes.length === 0 ? '—' : indexes.map((index) => pageNumber(index)).join(', ');

/** Ход выбранной попытки: состояние, таймер, фаза, план страниц, события и этапы по видам. */
export const CadPipeline: FC<ICadPipelineProps> = ({
  job,
  attempt,
  nowMs,
  offsetMs,
  eventLog,
  eventsLoading,
  eventsFailed,
  selectedPage,
  selectedView,
  onSelectView,
}) => {
  const running = attempt.outcome === 'running';
  const rawElapsed = attemptElapsedSeconds(
    attempt.started_at,
    attempt.finished_at,
    running,
    nowMs,
    offsetMs,
  );
  const elapsed = useHeldElapsed(`${job.job_id}:${attempt.attempt}`, rawElapsed, running);
  const isLatest = attempt.attempt === job.attempt;
  const plan = attempt.pages;

  return (
    <section className="flex flex-col gap-[var(--s-5)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
      <header className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 className="text-sm font-medium">Ход преобразования</h2>
        {isLatest && <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>}
        <span className="mono text-xs text-muted">попытка {attempt.attempt}</span>
        <StatusBadge
          tone={attempt.outcome === 'failed' || attempt.outcome === 'lost' ? 'danger' : 'neutral'}
          dot={false}
        >
          {outcomeLabel(attempt.outcome)}
        </StatusBadge>
        <span className="mono ml-auto text-sm tabular" aria-label="Время работы попытки">
          {formatElapsed(elapsed)}
        </span>
      </header>

      <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-5)] gap-y-[var(--s-3)] text-xs">
        <dt className="text-muted">Фаза</dt>
        <dd className="m-0 [overflow-wrap:anywhere]">
          {phaseLabel(attempt.phase)}
          {attempt.phase_detail && <span className="text-muted"> · {attempt.phase_detail}</span>}
        </dd>

        <dt className="text-muted">Страницы</dt>
        <dd className="m-0">
          {plan ? (
            <>
              Страниц в PDF: {plan.total ?? '—'} · плановых: {pagesText(plan.planned)} · в работе:{' '}
              {pagesText(plan.requested)}
            </>
          ) : (
            <span className="text-muted">План страниц ещё не сообщён движком</span>
          )}
        </dd>

        {attempt.engine && (
          <>
            <dt className="text-muted">Движок</dt>
            <dd className="m-0 [overflow-wrap:anywhere]">
              <span className="mono">
                {attempt.engine.stage} · {attempt.engine.status}
              </span>
              {attempt.engine.error && (
                <span className="text-danger"> · {attempt.engine.error}</span>
              )}
            </dd>
          </>
        )}

        {attempt.error_code && (
          <>
            <dt className="text-muted">Отказ</dt>
            <dd className="m-0 [overflow-wrap:anywhere]">
              <span className="mono text-danger">{attempt.error_code}</span>
              <span> · {cadCodeText(attempt.error_code)}</span>
            </dd>
          </>
        )}
      </dl>

      <CadEventTimeline
        attempt={attempt}
        events={eventLog ? documentEvents(eventLog) : []}
        loading={eventsLoading}
        failed={eventsFailed}
      />

      <CadViewStages
        attempt={attempt}
        selectedPage={selectedPage}
        selectedView={selectedView}
        onSelectView={onSelectView}
      />
    </section>
  );
};
