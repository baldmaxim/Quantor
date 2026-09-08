import type { ReactNode } from 'react';

/**
 * Заголовок раздела: название, пояснение и место под действия.
 *
 * Пояснение обязательно. Раздел администрирования без объяснения, что он меняет,
 * заставляет догадываться — а догадки в контуре управления стоят дорого.
 */
export const Section = ({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) => (
  <section className="flex flex-col gap-[var(--s-6)]">
    <header className="flex flex-wrap items-start justify-between gap-[var(--s-4)]">
      <div className="flex max-w-[70ch] flex-col gap-[var(--s-2)]">
        <h1 className="text-lg font-semibold tracking-[-0.01em]">{title}</h1>
        <p className="text-sm text-muted">{description}</p>
      </div>
      {actions}
    </header>
    {children}
  </section>
);
