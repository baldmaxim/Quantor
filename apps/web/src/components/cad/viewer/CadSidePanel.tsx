'use client';

import { useRef, useState, type FC, type KeyboardEvent, type ReactNode } from 'react';

import { cx } from '@/components/ui';

export interface ICadSideTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface ICadSidePanelProps {
  /** Доступное имя панели. */
  label: string;
  tabs: readonly ICadSideTab[];
  /** Открытый раздел снаружи: так он переживает пересоздание панели при смене вида. */
  active?: string;
  onActiveChange?: (id: string) => void;
}

const TAB_BASE =
  'min-h-[44px] shrink-0 px-[var(--s-5)] text-sm whitespace-nowrap transition-colors';

/**
 * Разделы панели вида CAD. Все вкладки смонтированы, неактивные скрыты: состояние разделов
 * (черновик замечания, ход задания) не теряется при переключении.
 *
 * Рамки, ширины и сворачивания у панели нет: она стоит в правой панели рабочей области, а её
 * ширину и свёртывание ведёт каркас рабочей области.
 */
export const CadSidePanel: FC<ICadSidePanelProps> = ({
  label,
  tabs,
  active,
  onActiveChange,
}) => {
  const [inner, setInner] = useState(tabs[0]?.id ?? '');
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const wanted = active ?? inner;
  const current = tabs.some((tab) => tab.id === wanted) ? wanted : (tabs[0]?.id ?? '');
  const setActive = (id: string) => {
    setInner(id);
    onActiveChange?.(id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (next) {
      setActive(next.id);
      refs.current.get(next.id)?.focus();
    }
  };

  return (
    <section aria-label={label} className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div
        role="tablist"
        aria-label={`${label}: разделы`}
        className="scroll-area flex flex-none overflow-x-auto overscroll-x-contain border-b border-border"
      >
        {tabs.map((tab, index) => {
          const selected = tab.id === current;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                if (node) refs.current.set(tab.id, node);
                else refs.current.delete(tab.id);
              }}
              type="button"
              role="tab"
              id={`cad-side-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`cad-side-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(tab.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={cx(
                TAB_BASE,
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

      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`cad-side-panel-${tab.id}`}
          aria-labelledby={`cad-side-tab-${tab.id}`}
          hidden={tab.id !== current}
          className="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain p-[var(--s-5)]"
        >
          {tab.content}
        </div>
      ))}
    </section>
  );
};
