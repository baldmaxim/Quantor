'use client';

import {
  useEffect,
  useRef,
  type FC,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';

import { styleClassInfo, type StyleSample } from '@/lib/cad/style-profile';
import type { Camera } from '@/lib/viewer/camera';
import { placeViewportPage, toNormalizedPoint, toScreenPoint } from '@/lib/viewer/coordinates';
import { resizeOverlay } from '@/lib/viewer/overlay';

interface ICadStyleCaptureProps {
  camera: Camera;
  /** Размер страницы у отрисовщика (pt при масштабе 1) - единицы листа в камере. */
  page: { readonly width: number; readonly height: number };
  samples: readonly StyleSample[];
  /** Щелчок по листу: точка в долях страницы от левого верхнего угла. */
  onSample: (point: { x: number; y: number }) => void;
  /** Esc: режим образцов закрыт. */
  onExit: () => void;
}

const ZOOM_WHEEL_STEP = 1.12;
const CLICK_SLOP_PX = 5;
const MARKER_RADIUS = 6;
const CROSS_HALF = 9;

interface IGesture {
  readonly pointerId: number;
  readonly startX: number;
  readonly startY: number;
  lastX: number;
  lastY: number;
  panning: boolean;
}

/** Открытые поповеры и диалоги: Esc принадлежит им. */
const FOREIGN_LAYER = '[role="dialog"], [role="menu"], [role="listbox"], [aria-modal="true"]';

const isTyping = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement &&
  (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

/**
 * Слой образцов профиля оформления: щелчок по листу ставит образец текущего класса, маркеры
 * рисуются на Canvas2D (положительный - кружок цвета класса, отрицательный - с крестом).
 *
 * Esc выходит из режима, но не трогает образцы. Образцы приходят пропсом и меняются только щелчком; панорама и зум перерисовывают холст
 * подпиской на камеру, мимо состояния React (ADR-0004). Перетаскивание и колесо двигают лист.
 */
export const CadStyleCapture: FC<ICadStyleCaptureProps> = ({
  camera,
  page,
  samples,
  onSample,
  onExit,
}) => {
  const layer = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const gesture = useRef<IGesture | null>(null);

  const callbacks = useRef({ onSample, onExit });
  const data = useRef({ page, samples });
  const draw = useRef<() => void>(() => undefined);
  useEffect(() => {
    callbacks.current = { onSample, onExit };
    data.current = { page, samples };
    draw.current();
  });

  useEffect(() => {
    draw.current = () => {
      const element = canvas.current;
      const host = layer.current;
      const context = element?.getContext('2d');
      if (!element || !host || !context) return;
      const ratio = window.devicePixelRatio || 1;
      resizeOverlay(element, host.clientWidth, host.clientHeight, ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, host.clientWidth, host.clientHeight);
      const placement = placeViewportPage(data.current.page, camera.getState());
      context.lineWidth = 2;
      for (const sample of data.current.samples) {
        const point = toScreenPoint({ x: sample.x, y: sample.y }, placement);
        const color = styleClassInfo(sample.class).color;
        context.strokeStyle = color;
        context.fillStyle = color;
        context.beginPath();
        context.arc(point.x, point.y, MARKER_RADIUS, 0, Math.PI * 2);
        if (sample.negative) {
          context.stroke();
          context.beginPath();
          context.moveTo(point.x - CROSS_HALF, point.y - CROSS_HALF);
          context.lineTo(point.x + CROSS_HALF, point.y + CROSS_HALF);
          context.moveTo(point.x + CROSS_HALF, point.y - CROSS_HALF);
          context.lineTo(point.x - CROSS_HALF, point.y + CROSS_HALF);
          context.stroke();
        } else {
          context.fill();
        }
      }
    };
    const redraw = () => draw.current();
    const unsubscribe = camera.subscribe(redraw);
    const host = layer.current;
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(redraw) : null;
    if (host) observer?.observe(host);
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target) || event.defaultPrevented) return;
      // Esc закрывает чужой поповер или диалог, а не режим образцов.
      if (document.querySelector(FOREIGN_LAYER) !== null) return;
      if (event.key === 'Escape') callbacks.current.onExit();
    };
    document.addEventListener('keydown', onKeyDown);
    redraw();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      unsubscribe();
      observer?.disconnect();
    };
  }, [camera]);

  const local = (event: { clientX: number; clientY: number }) => {
    const bounds = layer.current?.getBoundingClientRect();
    return { x: event.clientX - (bounds?.left ?? 0), y: event.clientY - (bounds?.top ?? 0) };
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (gesture.current !== null) return;
    if (event.pointerType === 'mouse' && event.button !== 0 && event.button !== 1) return;
    if (event.button === 1) event.preventDefault();
    gesture.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      panning: event.button === 1,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current === null || current.pointerId !== event.pointerId) return;
    if (
      !current.panning &&
      Math.hypot(event.clientX - current.startX, event.clientY - current.startY) > CLICK_SLOP_PX
    ) {
      current.panning = true;
    }
    if (current.panning) {
      camera.panBy(event.clientX - current.lastX, event.clientY - current.lastY);
      current.lastX = event.clientX;
      current.lastY = event.clientY;
    }
  };

  const release = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current === null || current.pointerId !== event.pointerId) return;
    gesture.current = null;
    release(event);
    if (current.panning) return;
    const placement = placeViewportPage(data.current.page, camera.getState());
    const point = toNormalizedPoint(local(event), placement);
    // Щелчок мимо страницы образцом не становится.
    if (point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) return;
    callbacks.current.onSample({ x: point.x, y: point.y });
  };

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (gesture.current?.pointerId !== event.pointerId) return;
    gesture.current = null;
    release(event);
  };

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    camera.zoomAt(local(event), event.deltaY < 0 ? ZOOM_WHEEL_STEP : 1 / ZOOM_WHEEL_STEP);
  };

  return (
    <div
      ref={layer}
      data-testid="style-capture"
      role="application"
      aria-label="Область образцов профиля оформления: щелчок ставит образец"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onWheel={onWheel}
      className="absolute inset-0 z-10 cursor-crosshair touch-none"
    >
      <canvas ref={canvas} className="pointer-events-none absolute top-0 left-0" />
    </div>
  );
};
