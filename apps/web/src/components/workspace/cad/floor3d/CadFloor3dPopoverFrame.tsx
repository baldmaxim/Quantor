'use client';

import type { FC, ReactNode } from 'react';

/** Оболочка карточки у курсора: положение в пределах холста, заголовок и кнопка «Закрыть». */

const WIDTH_PX = 252;
const HEIGHT_ESTIMATE_PX = 340;
const GAP_PX = 12;
const EDGE_PX = 8;

interface ICadFloor3dPopoverFrameProps {
  readonly title: string;
  /** Точка клика от угла холста и размер холста, px. */
  readonly anchor: { readonly x: number; readonly y: number };
  readonly bounds: { readonly width: number; readonly height: number };
  readonly onClose: () => void;
  readonly children: ReactNode;
}

export const CadFloor3dPopoverFrame: FC<ICadFloor3dPopoverFrameProps> = ({
  title,
  anchor,
  bounds,
  onClose,
  children,
}) => {
  const left = Math.max(EDGE_PX, Math.min(anchor.x + GAP_PX, bounds.width - WIDTH_PX - EDGE_PX));
  const top = Math.max(EDGE_PX, Math.min(anchor.y + GAP_PX, bounds.height - HEIGHT_ESTIMATE_PX));

  return (
    <div
      role="dialog"
      aria-label={title}
      data-testid="floor3d-popover"
      // Положение у курсора - динамическое значение.
      style={{ left, top }}
      className="absolute z-10 flex max-h-[60%] w-[252px] max-w-[calc(100%-16px)] flex-col gap-[var(--s-3)] overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-4)] shadow-[var(--shadow-2)]"
    >
      <div className="flex items-start justify-between gap-[var(--s-3)]">
        <h4 className="text-sm font-semibold [overflow-wrap:anywhere]">{title}</h4>
        <button
          type="button"
          aria-label="Закрыть карточку"
          onClick={onClose}
          className="press -mt-[var(--s-2)] -mr-[var(--s-2)] grid h-[44px] w-[44px] flex-none place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text md:h-[28px] md:w-[28px]"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
      {children}
    </div>
  );
};
