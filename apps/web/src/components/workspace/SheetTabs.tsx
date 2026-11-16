'use client';

import { useEffect, useRef, type FC, type MouseEvent, type WheelEvent } from 'react';

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

interface ISheetTabsProps {
  tabs: readonly ISheetTab[];
  active: number | null;
  onActivate: (position: number) => void;
  onClose: (position: number) => void;
}

/** Средняя кнопка по вкладке закрывает её, как в браузере; автопрокрутку колесом гасим. */
const suppressAutoscroll = (event: MouseEvent) => {
  if (event.button === 1) event.preventDefault();
};

/**
 * Вкладки открытых листов.
 *
 * Как в браузере: вкладки сжимаются до минимальной ширины, подпись этажа обрезается, номер листа
 * виден всегда. Не поместившиеся вкладки прокручиваются колесом, без полосы прокрутки - она
 * съедала высоту ряда. Активная вкладка прокручивается в видимую часть.
 */
export const SheetTabs: FC<ISheetTabsProps> = ({ tabs, active, onActivate, onClose }) => {
  const strip = useRef<HTMLDivElement>(null);
  const closable = tabs.length > 1;

  useEffect(() => {
    strip.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [active, tabs.length]);

  // Вертикальное колесо листает вкладки по горизонтали: другой прокрутки у ряда нет.
  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    const node = strip.current;
    if (!node || event.deltaY === 0 || node.scrollWidth <= node.clientWidth) return;
    node.scrollLeft += event.deltaY;
  };

  return (
    <div
      ref={strip}
      role="tablist"
      aria-label="Открытые листы"
      onWheel={onWheel}
      className="flex min-w-0 flex-1 items-stretch overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
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
              'group flex min-w-[112px] flex-[0_1_240px] items-stretch border-r border-border text-xs',
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
                [tab.fullTitle ?? tab.floorTitle, tab.sheetLabel, closable ? 'средняя кнопка — закрыть' : null]
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
                'flex min-w-0 flex-1 items-center gap-[var(--s-3)] whitespace-nowrap',
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
                  'my-auto mr-[var(--s-3)] grid h-[18px] w-[18px] flex-none place-items-center rounded-[var(--radius-xs)] text-sm leading-none text-muted hover:bg-surface hover:text-text',
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
  );
};
