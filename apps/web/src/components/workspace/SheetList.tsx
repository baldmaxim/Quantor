'use client';

import type { CadSheetFloorTitle } from '@quantor/api-client';
import { useEffect, useRef, type FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';

export interface ISheetListPage {
  id: string;
  index: number;
  label: string | null;
  /** Заголовок плана из CAD (корпус, секция, этаж); нет - лист подписан номером. */
  floorTitle?: CadSheetFloorTitle | null;
  /** Название листа из штампа распознавалки; нет штампа - null. */
  title?: string | null;
  regionCount: number;
  /** У листа есть готовый DXF (результат CAD без одной диагностики). */
  cad: boolean;
}

interface ISheetListProps {
  pages: readonly ISheetListPage[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

/**
 * Список листов.
 *
 * Показываются только видимые строки: у документа их 77, и держать в разметке все
 * вместе с миниатюрами значило бы рисовать весь документ ради панели шириной 264 px.
 * Ярлыки справа независимы: «Распознан» — есть регионы, «CAD» — есть готовый DXF.
 * Нет признака — нет ярлыка.
 */
export const SheetList: FC<ISheetListProps> = ({ pages, activeIndex, onSelect }) => {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    container.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  if (pages.length === 0) {
    return <p className="p-[var(--s-4)] text-xs text-muted">Листов пока нет.</p>;
  }

  return (
    <div ref={container} className="flex flex-col py-[var(--s-2)]">
      {pages.map((page) => {
        const recognized = page.regionCount > 0;
        const floorTitle = formatFloorTitle(page.floorTitle, '');
        // Этаж из CAD точнее названия из штампа: штамп показывается, только если этажа нет.
        const caption = floorTitle !== '' ? floorTitle : (page.title ?? '');
        return (
          <button
            key={page.id}
            type="button"
            aria-current={page.index === activeIndex}
            onClick={() => onSelect(page.index)}
            className={cx(
              'flex min-h-[var(--h-row-tree)] items-center gap-[var(--s-3)] px-[var(--s-4)] py-[var(--s-1)] text-left text-xs transition-colors',
              page.index === activeIndex
                ? 'bg-accent-soft text-text'
                : 'text-muted hover:bg-surface-muted hover:text-text',
            )}
          >
            {/* Длинная метка листа обрезается: иначе строка растёт в высоту и теснит ярлыки. */}
            <span
              className="tabular min-w-[28px] max-w-[64px] flex-none truncate"
              title={page.label ?? undefined}
            >
              {page.label ?? page.index + 1}
            </span>
            {/* Номер листа первым, этаж — следом: нумерация в списке не прерывается. */}
            <span
              className="min-w-0 flex-1 truncate"
              title={formatFloorTitleFull(page.floorTitle) ?? page.title ?? undefined}
            >
              Лист {page.index + 1}
              {caption !== '' && <span className="text-text"> · {caption}</span>}
            </span>
            {recognized && (
              <span className="tabular flex-none text-micro text-muted">{page.regionCount}</span>
            )}
            {(recognized || page.cad) && (
              <span className="flex flex-none flex-wrap items-center justify-end gap-[var(--s-2)]">
                {recognized && (
                  <StatusBadge tone="success" dot={false}>
                    Распознан
                  </StatusBadge>
                )}
                {page.cad && (
                  <StatusBadge tone="accent" dot={false}>
                    CAD
                  </StatusBadge>
                )}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};
