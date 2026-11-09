'use client';

import type { CadAttemptRead, CadEventRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { secondsSince } from '@/lib/cad/format';
import { formatElapsed, phaseLabel, stateLabel, stateTone } from '@/lib/cad/stages';

interface ICadEventTimelineProps {
  attempt: CadAttemptRead;
  /** События документа целиком, по возрастанию номера. */
  events: readonly CadEventRead[];
  loading: boolean;
  failed: boolean;
}

/** Хронология событий документа: только то, что сообщил сервер. */
export const CadEventTimeline: FC<ICadEventTimelineProps> = ({
  attempt,
  events,
  loading,
  failed,
}) => (
  <section className="flex flex-col gap-[var(--s-4)]">
    <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
      События попытки
    </h3>

    {attempt.events_dropped > 0 && (
      <p role="status" className="text-xs text-warning">
        Часть событий ({attempt.events_dropped}) отброшена сервером из-за предела журнала:
        хронология неполная.
      </p>
    )}

    {failed ? (
      <p className="text-xs text-danger">Не удалось прочитать события.</p>
    ) : events.length === 0 ? (
      <p className="text-xs text-muted">{loading ? 'Читаем события…' : 'Событий пока нет.'}</p>
    ) : (
      <ol className="flex flex-col rounded-[var(--radius-md)] border border-border">
        {events.map((event) => {
          const since = secondsSince(attempt.started_at, event.at);
          return (
            <li
              key={event.seq}
              className="flex flex-wrap items-baseline gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-3)] text-xs last:border-b-0"
            >
              <span className="mono w-[64px] flex-none text-muted tabular">
                {since === null ? '—' : `+${formatElapsed(since)}`}
              </span>
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                {phaseLabel(event.phase)}
                {event.detail && <span className="text-muted"> · {event.detail}</span>}
              </span>
              <StatusBadge tone={stateTone(event.status)} dot={false}>
                {stateLabel(event.status)}
              </StatusBadge>
              {event.elapsed_s !== null && event.elapsed_s !== undefined && (
                <span className="mono text-muted">{formatElapsed(event.elapsed_s)}</span>
              )}
            </li>
          );
        })}
      </ol>
    )}
  </section>
);
