'use client';

import type { FC, MouseEvent } from 'react';

import { cx } from '@/components/ui';

export interface ISheetTab {
  /** Позиция листа в ревизии, с единицы - как в параметре `page`. */
  position: number;
  /** Этаж из заголовка плана; нет - пусто, вкладка подписана номером листа. */
  floorTitle: string;
  /** Полный заголовок плана для подсказки. */
  fullTitle: string | null;
  /** «Лист 3» или метка листа из пакета. */
  sheetLabel: string;
}

/** Масштаб чертежа по центру панели: число «1:N», откуда оно, и масштаб вида. */
export interface ISheetScale {
  /** «1:100»; масштаб не задан - null. */
  text: string | null;
  /** Откуда масштаб, словами - для подсказки и подписи. */
  source: string | null;
  zoomPercent: number;
}

interface ISheetTabsProps {
  tabs: readonly ISheetTab[];
  active: number | null;
  onActivate: (position: number) => void;
  onClose: (position: number) => void;
  scale: ISheetScale;
}

/** Средняя кнопка по вкладке закрывает её, как в браузере; автопрокрутку колесом гасим. */
const suppressAutoscroll = (event: MouseEvent) => {
  if (event.button === 1) event.preventDefault();
};

/**
 * Вкладки открытых листов и масштаб по центру над чертежом.
 *
 * Масштаб стоит в средней колонке сетки, вкладки - в левой: сколько бы листов ни было открыто,
 * число остаётся на месте, а лишние вкладки прокручиваются.
 */
export const SheetTabs: FC<ISheetTabsProps> = ({ tabs, active, onActivate, onClose, scale }) => {
  const closable = tabs.length > 1;

  return (
    <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-stretch">
      <div
        role="tablist"
        aria-label="Открытые листы"
        className="scroll-area flex min-w-0 items-stretch overflow-x-auto overflow-y-hidden"
      >
        {tabs.length === 0 && (
          <span className="flex items-center whitespace-nowrap border-r border-border px-[var(--s-5)] text-xs text-muted">
            Лист не выбран
          </span>
        )}
        {tabs.map((tab) => {
          const selected = tab.position === active;
          return (
            <div
              key={tab.position}
              className={cx(
                'group flex flex-none items-stretch border-r border-border text-xs',
                selected
                  ? 'bg-surface-muted shadow-[inset_0_-2px_0_var(--accent)]'
                  : 'text-muted hover:bg-surface-muted hover:text-text',
              )}
            >
              <button
                type="button"
                role="tab"
                aria-selected={selected}
                title={
                  [tab.fullTitle, closable ? 'средняя кнопка — закрыть' : null]
                    .filter(Boolean)
                    .join(' · ') || undefined
                }
                onClick={() => onActivate(tab.position)}
                onMouseDown={suppressAutoscroll}
                onAuxClick={(event) => {
                  if (event.button !== 1 || !closable) return;
                  event.preventDefault();
                  onClose(tab.position);
                }}
                className={cx(
                  'flex max-w-[260px] items-center gap-[var(--s-3)] whitespace-nowrap',
                  closable ? 'pl-[var(--s-5)] pr-[var(--s-2)]' : 'px-[var(--s-5)]',
                )}
              >
                {tab.floorTitle !== '' && (
                  <span className={cx('min-w-0 truncate', selected && 'font-medium')}>
                    {tab.floorTitle}
                  </span>
                )}
                <span
                  className={cx(
                    'flex-none',
                    tab.floorTitle !== '' ? 'text-muted' : selected && 'font-medium',
                  )}
                >
                  {tab.sheetLabel}
                </span>
              </button>
              {closable && (
                <button
                  type="button"
                  aria-label={`Закрыть вкладку: ${tab.sheetLabel}`}
                  title="Закрыть вкладку"
                  onClick={() => onClose(tab.position)}
                  className={cx(
                    'my-auto mr-[var(--s-3)] grid h-[18px] w-[18px] place-items-center rounded-[var(--radius-xs)] text-sm leading-none text-muted hover:bg-surface hover:text-text',
                    !selected && 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                  )}
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div
        data-testid="sheet-scale"
        className="flex items-center justify-center gap-[var(--s-3)] whitespace-nowrap px-[var(--s-5)] text-xs"
        title={
          scale.text
            ? `Масштаб чертежа ${scale.text}${scale.source ? ` — ${scale.source}` : ''}; масштаб вида ${scale.zoomPercent} %`
            : `Масштаб чертежа не задан; масштаб вида ${scale.zoomPercent} %`
        }
      >
        {/* Один кегль и одна базовая линия: подпись источника мельче кегля съезжала вверх. */}
        <span className="flex items-baseline gap-[var(--s-3)] leading-none">
          <span className="text-muted">Масштаб</span>
          <span className={cx('tabular font-medium', !scale.text && 'text-muted')}>
            {scale.text ?? 'не задан'}
          </span>
          {scale.source && <span className="text-muted">{scale.source}</span>}
        </span>
        <span aria-hidden="true" className="h-[12px] w-px flex-none bg-border-strong" />
        <span className="tabular leading-none text-muted">вид {scale.zoomPercent} %</span>
      </div>

      <div aria-hidden="true" />
    </div>
  );
};
