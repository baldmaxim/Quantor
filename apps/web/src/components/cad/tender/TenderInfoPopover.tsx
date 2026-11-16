'use client';

import { useEffect, useLayoutEffect, useRef, type FC } from 'react';
import { createPortal } from 'react-dom';

import type { IMepInfo } from '@/lib/cad/floor3d-mep-info';
import { POPOVER_OFFSET_PX, placePopover } from '@/lib/cad/constructions';

interface ITenderInfoPopoverProps {
  readonly info: IMepInfo;
  /** Точка клика в координатах окна. */
  readonly anchor: { readonly x: number; readonly y: number };
  readonly onClose: () => void;
}

/**
 * Плашка объекта расчёта на плане (ширина 300 px, на узком окне - по окну за вычетом полей). Положение -
 * у точки клика, у края окна переворачивается. Закрывается Esc, крестиком и щелчком вне; панораму и зум
 * отслеживает владелец (камера идёт мимо React, ADR-0004). Только просмотр.
 */
export const TenderInfoPopover: FC<ITenderInfoPopoverProps> = ({ info, anchor, onClose }) => {
  const element = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return undefined;
    const apply = () => {
      const box = node.getBoundingClientRect();
      const at = placePopover(
        anchor,
        { width: box.width, height: box.height },
        { width: window.innerWidth, height: window.innerHeight },
      );
      node.style.left = `${at.left}px`;
      node.style.top = `${at.top}px`;
    };
    apply();
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(apply) : null;
    observer?.observe(node);
    window.addEventListener('resize', apply);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', apply);
    };
  }, [anchor]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && element.current?.contains(event.target)) return;
      onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown, true);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={element}
      role="dialog"
      aria-label={`Расчёт: ${info.title}`}
      data-testid="tender-popover"
      // Положение у курсора - динамическое значение; уточняется после замера в layout-эффекте.
      style={{ left: anchor.x + POPOVER_OFFSET_PX, top: anchor.y + POPOVER_OFFSET_PX }}
      className="scroll-area fixed z-50 flex max-h-[70dvh] w-[300px] max-w-[calc(100vw-16px)] flex-col gap-[var(--s-3)] overflow-y-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-4)] shadow-[var(--shadow-2)]"
    >
      <div className="flex items-start justify-between gap-[var(--s-3)]">
        <h3 className="m-0 text-sm font-semibold [overflow-wrap:anywhere]">{info.title}</h3>
        <button
          type="button"
          aria-label="Закрыть карточку"
          onClick={onClose}
          className="press -mt-[var(--s-2)] -mr-[var(--s-2)] grid h-[44px] w-[44px] flex-none place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text md:h-[28px] md:w-[28px]"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
      {info.rows.map((row) => (
        <p key={row.label} className="m-0 text-xs [overflow-wrap:anywhere]">
          <span className="text-muted">{row.label}: </span>
          {row.value}
        </p>
      ))}
    </div>,
    document.body,
  );
};
