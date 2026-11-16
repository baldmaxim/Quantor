'use client';

import type { TenderCalcRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { formatWhen } from '@/lib/format';
import { systemLabel } from '@/lib/tender/systems';

import { SystemSwatch } from './SystemSwatch';

/**
 * Карточка репозитория расчёта: система, название, последняя действующая версия, автор, дата,
 * выпуск базы, предупреждения. «Новая база» — после версии вышел более свежий выпуск базы объекта.
 */

interface ICardProps {
  readonly calc: TenderCalcRead;
  /** Номер последнего действующего выпуска базы проекта; 0 — выпусков нет. */
  readonly latestRelease: number;
  readonly onOpen: () => void;
}

export const CalcCard: FC<ICardProps> = ({ calc, latestRelease, onOpen }) => {
  const version = calc.active_version;
  const newerBase = version !== null && latestRelease > version.base_release_number;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="press flex min-h-[44px] w-full flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)] text-left hover:border-accent"
    >
      <span className="flex items-center gap-[var(--s-3)] text-xs text-muted">
        <SystemSwatch system={calc.system} />
        {systemLabel(calc.system)}
      </span>
      <span className="text-base font-semibold [overflow-wrap:anywhere]">{calc.title}</span>
      {version ? (
        <>
          <span className="tabular text-sm">
            №{version.number} · {version.label}
          </span>
          <span className="text-xs text-muted">
            {version.author} · {formatWhen(version.uploaded_at)}
          </span>
          <span className="flex flex-wrap items-center gap-[var(--s-3)]">
            <span className="tabular text-xs text-muted">база #{version.base_release_number}</span>
            {newerBase && <StatusBadge tone="warning">новая база #{latestRelease}</StatusBadge>}
            {version.warning_count > 0 && (
              <StatusBadge tone="warning">предупреждений: {version.warning_count}</StatusBadge>
            )}
            {version.question_count > 0 && (
              <StatusBadge tone="neutral">вопросов: {version.question_count}</StatusBadge>
            )}
          </span>
        </>
      ) : (
        <span className="text-sm text-muted">Действующей версии нет: все отозваны.</span>
      )}
      <span className="tabular text-xs text-muted">версий: {calc.version_count}</span>
    </button>
  );
};
