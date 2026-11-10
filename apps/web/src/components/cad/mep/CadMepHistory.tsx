'use client';

import type { CadJobRead, CadMepAttemptRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, StatusBadge } from '@/components/ui';
import { formatTime } from '@/lib/cad/format';
import { cadCodeText } from '@/lib/cad/errors';
import { floorSourceLabel } from '@/lib/cad/mep-candidate';
import { useCadCandidate } from '@/lib/cad/mep-queries';
import { jobLabel, jobTone } from '@/lib/cad/stages';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepCandidateBody } from './CadMepCandidate';

interface ICadMepHistoryProps {
  /** Route-задание: лист, вид и текущая попытка с результатом. */
  params: ICadViewParams | null;
  job: CadJobRead;
}

const requestText = (attempt: CadMepAttemptRead): string => {
  const e = attempt.requested_elevation_mm;
  const h = attempt.requested_height_mm;
  if (e === null && h === null) return 'по документации';
  return `пол ${e ?? 'по документации'} · этаж ${h ?? 'по документации'}`;
};

const resultText = (attempt: CadMepAttemptRead): string => {
  if (attempt.floor_elevation_mm === null && attempt.floor_height_mm === null) return '';
  return `пол ${attempt.floor_elevation_mm ?? '—'} мм (${floorSourceLabel(attempt.floor_elevation_source)}) · этаж ${attempt.floor_height_mm ?? '—'} мм (${floorSourceLabel(attempt.floor_height_source)})`;
};

const PastAttempt: FC<{ params: ICadViewParams; attempt: number }> = ({ params, attempt }) => {
  const query = useCadCandidate(params, true, attempt);
  if (query.isPending) {
    return (
      <p role="status" className="text-xs text-muted">
        Загрузка итогов попытки…
      </p>
    );
  }
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-danger">
        Итоги попытки не загружены.
      </p>
    );
  }
  return <CadMepCandidateBody candidate={query.data} />;
};

/**
 * История расчётов route-задания: номер попытки, когда запрошена, что запросил человек, что
 * получилось и итог. Прошлую попытку можно открыть только на просмотр (итоги генератора).
 */
export const CadMepHistory: FC<ICadMepHistoryProps> = ({ params, job }) => {
  const [opened, setOpened] = useState<number | null>(null);
  const attempts = job.route_attempts ?? [];
  if (attempts.length === 0) return null;

  return (
    <details className="min-w-0" data-testid="mep-history">
      <summary className="flex min-h-[44px] cursor-pointer items-center text-sm font-medium">
        История расчётов ({attempts.length})
      </summary>
      <ul className="flex flex-col gap-[var(--s-3)]" aria-label="История расчётов">
        {[...attempts].reverse().map((attempt) => {
          const past = attempt.status === 'succeeded' && attempt.attempt !== job.result_attempt;
          return (
            <li
              key={attempt.attempt}
              className="flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-3)] text-xs"
            >
              <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                <span className="mono">№{attempt.attempt}</span>
                <StatusBadge tone={jobTone(attempt.status)}>{jobLabel(attempt.status)}</StatusBadge>
                {attempt.attempt === job.result_attempt && <span className="text-muted">текущая</span>}
                {attempt.requested_at && (
                  <span className="text-muted">{formatTime(attempt.requested_at)}</span>
                )}
              </span>
              <span className="[overflow-wrap:anywhere]">Запрос: {requestText(attempt)}</span>
              {resultText(attempt) && (
                <span className="[overflow-wrap:anywhere]">Итог: {resultText(attempt)}</span>
              )}
              {attempt.error_code && (
                <span className="text-danger [overflow-wrap:anywhere]">
                  {cadCodeText(attempt.error_code)}
                </span>
              )}
              {past && params && (
                <>
                  <Button
                    onClick={() => setOpened(opened === attempt.attempt ? null : attempt.attempt)}
                    aria-expanded={opened === attempt.attempt}
                    className="self-start max-md:h-[44px] max-md:w-full"
                  >
                    {opened === attempt.attempt ? 'Скрыть попытку' : 'Открыть на просмотр'}
                  </Button>
                  {opened === attempt.attempt && (
                    <PastAttempt params={params} attempt={attempt.attempt} />
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
};
