'use client';

import type { FC } from 'react';

import { cx } from '@/components/ui';

/** Масштаб чертежа: число «1:N», откуда оно, и масштаб вида. */
export interface IDrawingScale {
  /** «1:100»; масштаб не задан - null. */
  text: string | null;
  /** Откуда масштаб, словами. */
  source: string | null;
  zoomPercent: number;
}

/**
 * Плашка масштаба в правом нижнем углу чертежа.
 *
 * Угол свободен: слева сверху встаёт окно калибровки, справа сверху - «отрисовка…», сверху -
 * панель режима зон. Плашка не перехватывает мышь: под ней чертёж панорамируется как обычно.
 */
export const DrawingScaleBadge: FC<{ scale: IDrawingScale }> = ({ scale }) => (
  <div
    data-testid="drawing-scale"
    className="pointer-events-none absolute right-[var(--s-4)] bottom-[var(--s-4)] z-10 flex items-center gap-[var(--s-3)] whitespace-nowrap rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-4)] py-[var(--s-2)] text-xs leading-none shadow-sm"
  >
    <span className="flex items-baseline gap-[var(--s-3)]">
      <span className="text-muted">Масштаб</span>
      <span className={cx('tabular font-medium', !scale.text && 'text-muted')}>
        {scale.text ?? 'не задан'}
      </span>
      {scale.source && <span className="text-muted">{scale.source}</span>}
    </span>
    <span aria-hidden="true" className="h-[12px] w-px flex-none bg-border-strong" />
    <span className="tabular text-muted">вид {scale.zoomPercent} %</span>
  </div>
);
