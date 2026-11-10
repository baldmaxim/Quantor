'use client';

import { useState, type FC } from 'react';

import { CadAttemptSwitcher } from '@/components/cad/CadAttemptSwitcher';
import { CadJobActions } from '@/components/cad/CadJobActions';
import { CadPipeline } from '@/components/cad/CadPipeline';
import { CadResult } from '@/components/cad/CadResult';
import { ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { serverOffsetMs } from '@/lib/cad/format';
import { isActiveStatus, useCadEvents, useCadJob } from '@/lib/cad/queries';
import { effectiveView, viewSelectionKind } from '@/lib/cad/selection';
import { jobLabel, jobTone } from '@/lib/cad/stages';
import { useTicker } from '@/lib/cad/useServerClock';
import { extractCode } from '@/lib/errors';

interface ICadJobDetailProps {
  projectId: string;
  revisionId: string;
  jobId: string;
  selectedPage: number | null;
  selectedView: number | null;
  onSelectView: (page: number, view: number) => void;
  onJobCreated: (jobId: string) => void;
}

/** Выбранное задание: попытки, ход, действия и итог. Чертёж вида показывает рабочая область. */
export const CadJobDetail: FC<ICadJobDetailProps> = ({
  projectId,
  revisionId,
  jobId,
  selectedPage,
  selectedView,
  onSelectView,
  onJobCreated,
}) => {
  const query = useCadJob(projectId, revisionId, jobId);
  // Попытка, выбранная вручную; `null` — всегда последняя, в том числе после повтора.
  const [chosenAttempt, setChosenAttempt] = useState<number | null>(null);

  const job = query.data?.job_id === jobId ? query.data : undefined;
  const attempts = job?.attempts ?? [];
  const latest = attempts.at(-1) ?? null;
  const attempt = attempts.find((item) => item.attempt === chosenAttempt) ?? latest;

  const live =
    attempt !== null &&
    job !== undefined &&
    (attempt.outcome === 'running' ||
      (attempt.attempt === job.attempt && isActiveStatus(job.status)));

  const events = useCadEvents(projectId, revisionId, jobId, attempt?.attempt ?? null, live);
  const eventLog =
    events.data && attempt && events.data.jobId === jobId && events.data.attempt === attempt.attempt
      ? events.data
      : undefined;

  const nowMs = useTicker(live);

  if (query.isPending) {
    return <SkeletonRows rows={6} />;
  }
  if (query.isError || job === undefined) {
    return (
      <ErrorState
        title="Не удалось прочитать задание"
        code={query.isError ? extractCode(query.error) : null}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const offsetMs = serverOffsetMs(job.server_time, query.dataUpdatedAt);
  // Смещение посчитано на момент получения ответа, а тик браузера мог отстать от него (экран
  // открыт без бегущей попытки, тик пришёл секундой раньше). Время не бывает раньше ответа:
  // иначе таймер стартует с нуля и шагает назад на каждом ответе.
  const clockMs = Math.max(nowMs, query.dataUpdatedAt);
  // Лист открыт без вида (из списка листов): показываем его первый вид.
  const shownView = effectiveView(job, selectedPage, selectedView);
  const selectionKind = viewSelectionKind(job, attempt, selectedPage, shownView);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
      <CadAttemptSwitcher
        attempts={attempts}
        selected={attempt?.attempt ?? 0}
        onSelect={(number) => setChosenAttempt(number === latest?.attempt ? null : number)}
      />

      {attempt === null ? (
        <section className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
          <div className="flex items-center gap-[var(--s-4)]">
            <h2 className="text-sm font-medium">Ход преобразования</h2>
            <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
          </div>
          <p className="text-xs text-muted">Попытка ещё не началась: задание ждёт исполнителя.</p>
        </section>
      ) : (
        <CadPipeline
          job={job}
          attempt={attempt}
          nowMs={clockMs}
          offsetMs={offsetMs}
          eventLog={eventLog}
          eventsLoading={events.isPending}
          eventsFailed={events.isError}
          selectedPage={selectedPage}
          selectedView={shownView}
          onSelectView={onSelectView}
        />
      )}

      <CadJobActions
        projectId={projectId}
        revisionId={revisionId}
        job={job}
        attempt={attempt}
        onJobCreated={onJobCreated}
        onRetried={() => setChosenAttempt(null)}
      />

      {attempt !== null && (
        <CadResult
          projectId={projectId}
          revisionId={revisionId}
          job={job}
          attempt={attempt.attempt}
        />
      )}

      {selectionKind === 'failed' && (
        <p role="note" className="text-xs text-muted">
          Попытка завершилась отказом: диагностика вида не выпущена. Этапы вида - в ходе попытки
          выше.
        </p>
      )}
      {selectionKind === 'unavailable' && (
        <p className="text-xs text-muted">
          Просмотр доступен только у видов выпущенного результата выбранной попытки.
        </p>
      )}
    </div>
  );
};
