'use client';

import type { SectionLevelRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, StatusBadge, cx } from '@/components/ui';
import { IconReset } from '@/components/ui/icons';
import {
  canAcceptLevel,
  formatLevelFloor,
  formatLevelHeights,
  formatMark,
  levelDecisionLabel,
} from '@/lib/cad/sections';

import type { IWorkspaceCadSections } from './types';

interface ICadSectionLevelRowProps {
  level: SectionLevelRead;
  active: boolean;
  busy: boolean;
  /** Показать линию разреза в строке: на листе их несколько. */
  showCut?: boolean;
  onSelect: IWorkspaceCadSections['onSelectLevel'];
  onDecide: IWorkspaceCadSections['onDecide'];
}

const TONES = { accepted: 'success', candidate: 'accent', rejected: 'neutral' } as const;

/**
 * Уровень разреза одной строкой: этаж, отметка, высоты, статус и решения человека.
 *
 * Щелчок по строке выделяет уровень и переводит вид листа к его полосе; повторный - снимает
 * выделение. Решения - малые квадратные кнопки справа: строка не растёт ради них.
 */
export const CadSectionLevelRow: FC<ICadSectionLevelRowProps> = ({
  level,
  active,
  busy,
  showCut = false,
  onSelect,
  onDecide,
}) => {
  const acceptable = canAcceptLevel(level);
  const place = `${formatLevelFloor(level)}, ${formatMark(level.elevation_mm)}`;
  return (
    <li
      className={cx(
        'flex min-w-0 items-center gap-[var(--s-2)] rounded-[var(--radius-sm)] border px-[var(--s-2)] py-[var(--s-1)]',
        active ? 'border-accent bg-accent-soft' : 'border-border',
      )}
      data-testid="section-level"
    >
      <button
        type="button"
        aria-pressed={active}
        title="Показать на листе"
        onClick={() => onSelect(active ? null : level.id)}
        className="flex min-h-[32px] min-w-0 flex-1 flex-col items-start justify-center text-left max-md:min-h-[44px]"
      >
        <span className="flex w-full min-w-0 items-center gap-x-[var(--s-2)]">
          <span className="truncate text-xs font-medium">{formatLevelFloor(level)}</span>
          <span className="tabular mono text-xs">{formatMark(level.elevation_mm)}</span>
          {showCut && level.cut !== null && (
            <span className="text-micro text-muted">{level.cut}</span>
          )}
          <span className="ml-auto shrink-0">
            <StatusBadge tone={TONES[level.status]}>{levelDecisionLabel(level)}</StatusBadge>
          </span>
        </span>
        <span className="text-micro text-muted [overflow-wrap:anywhere]">
          {formatLevelHeights(level)}
          {' · '}до {formatMark(level.upper_elevation_mm)}
        </span>
      </button>
      <div className="flex shrink-0 gap-[var(--s-1)]">
        {level.status !== 'accepted' && (
          <Button
            compact
            iconOnly
            variant="primary"
            aria-label={`Принять: ${place}`}
            title={acceptable ? 'Принять' : 'Высота в свету не определена или вне 1500-6000 мм'}
            disabled={busy || !acceptable}
            onClick={() => onDecide([level.id], 'accept')}
          >
            <span aria-hidden="true">✓</span>
          </Button>
        )}
        {level.status !== 'rejected' && (
          <Button
            compact
            iconOnly
            aria-label={`Отклонить: ${place}`}
            title="Отклонить"
            disabled={busy}
            onClick={() => onDecide([level.id], 'reject')}
          >
            <span aria-hidden="true">✕</span>
          </Button>
        )}
        {level.status !== 'candidate' && (
          <Button
            compact
            iconOnly
            variant="ghost"
            aria-label={`Вернуть в кандидаты: ${place}`}
            title="Вернуть в кандидаты"
            disabled={busy}
            onClick={() => onDecide([level.id], 'reset')}
          >
            <IconReset />
          </Button>
        )}
      </div>
    </li>
  );
};
