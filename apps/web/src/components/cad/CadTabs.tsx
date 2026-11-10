'use client';

import { useRef, type KeyboardEvent, type ReactElement, type ReactNode } from 'react';

import { cx } from '@/components/ui';

export interface ICadTab<TId extends string> {
  id: TId;
  label: string;
}

interface ICadTabsProps<TId extends string> {
  /** Префикс для `id` вкладок и панели: связывает aria-controls и aria-labelledby. */
  idPrefix: string;
  label: string;
  tabs: readonly ICadTab<TId>[];
  active: TId;
  onChange: (id: TId) => void;
  /** Содержимое активной вкладки; неактивные не рендерятся. */
  children: ReactNode;
}

/** Карточка с вкладками: переключение стрелками, тап-цели не ниже 44 px. */
export const CadTabs = <TId extends string>({
  idPrefix,
  label,
  tabs,
  active,
  onChange,
  children,
}: ICadTabsProps<TId>): ReactElement => {
  const refs = useRef(new Map<TId, HTMLButtonElement>());

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (next) {
      onChange(next.id);
      refs.current.get(next.id)?.focus();
    }
  };

  return (
    <section className="flex flex-col rounded-[var(--radius-md)] border border-border-strong bg-surface">
      <div role="tablist" aria-label={label} className="flex border-b border-border">
        {tabs.map((tab, index) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                if (node) refs.current.set(tab.id, node);
                else refs.current.delete(tab.id);
              }}
              type="button"
              role="tab"
              id={`${idPrefix}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${idPrefix}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={cx(
                'min-h-[44px] flex-1 px-[var(--s-5)] text-sm transition-colors',
                selected
                  ? 'font-medium text-text shadow-[inset_0_-2px_0_var(--accent)]'
                  : 'text-muted hover:text-text',
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${idPrefix}-panel-${active}`}
        aria-labelledby={`${idPrefix}-tab-${active}`}
        className="flex flex-col p-[var(--s-6)]"
      >
        {children}
      </div>
    </section>
  );
};
