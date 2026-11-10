'use client';

import { useRef, useState, type FC, type KeyboardEvent, type ReactNode } from 'react';

import { Button, cx } from '@/components/ui';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import { useStoredFlag } from '@/lib/cad/useStoredFlag';

export interface ICadSideTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface ICadSidePanelProps {
  /** Доступное имя панели. */
  label: string;
  tabs: readonly ICadSideTab[];
  /** Ключ localStorage, под которым хранится «свёрнута». */
  storageKey: string;
  /** Открытый раздел снаружи: так он переживает пересоздание панели при смене вида. */
  active?: string;
  onActiveChange?: (id: string) => void;
}

const TAB_BASE =
  'min-h-[44px] shrink-0 px-[var(--s-5)] text-sm whitespace-nowrap transition-colors';

/**
 * Боковая панель вида с вкладками. Все вкладки смонтированы, неактивные скрыты: состояние
 * разделов (черновик замечания, ход задания) не теряется при переключении.
 *
 * Свёртывание действует только на широком экране (от 1024 px): на узком панель идёт под
 * холстом обычным потоком и всегда видна. Состояние хранится в localStorage.
 */
export const CadSidePanel: FC<ICadSidePanelProps> = ({
  label,
  tabs,
  storageKey,
  active,
  onActiveChange,
}) => {
  const [inner, setInner] = useState(tabs[0]?.id ?? '');
  const [collapsed, setCollapsed] = useStoredFlag(storageKey);
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
    <>
      <aside
        aria-label={label}
        data-collapsed={collapsed}
        className={cx(
          'flex min-w-0 flex-col rounded-[var(--radius-md)] border border-border-strong bg-surface',
          'lg:min-h-0 lg:w-[clamp(300px,26vw,440px)] lg:flex-none',
          collapsed && 'lg:hidden',
        )}
      >
        <div className="flex border-b border-border">
          <div
            role="tablist"
            aria-label={`${label}: разделы`}
            className="scroll-area flex min-w-0 flex-1 overflow-x-auto overscroll-x-contain"
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
          <Button
            iconOnly
            variant="ghost"
            onClick={() => setCollapsed(true)}
            aria-expanded="true"
            aria-label="Свернуть боковую панель"
            title="Свернуть боковую панель"
            className="max-lg:hidden"
          >
            <IconChevronRight width={16} height={16} />
          </Button>
        </div>

        {tabs.map((tab) => (
          <div
            key={tab.id}
            role="tabpanel"
            id={`cad-side-panel-${tab.id}`}
            aria-labelledby={`cad-side-tab-${tab.id}`}
            hidden={tab.id !== current}
            className="min-h-0 min-w-0 flex-1 p-[var(--s-5)] lg:overflow-auto lg:overscroll-contain"
          >
            {tab.content}
          </div>
        ))}
      </aside>

      {collapsed && (
        <div
          data-testid="cad-side-collapsed"
          className="hidden flex-none flex-col items-center rounded-[var(--radius-md)] border border-border-strong bg-surface py-[var(--s-3)] lg:flex"
        >
          <Button
            iconOnly
            variant="ghost"
            onClick={() => setCollapsed(false)}
            aria-expanded="false"
            aria-label="Показать боковую панель"
            title="Показать боковую панель"
          >
            <IconChevronLeft width={16} height={16} />
          </Button>
        </div>
      )}
    </>
  );
};
