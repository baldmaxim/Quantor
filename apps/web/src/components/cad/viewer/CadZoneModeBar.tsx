import type { FC, ReactNode } from 'react';

interface ICadZoneModeBarProps {
  /** Что делать в режиме: подсказка одной строкой. */
  hint: string;
  /** Отказ проверки или сервера; режим при этом не закрывается. */
  problem: string | null;
  children: ReactNode;
}

/** Плашка режима правки или разреза поверх холста: подсказка, отказ и кнопки. */
export const CadZoneModeBar: FC<ICadZoneModeBarProps> = ({ hint, problem, children }) => (
  <div
    data-testid="zone-mode-bar"
    className="pointer-events-auto absolute top-[var(--s-3)] right-[var(--s-3)] left-[var(--s-3)] z-20 flex max-w-[560px] min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-4)] shadow-[var(--shadow-sheet)]"
  >
    <p role="status" className="text-xs">
      {hint}
    </p>
    {problem !== null && (
      <p role="alert" className="text-xs text-danger">
        {problem}
      </p>
    )}
    <div className="flex flex-wrap gap-[var(--s-2)]">{children}</div>
  </div>
);
