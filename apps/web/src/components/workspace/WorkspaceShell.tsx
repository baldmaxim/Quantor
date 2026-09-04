'use client';

import { useRef, type ReactNode } from 'react';

import { cx } from '@/components/ui';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import { Splitter } from '@/components/workspace/Splitter';
import { PANE_LIMITS, useWorkspaceStore } from '@/store/workspace';

/**
 * Каркас рабочей области: три ряда хрома и три колонки под ними.
 *
 * ```text
 * ┌──────────────────────────────────────────────┐ вкладки листов и путь
 * ├──────────────────────────────────────────────┤ инструменты
 * │ панель │ чертёж              │ инспектор     │
 * ├──────────────────────────────────────────────┤ статусная строка
 * ```
 *
 * Центр принимает содержимое слотом: просмотрщик встанет сюда в промте 07, не трогая
 * раскладку. Ширины панелей во время перетаскивания идут в CSS-переменные контейнера
 * мимо состояния React — иначе каждое движение мыши перерисовывает обе панели.
 */

interface IWorkspaceShellProps {
  tabs: ReactNode;
  toolbar: ReactNode;
  /** Подпись над левой панелью — обычно название открытого документа. */
  leftTitle: ReactNode;
  left: ReactNode;
  center: ReactNode;
  rightTitle: ReactNode;
  right: ReactNode;
  status: ReactNode;
}

/** Ширина свёрнутой панели: остаётся полоса с кнопкой разворачивания. */
const COLLAPSED_WIDTH = 30;

export const WorkspaceShell = ({
  tabs,
  toolbar,
  leftTitle,
  left,
  center,
  rightTitle,
  right,
  status,
}: IWorkspaceShellProps) => {
  const container = useRef<HTMLDivElement>(null);

  const leftWidth = useWorkspaceStore((state) => state.leftWidth);
  const rightWidth = useWorkspaceStore((state) => state.rightWidth);
  const leftCollapsed = useWorkspaceStore((state) => state.leftCollapsed);
  const rightCollapsed = useWorkspaceStore((state) => state.rightCollapsed);
  const setLeftWidth = useWorkspaceStore((state) => state.setLeftWidth);
  const setRightWidth = useWorkspaceStore((state) => state.setRightWidth);
  const toggleLeft = useWorkspaceStore((state) => state.toggleLeft);
  const toggleRight = useWorkspaceStore((state) => state.toggleRight);

  const style: Record<string, string> = {};
  if (leftWidth !== null) style['--pane-left'] = `${leftWidth}px`;
  if (rightWidth !== null) style['--pane-right'] = `${rightWidth}px`;

  return (
    <div
      ref={container}
      className="grid min-h-0 flex-1 grid-rows-[var(--h-ws-tabs)_var(--h-ws-toolbar)_1fr_var(--h-ws-status)] bg-surface-sunken text-text"
      style={style}
    >
      <div className="flex min-w-0 items-stretch border-b border-border-strong bg-surface">
        {tabs}
      </div>

      <div className="flex min-w-0 items-center gap-[var(--s-2)] border-b border-border-strong bg-surface px-[var(--s-4)]">
        {toolbar}
      </div>

      <div className="flex min-h-0 min-w-0">
        <Pane
          side="left"
          collapsed={leftCollapsed}
          onToggle={toggleLeft}
          label="Панель документов и распознавания"
          title={leftTitle}
          width={leftWidth ?? undefined}
          variable="--pane-left"
          fallback="var(--w-pane-left)"
        >
          {left}
        </Pane>

        {!leftCollapsed && (
          <Splitter
            side="left"
            label="Ширина левой панели"
            width={leftWidth ?? PANE_LIMITS.MIN_LEFT + 64}
            min={PANE_LIMITS.MIN_LEFT}
            max={PANE_LIMITS.MAX_LEFT}
            previewTarget={container}
            previewVariable="--pane-left"
            onResize={setLeftWidth}
          />
        )}

        <main className="relative min-h-0 min-w-0 flex-1 bg-canvas-well">{center}</main>

        {!rightCollapsed && (
          <Splitter
            side="right"
            label="Ширина панели свойств"
            width={rightWidth ?? PANE_LIMITS.MIN_RIGHT + 60}
            min={PANE_LIMITS.MIN_RIGHT}
            max={PANE_LIMITS.MAX_RIGHT}
            previewTarget={container}
            previewVariable="--pane-right"
            onResize={setRightWidth}
          />
        )}

        <Pane
          side="right"
          collapsed={rightCollapsed}
          onToggle={toggleRight}
          label="Панель свойств"
          title={rightTitle}
          width={rightWidth ?? undefined}
          variable="--pane-right"
          fallback="var(--w-pane-right)"
        >
          {right}
        </Pane>
      </div>

      <div className="flex items-center gap-[var(--s-6)] border-t border-border-strong bg-surface px-[var(--s-5)] text-micro text-muted">
        {status}
      </div>
    </div>
  );
};

interface IPaneProps {
  side: 'left' | 'right';
  collapsed: boolean;
  onToggle: () => void;
  label: string;
  title: ReactNode;
  width: number | undefined;
  variable: string;
  fallback: string;
  children: ReactNode;
}

const Pane = ({
  side,
  collapsed,
  onToggle,
  label,
  title,
  width,
  variable,
  fallback,
  children,
}: IPaneProps) => {
  const Chevron = side === 'left' ? IconChevronLeft : IconChevronRight;

  if (collapsed) {
    return (
      <aside
        aria-label={`${label} (свёрнута)`}
        className={cx(
          'flex flex-none flex-col items-center bg-surface py-[var(--s-4)]',
          side === 'left' ? 'border-r border-border-strong' : 'border-l border-border-strong',
        )}
        style={{ width: COLLAPSED_WIDTH }}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded="false"
          title={`Развернуть: ${label}`}
          className="grid h-[22px] w-[22px] place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text"
        >
          <Chevron
            width={14}
            height={14}
            className={side === 'left' ? 'rotate-180' : '-rotate-180'}
          />
        </button>
      </aside>
    );
  }

  return (
    <aside
      aria-label={label}
      className={cx(
        'flex min-h-0 flex-none flex-col bg-surface',
        side === 'left' ? 'border-r border-border-strong' : 'border-l border-border-strong',
      )}
      style={{ width: width !== undefined ? `var(${variable}, ${fallback})` : fallback }}
    >
      <div className="flex flex-none items-center gap-[var(--s-3)] border-b border-border px-[var(--s-4)] py-[var(--s-3)]">
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{title}</span>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded="true"
          title={`Свернуть: ${label}`}
          className="grid h-[20px] w-[20px] flex-none place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text"
        >
          <Chevron width={14} height={14} />
        </button>
      </div>
      {children}
    </aside>
  );
};
