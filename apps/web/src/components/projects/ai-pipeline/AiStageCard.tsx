'use client';

import type { AiStageSummary } from '@quantor/api-client';
import type { FC, ReactNode } from 'react';

import { cx, StatusBadge } from '@/components/ui';
import { IconChevronRight } from '@/components/ui/icons';

import { costText, stageBadge, stageProgressText } from './aiPipelineView';

/** Карточка одного этапа: номер, название, «N из M листов», бейдж, расход, действия и раскрытие. */

export interface IAiStageCardProps {
  readonly stage: AiStageSummary;
  readonly expanded: boolean;
  readonly panelId: string;
  readonly onToggle: () => void;
  readonly actions?: ReactNode;
}

export const AiStageCard: FC<IAiStageCardProps> = ({
  stage,
  expanded,
  panelId,
  onToggle,
  actions,
}) => {
  const badge = stageBadge(stage);
  const cost = costText(stage);
  return (
    <li
      data-testid={`ai-stage-${stage.stage}`}
      className="flex min-w-0 flex-1 flex-col gap-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-3)] last:border-b-0 md:border-r md:border-b-0 md:last:border-r-0"
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={onToggle}
        className="flex min-h-[44px] w-full items-center gap-[var(--s-3)] text-left"
      >
        <IconChevronRight
          className={cx(
            'flex-none text-muted transition-transform duration-150 motion-reduce:transition-none',
            expanded && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-xs text-muted">Этап {stage.stage}</span>
          <span className="block text-sm font-medium [overflow-wrap:anywhere]">{stage.title}</span>
        </span>
      </button>
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>
        <span className="text-xs text-muted">{stageProgressText(stage)}</span>
      </div>
      {cost && <p className="m-0 text-xs text-muted">Расход Claude: {cost}</p>}
      {actions}
    </li>
  );
};
