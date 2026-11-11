'use client';

import { useEffect, useLayoutEffect, useRef, type FC } from 'react';
import { createPortal } from 'react-dom';

import { StatusBadge } from '@/components/ui';
import {
  SLAB_STATUS_LABELS,
  STATUS_LABELS,
  constructionTitle,
  isFloorSlab,
} from '@/lib/cad/construction-labels';
import { POPOVER_OFFSET_PX, placePopover } from '@/lib/cad/constructions';

import { ConstructionComputed } from './ConstructionComputed';
import { ConstructionPropsForm } from './ConstructionPropsForm';
import type { IWorkspaceCadConstructionPopover } from './types';

/**
 * Карточка конструкции у точки клика (ширина 340 px, на узком окне - по окну за вычетом полей). Положение - экранные координаты клика со смещением; у края
 * окна карточка переворачивается и не выходит за него. Закрывается Esc, крестиком и щелчком вне:
 * при панораме и зуме её закрывает владелец (камера идёт мимо React, ADR-0004).
 *
 * Положение ставится прямо на элемент в layout-эффекте: размер известен только после разметки, а
 * состояние ради этого вызвало бы лишний кадр.
 */
export const ConstructionPopover: FC<IWorkspaceCadConstructionPopover> = ({
  construction,
  doors,
  groupCount,
  anchor,
  saving,
  error,
  onClose,
  onSave,
  onBulk,
  onAccept,
}) => {
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
    // Щелчок вне карточки закрывает её; щелчок по холсту после этого выберет другую конструкцию.
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

  const { computed } = construction;
  const statusLabels = isFloorSlab(construction.kind) ? SLAB_STATUS_LABELS : STATUS_LABELS;
  return createPortal(
    <div
      ref={element}
      role="dialog"
      aria-label={`Конструкция: ${constructionTitle(construction)}`}
      data-testid="construction-popover"
      // Пробел и стрелки в полях карточки не должны доходить до горячих клавиш просмотрщика.
      onKeyDown={(event) => {
        if (event.key !== 'Escape') event.stopPropagation();
      }}
      style={{ left: anchor.x + POPOVER_OFFSET_PX, top: anchor.y + POPOVER_OFFSET_PX }}
      className="scroll-area fixed z-50 flex max-h-[70dvh] w-[340px] max-w-[calc(100vw-16px)] flex-col gap-[var(--s-5)] overflow-y-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-5)] shadow-[var(--shadow-2)]"
    >
      <header className="flex min-w-0 items-start justify-between gap-[var(--s-3)]">
        <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <h3 className="m-0 text-sm font-medium break-words">{constructionTitle(construction)}</h3>
          <div className="flex flex-wrap gap-[var(--s-3)]">
            {computed.status !== 'ok' && (
              <StatusBadge tone="warning">{statusLabels[computed.status]}</StatusBadge>
            )}
            {construction.accepted && <StatusBadge tone="success">Принято</StatusBadge>}
          </div>
        </div>
        <button
          type="button"
          aria-label="Закрыть карточку"
          onClick={onClose}
          className="press grid h-[44px] w-[44px] shrink-0 place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-[14px] w-[14px]"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </header>

      <ConstructionComputed construction={construction} doors={doors} />

      <ConstructionPropsForm
        // Параметры пришли с сервера другими: черновик начинается заново.
        key={`${construction.id}:${JSON.stringify(construction.props)}`}
        construction={construction}
        groupCount={groupCount}
        saving={saving}
        onSave={onSave}
        onBulk={onBulk}
        onAccept={onAccept}
      />

      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>,
    document.body,
  );
};
