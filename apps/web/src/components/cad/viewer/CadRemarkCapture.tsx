'use client';

import { useEffect, useRef, type FC, type PointerEvent as ReactPointerEvent } from 'react';

import { normalizeBboxPt, screenToPagePt, type BboxPt, type IPageSizePt } from '@/lib/cad/remarks';
import type { Camera } from '@/lib/viewer/camera';

interface ICadRemarkCaptureProps {
  camera: Camera;
  /** Размер страницы в pt при масштабе 1 - единицы листа в камере. */
  page: IPageSizePt;
  /** Прямоугольник отмечен: координаты в pt PDF от левого верхнего угла. */
  onDrawn: (bbox: BboxPt) => void;
}

interface IDrag {
  readonly pointerId: number;
  readonly startX: number;
  readonly startY: number;
}

/**
 * Прозрачный слой захвата поверх холста, пока включён режим «Отметить участок».
 *
 * Рамка при протягивании двигается императивно (стили элемента), а не через состояние React:
 * камера и жесты вне React (ADR-0004), и рамка не должна перерисовывать панель на каждое движение.
 * Положение камеры читается в момент отпускания: сдвиг экрана в pt - `screenToPagePt`.
 */
export const CadRemarkCapture: FC<ICadRemarkCaptureProps> = ({ camera, page, onDrawn }) => {
  const layer = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<IDrag | null>(null);
  const stopWatching = useRef<(() => void) | null>(null);

  const finish = () => {
    drag.current = null;
    stopWatching.current?.();
    stopWatching.current = null;
    if (box.current) box.current.hidden = true;
  };

  // Слой закрывается вместе с режимом: незаконченный жест не остаётся висеть.
  useEffect(() => () => stopWatching.current?.(), []);

  const local = (event: { clientX: number; clientY: number }) => {
    const bounds = layer.current?.getBoundingClientRect();
    return { x: event.clientX - (bounds?.left ?? 0), y: event.clientY - (bounds?.top ?? 0) };
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current !== null) return;
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    const point = local(event);
    drag.current = { pointerId: event.pointerId, startX: point.x, startY: point.y };
    event.currentTarget.setPointerCapture(event.pointerId);

    // Второй палец - щипок камеры, а не отметка: его события гасятся выше по дереву, поэтому
    // ловим его на окне в фазе перехвата и отменяем начатую рамку.
    const onOther = (other: PointerEvent) => {
      if (other.pointerId !== event.pointerId) finish();
    };
    window.addEventListener('pointerdown', onOther, true);
    stopWatching.current = () => window.removeEventListener('pointerdown', onOther, true);

    if (box.current) {
      box.current.hidden = false;
      box.current.style.left = `${point.x}px`;
      box.current.style.top = `${point.y}px`;
      box.current.style.width = '0px';
      box.current.style.height = '0px';
    }
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (current === null || current.pointerId !== event.pointerId || !box.current) return;
    const point = local(event);
    box.current.style.left = `${Math.min(point.x, current.startX)}px`;
    box.current.style.top = `${Math.min(point.y, current.startY)}px`;
    box.current.style.width = `${Math.abs(point.x - current.startX)}px`;
    box.current.style.height = `${Math.abs(point.y - current.startY)}px`;
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (current === null || current.pointerId !== event.pointerId) return;
    const point = local(event);
    finish();
    const state = camera.getState();
    const bbox = normalizeBboxPt(
      screenToPagePt(state, current.startX, current.startY),
      screenToPagePt(state, point.x, point.y),
      page,
    );
    if (bbox) onDrawn(bbox);
  };

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId === event.pointerId) finish();
  };

  return (
    <div
      ref={layer}
      data-testid="remark-capture"
      aria-label="Область разметки замечания: протяните прямоугольник"
      role="application"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      className="absolute inset-0 z-10 cursor-crosshair touch-none"
    >
      <div
        ref={box}
        hidden
        data-testid="remark-draft-box"
        className="pointer-events-none absolute border-2 border-dashed border-[var(--sheet-ink-danger)] bg-[color-mix(in_srgb,var(--sheet-ink-danger)_10%,transparent)]"
      />
    </div>
  );
};
