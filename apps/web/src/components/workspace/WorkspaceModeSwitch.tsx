'use client';

import type { FC } from 'react';

import { cx } from '@/components/ui';

export type WorkspaceMode = 'sheets' | 'cad';

interface IWorkspaceModeSwitchProps {
  mode: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
}

const MODES: readonly { id: WorkspaceMode; label: string }[] = [
  { id: 'sheets', label: 'Листы' },
  { id: 'cad', label: 'CAD' },
];

/** Сегментированный переключатель режима рабочей области: «Листы | CAD». */
export const WorkspaceModeSwitch: FC<IWorkspaceModeSwitchProps> = ({ mode, onChange }) => (
  <div
    role="radiogroup"
    aria-label="Режим рабочей области"
    className="flex shrink-0 items-center rounded-md border border-border"
  >
    {MODES.map((item) => {
      const checked = item.id === mode;
      return (
        <button
          key={item.id}
          type="button"
          role="radio"
          aria-checked={checked}
          onClick={() => !checked && onChange(item.id)}
          className={cx(
            'min-h-11 touch-manipulation px-[var(--s-4)] text-xs whitespace-nowrap transition-colors duration-150 first:rounded-l-md last:rounded-r-md motion-reduce:transition-none md:min-h-8',
            checked
              ? 'bg-surface-muted text-text shadow-[inset_0_-2px_0_var(--accent)]'
              : 'text-muted hover:text-text',
          )}
        >
          {item.label}
        </button>
      );
    })}
  </div>
);
