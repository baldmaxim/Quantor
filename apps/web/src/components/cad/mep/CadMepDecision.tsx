'use client';

import type { CadDecisionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { formatTime } from '@/lib/cad/format';

interface ICadMepDecisionProps {
  /** Что решено: «Вид одобрен», «Трассы приняты». */
  title: string;
  decision: CadDecisionRead;
}

/** Решение человека: кто и когда. Решения неизменяемы, отмены нет. */
export const CadMepDecision: FC<ICadMepDecisionProps> = ({ title, decision }) => (
  <div
    className="flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-md)] border border-border-strong bg-surface-muted p-[var(--s-5)]"
    data-testid="mep-decision"
  >
    <p className="text-sm font-medium">{title}</p>
    <p className="text-xs text-muted [overflow-wrap:anywhere]">
      {decision.decided_by_name ?? 'Пользователь без имени'} · {formatTime(decision.decided_at)}
    </p>
    {decision.comment && (
      <p className="text-xs [overflow-wrap:anywhere]">{decision.comment}</p>
    )}
  </div>
);
