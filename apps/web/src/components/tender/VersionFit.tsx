import type { FC } from 'react';

/**
 * Привязка тендерных координат к кадру вида (`fit` манифеста): метод, оси, rms и максимум в мм.
 * Поля приходят свободным объектом, поэтому каждое читается с проверкой типа.
 */

interface IFitProps {
  readonly fit: readonly Readonly<Record<string, unknown>>[];
}

const text = (value: unknown): string | null =>
  typeof value === 'string' || typeof value === 'number' ? String(value) : null;

const mm = (value: unknown): string => (typeof value === 'number' ? `${value} мм` : '—');

const axes = (value: unknown): string =>
  Array.isArray(value) ? value.map((axis) => String(axis)).join(', ') : '—';

export const VersionFit: FC<IFitProps> = ({ fit }) => {
  if (fit.length === 0) return <p className="m-0 text-sm text-muted">Привязка не указана.</p>;

  return (
    <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
      {fit.map((entry, index) => (
        <li
          key={text(entry.view_key) ?? index}
          className="flex flex-wrap items-baseline gap-x-[var(--s-6)] gap-y-[var(--s-2)] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-3)] text-sm"
        >
          <span className="mono text-xs [overflow-wrap:anywhere]">
            {text(entry.view_key) ?? '—'}
          </span>
          <span className="text-muted">{text(entry.method) ?? '—'}</span>
          <span>оси: {axes(entry.axes)}</span>
          <span className="tabular">rms {mm(entry.rms_mm)}</span>
          <span className="tabular">max {mm(entry.max_mm)}</span>
        </li>
      ))}
    </ul>
  );
};
