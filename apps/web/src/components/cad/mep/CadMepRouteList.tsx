'use client';

import type { CadRouteJobRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { formatTime } from '@/lib/cad/format';
import { jobLabel, jobTone } from '@/lib/cad/stages';

interface ICadMepRouteListProps {
  routeJobs: readonly CadRouteJobRead[];
  selectedId: string | null;
  onSelect: (jobId: string) => void;
}

/** Построенные трассы этого вида: задание на каждое одобрение, попытки - внутри задания. */
export const CadMepRouteList: FC<ICadMepRouteListProps> = ({ routeJobs, selectedId, onSelect }) => {
  if (routeJobs.length === 0) {
    return <p className="text-xs text-muted">Трассы для этого вида ещё не строились.</p>;
  }
  return (
    <ul
      aria-label="Трассы вида"
      className="flex flex-col rounded-[var(--radius-md)] border border-border"
    >
      {routeJobs.map((route) => (
        <li key={route.job_id} className="border-b border-border last:border-b-0">
          <button
            type="button"
            aria-current={route.job_id === selectedId ? 'true' : undefined}
            onClick={() => onSelect(route.job_id)}
            className={cx(
              'flex min-h-[44px] w-full flex-col items-start gap-[var(--s-2)] px-[var(--s-5)] py-[var(--s-4)] text-left hover:bg-surface-muted',
              route.job_id === selectedId && 'bg-accent-soft',
            )}
          >
            <span className="flex flex-wrap items-center gap-[var(--s-3)]">
              <StatusBadge tone={jobTone(route.status)}>{jobLabel(route.status)}</StatusBadge>
              {route.accepted && (
                <StatusBadge tone="success" dot={false}>
                  Приняты
                </StatusBadge>
              )}
              {route.approval_revoked && (
                <StatusBadge tone="warning" dot={false}>
                  Одобрение вида отозвано
                </StatusBadge>
              )}
              {route.error_code && <span className="mono text-xs text-danger">{route.error_code}</span>}
            </span>
            <span className="text-xs text-muted [overflow-wrap:anywhere]">
              {formatTime(route.created_at)}
              {route.floor_elevation_mm !== null || route.floor_height_mm !== null
                ? ` · запрос: пол ${route.floor_elevation_mm ?? 'по документации'} · этаж ${route.floor_height_mm ?? 'по документации'}`
                : ' · отметки по документации'}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
};
