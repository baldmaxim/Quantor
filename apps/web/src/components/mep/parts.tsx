'use client';

import type { FC, ReactNode } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { DASH, STYLE_TOKEN, type ShapeStyle } from '@/lib/mep/sheet';
import { ORIGIN_LABEL, type NetworkOrigin } from '@/lib/mep/trace';

/** Кнопка-ссылка на элемент трассировки: идентификатор моноширинный, переход — по клику. */
export const TraceLink: FC<{
  readonly id: string;
  readonly onClick: () => void;
  readonly title?: string;
}> = ({ id, onClick, title }) => (
  <button
    type="button"
    onClick={onClick}
    title={title}
    className="mono press rounded-[var(--radius-xs)] border border-border px-[var(--s-2)] text-xs text-accent hover:bg-accent-soft"
  >
    {id}
  </button>
);

export const TraceLinks: FC<{
  readonly ids: readonly string[];
  readonly onClick: (id: string) => void;
  readonly empty?: string;
}> = ({ ids, onClick, empty = '—' }) =>
  ids.length === 0 ? (
    <span className="text-xs text-muted">{empty}</span>
  ) : (
    <span className="flex flex-wrap gap-[var(--s-2)]">
      {ids.map((id) => (
        <TraceLink key={id} id={id} onClick={() => onClick(id)} />
      ))}
    </span>
  );

const ORIGIN_TONE: Readonly<
  Record<NetworkOrigin, 'accent' | 'warning' | 'danger' | 'success' | 'neutral'>
> = {
  evidence: 'success',
  rule: 'neutral',
  prior: 'warning',
  human: 'neutral',
  unresolved: 'danger',
};

export const OriginBadge: FC<{ readonly origin: NetworkOrigin }> = ({ origin }) => (
  <StatusBadge tone={ORIGIN_TONE[origin]}>{ORIGIN_LABEL[origin]}</StatusBadge>
);

export const ObservedBadge: FC = () => <StatusBadge tone="accent">наблюдено на П</StatusBadge>;

/** Образец штриха легенды: тот же токен и тот же штрих, что на листе. */
export const LegendSwatch: FC<{ readonly style: ShapeStyle; readonly children: ReactNode }> = ({
  style,
  children,
}) => (
  <span className="inline-flex items-center gap-[var(--s-3)] text-xs text-muted">
    <svg aria-hidden="true" width="28" height="8" className="flex-none">
      <line
        x1="1"
        y1="4"
        x2="27"
        y2="4"
        strokeWidth="2.5"
        stroke={`var(${STYLE_TOKEN[style]})`}
        strokeDasharray={DASH[style].join(' ')}
      />
    </svg>
    {children}
  </span>
);

export const Panel: FC<{
  readonly title: string;
  readonly aside?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
}> = ({ title, aside, children, className }) => (
  <section
    className={cx(
      'flex min-w-0 flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)]',
      className,
    )}
  >
    <header className="flex flex-wrap items-center gap-[var(--s-3)]">
      <h2 className="text-sm font-medium">{title}</h2>
      {aside}
    </header>
    {children}
  </section>
);

export const formatConfidence = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? 'нет'
    : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });

export const formatValue = (
  value: boolean | number | string | null,
  unit?: string | null,
): string => {
  if (value === null) return 'не определено';
  const text = typeof value === 'number' ? value.toLocaleString('ru-RU') : String(value);
  return unit ? `${text} ${unit}` : text;
};
