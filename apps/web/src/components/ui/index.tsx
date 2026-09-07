/**
 * Примитивы интерфейса.
 *
 * Общие переехали в `@quantor/ui`: потребителей стало два (ADR-0001). Здесь остаётся
 * то, что принадлежит порталу, и реэкспорт — чтобы два десятка мест импорта не менялись
 * ради переноса, не меняющего поведение.
 */

import type { ReactNode } from 'react';

export * from '@quantor/ui';

/* --------------------------------------------------------- секция инспектора */

interface IInspectorSectionProps {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}

export const InspectorSection = ({ title, aside, children }: IInspectorSectionProps) => (
  <section className="border-t border-border pt-[var(--s-5)] first:border-t-0 first:pt-0">
    <h3 className="mb-[var(--s-4)] flex items-center gap-[var(--s-3)] text-micro font-semibold tracking-[0.06em] text-muted uppercase">
      {title}
      {aside}
    </h3>
    {children}
  </section>
);

/** Пара «подпись — значение». Значение моноширинное: это данные, а не текст. */
export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-xs text-muted">{label}</dt>
    <dd className="mono m-0 text-xs break-words">{children}</dd>
  </>
);
