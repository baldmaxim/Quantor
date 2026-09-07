import { StatusBadge, type BadgeTone } from '@quantor/ui';
import type { ReactNode } from 'react';

/**
 * Плитка состояния.
 *
 * Правило одно и оно важнее вида: неизвестное показывается неизвестным. Ни ноль, ни
 * «в порядке» вместо «не знаю» — по этой панели принимают решения, и правдоподобная
 * цифра хуже прочерка.
 */
export const Tile = ({
  label,
  value,
  tone,
  badge,
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: BadgeTone;
  badge?: string;
  hint?: ReactNode;
}) => (
  <div className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface p-[var(--s-5)]">
    <span className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">{label}</span>
    <span className="text-md font-medium wrap-anywhere">{value}</span>
    {badge && <StatusBadge tone={tone ?? 'neutral'}>{badge}</StatusBadge>}
    {hint && <span className="text-xs text-muted">{hint}</span>}
  </div>
);
