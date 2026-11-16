'use client';

import type { FC, ReactNode } from 'react';

import { Button, StatusBadge, type BadgeTone } from '@/components/ui';
import { FINISH_STEP_STATUS_LABELS, type FinishStepStatus } from '@/lib/cad/finish-steps';

export interface ICadFinishStepAction {
  label: string;
  onClick: () => void;
}

interface ICadFinishStepProps {
  /** Порядковый номер шага в чек-листе. */
  number: number;
  title: string;
  status: FinishStepStatus;
  /** Строка-итог цифрами. */
  summary: string;
  /** Что сделать; показывается, пока шаг не готов. */
  hint?: string | null;
  action?: ICadFinishStepAction | null;
  children?: ReactNode;
}

const TONES: Readonly<Record<FinishStepStatus, BadgeTone>> = {
  ready: 'success',
  action: 'warning',
  neutral: 'neutral',
};

/** Шаг чек-листа отделки: номер и заголовок, бейдж состояния, итог, подсказка, действие. */
export const CadFinishStep: FC<ICadFinishStepProps> = ({
  number,
  title,
  status,
  summary,
  hint = null,
  action = null,
  children,
}) => (
  <section
    aria-label={`Шаг ${number}. ${title}`}
    data-status={status}
    className="flex min-w-0 flex-col gap-[var(--s-2)] border-t border-border pt-[var(--s-3)]"
  >
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-[var(--s-2)]">
      <h4 className="min-w-0 text-sm font-semibold break-words">
        {number}. {title}
      </h4>
      <StatusBadge tone={TONES[status]}>{FINISH_STEP_STATUS_LABELS[status]}</StatusBadge>
    </div>
    <p className="text-xs break-words text-muted">{summary}</p>
    {status === 'action' && hint !== null && <p className="text-xs break-words">{hint}</p>}
    {children}
    {status === 'action' && action !== null && (
      <Button compact className="self-start max-md:h-[44px]" onClick={action.onClick}>
        {action.label}
      </Button>
    )}
  </section>
);
