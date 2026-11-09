'use client';

import type { CadAttemptRead } from '@quantor/api-client';
import type { FC } from 'react';

import { cx } from '@/components/ui';
import { outcomeLabel } from '@/lib/cad/stages';

interface ICadAttemptSwitcherProps {
  attempts: readonly CadAttemptRead[];
  selected: number;
  onSelect: (attempt: number) => void;
}

/** История попыток задания: каждая со своим исходом и кодом отказа. */
export const CadAttemptSwitcher: FC<ICadAttemptSwitcherProps> = ({
  attempts,
  selected,
  onSelect,
}) => {
  if (attempts.length < 2) {
    return null;
  }

  return (
    <div role="group" aria-label="Попытки задания" className="flex flex-wrap gap-[var(--s-3)]">
      {attempts.map((attempt) => {
        const active = attempt.attempt === selected;
        return (
          <button
            key={attempt.attempt}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(attempt.attempt)}
            className={cx(
              'flex min-h-[44px] flex-col items-start justify-center rounded-[var(--radius-sm)] border px-[var(--s-5)] py-[var(--s-2)] text-left text-xs',
              active
                ? 'border-accent bg-accent-soft text-text'
                : 'border-border-control text-muted hover:bg-surface-muted hover:text-text',
            )}
          >
            <span className="font-medium">Попытка {attempt.attempt}</span>
            <span>
              {outcomeLabel(attempt.outcome)}
              {attempt.error_code && (
                <span className="mono text-danger"> · {attempt.error_code}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
};
