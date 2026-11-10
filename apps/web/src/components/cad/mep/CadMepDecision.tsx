'use client';

import type { CadDecisionRead } from '@quantor/api-client';
import type { FC, ReactNode } from 'react';

import { formatTime } from '@/lib/cad/format';

interface ICadMepDecisionProps {
  /** Что решено: «Вид одобрен», «Трассы приняты». */
  title: string;
  decision: CadDecisionRead;
  /** Действия под решением (отзыв). */
  children?: ReactNode;
}

/** Решение человека: кто и когда. Запись не удаляется; отозвать можно (кнопка в `children`). */
export const CadMepDecision: FC<ICadMepDecisionProps> = ({ title, decision, children }) => (
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
    {children}
  </div>
);

interface ICadMepRevokedProps {
  /** Отозванные решения вида, старые сверху. */
  decisions: readonly CadDecisionRead[];
}

/** История отзывов вида: кто и когда решил, кто и когда отозвал, причина. */
export const CadMepRevoked: FC<ICadMepRevokedProps> = ({ decisions }) => {
  if (decisions.length === 0) return null;
  return (
    <details className="min-w-0" data-testid="mep-revoked">
      <summary className="flex min-h-[44px] cursor-pointer items-center text-xs text-muted">
        Отозванные решения ({decisions.length})
      </summary>
      <ul className="flex flex-col gap-[var(--s-3)]" aria-label="Отозванные решения">
        {decisions.map((decision) => (
          <li key={decision.id} className="text-xs [overflow-wrap:anywhere]">
            <span className="block">
              {decision.kind === 'view_approval' ? 'Вид одобрен' : 'Трассы приняты'}:{' '}
              {decision.decided_by_name ?? 'без имени'} · {formatTime(decision.decided_at)}
            </span>
            <span className="block text-muted">
              Отозвано:{' '}
              {decision.revoked_by_name ?? 'без имени'}
              {decision.revoked_at ? ` · ${formatTime(decision.revoked_at)}` : ''}
              {decision.revoke_reason ? ` — ${decision.revoke_reason}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
};
