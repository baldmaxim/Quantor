import type { FC } from 'react';

/** Общие классы и подсказка ошибки полей строки реестра стояков. */
export const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
export const SELECT =
  'h-[var(--h-ctl)] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

export const Problem: FC<{ text: string | undefined }> = ({ text }) =>
  text ? (
    <span role="alert" className="text-xs text-danger">
      {text}
    </span>
  ) : null;
