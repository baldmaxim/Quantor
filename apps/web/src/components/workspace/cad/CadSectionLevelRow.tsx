'use client';

import type { SectionLevelRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, StatusBadge, cx } from '@/components/ui';
import {
  canAcceptLevel,
  formatLevelFloor,
  formatLevelHeights,
  formatMark,
  levelStatusLabel,
} from '@/lib/cad/sections';

import type { IWorkspaceCadSections } from './types';

interface ICadSectionLevelRowProps {
  level: SectionLevelRead;
  active: boolean;
  busy: boolean;
  onSelect: IWorkspaceCadSections['onSelectLevel'];
  onDecide: IWorkspaceCadSections['onDecide'];
}

const TONES = { accepted: 'success', candidate: 'accent', rejected: 'neutral' } as const;

const ACTION = 'min-h-[44px] flex-1 max-md:h-[44px]';

/** Уровень разреза: этаж, отметка, высоты, статус и решения человека. */
export const CadSectionLevelRow: FC<ICadSectionLevelRowProps> = ({
  level,
  active,
  busy,
  onSelect,
  onDecide,
}) => {
  const acceptable = canAcceptLevel(level);
  return (
    <li
      className={cx(
        'flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border p-[var(--s-3)]',
        active ? 'border-accent bg-accent-soft' : 'border-border',
      )}
      data-testid="section-level"
    >
      <button
        type="button"
        aria-pressed={active}
        onClick={() => onSelect(active ? null : level.id)}
        className="flex min-h-[44px] min-w-0 flex-col items-start gap-[var(--s-1)] text-left"
      >
        <span className="flex w-full min-w-0 flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-1)]">
          <span className="text-sm font-medium">{formatLevelFloor(level)}</span>
          <span className="tabular mono text-sm">{formatMark(level.elevation_mm)}</span>
          <span className="ml-auto">
            <StatusBadge tone={TONES[level.status]}>{levelStatusLabel(level.status)}</StatusBadge>
          </span>
        </span>
        <span className="text-xs text-muted [overflow-wrap:anywhere]">
          {formatLevelHeights(level)}
          {' · '}до {formatMark(level.upper_elevation_mm)}
        </span>
      </button>
      <div className="flex min-w-0 flex-wrap gap-[var(--s-2)]">
        {level.status !== 'accepted' && (
          <Button
            compact
            variant="primary"
            className={ACTION}
            disabled={busy || !acceptable}
            title={acceptable ? undefined : 'Высота в свету не определена или вне 1500-6000 мм'}
            onClick={() => onDecide([level.id], 'accept')}
          >
            Принять
          </Button>
        )}
        {level.status !== 'rejected' && (
          <Button
            compact
            className={ACTION}
            disabled={busy}
            onClick={() => onDecide([level.id], 'reject')}
          >
            Отклонить
          </Button>
        )}
        {level.status !== 'candidate' && (
          <Button
            compact
            variant="ghost"
            className={ACTION}
            disabled={busy}
            onClick={() => onDecide([level.id], 'reset')}
          >
            Сбросить
          </Button>
        )}
      </div>
    </li>
  );
};
