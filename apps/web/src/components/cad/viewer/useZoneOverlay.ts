'use client';

import {
  useCallback,
  useEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  type WheelEvent as ReactWheelEvent,
} from 'react';

import type { Camera } from '@/lib/viewer/camera';
import { placeViewportPage, type ScreenPoint, type SheetPlacement } from '@/lib/viewer/coordinates';
import { resizeOverlay } from '@/lib/viewer/overlay';

/** Шаг зума на щелчок колеса - тот же, что у просмотрщика. */
const ZOOM_WHEEL_STEP = 1.12;
/** Сдвиг указателя, после которого жест - панорама, а не щелчок. */
const CLICK_SLOP_PX = 5;

export interface IOverlayModifiers {
  readonly shift: boolean;
  readonly alt: boolean;
}

export interface IZoneOverlayHandlers {
  /** Перерисовка холста; вызывается на каждое движение камеры и указателя, без setState. */
  readonly draw: (
    context: CanvasRenderingContext2D,
    placement: SheetPlacement,
    extent: { readonly width: number; readonly height: number },
  ) => void;
  /** Указатель двинулся без нажатия (или сменился модификатор); `null` - ушёл с холста. */
  readonly onHover: (screen: ScreenPoint | null, modifiers: IOverlayModifiers) => void;
  /** Нажатие: `true` - ручка захвачена, дальше жест - перетаскивание, а не панорама. */
  readonly onPress?: (screen: ScreenPoint, modifiers: IOverlayModifiers) => boolean;
  readonly onDrag?: (screen: ScreenPoint, modifiers: IOverlayModifiers) => void;
  readonly onRelease?: (screen: ScreenPoint, modifiers: IOverlayModifiers) => void;
  /** Щелчок без перетаскивания и панорамы. */
  readonly onTap: (screen: ScreenPoint, modifiers: IOverlayModifiers) => void;
  /** Клавиша, когда фокус не в поле ввода. */
  readonly onKey: (event: KeyboardEvent) => void;
}

interface IGesture {
  readonly pointerId: number;
  readonly startX: number;
  readonly startY: number;
  lastX: number;
  lastY: number;
  panning: boolean;
  readonly grabbed: boolean;
}

const isTyping = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement &&
  (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

export interface IZoneOverlay {
  readonly redraw: () => void;
  readonly bind: {
    readonly onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
    readonly onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
    readonly onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
    readonly onPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
    readonly onPointerLeave: () => void;
    readonly onWheel: (event: ReactWheelEvent<HTMLDivElement>) => void;
  };
}

/**
 * Общий слой режимов правки и разреза зоны: холст поверх листа, панорама и зум камеры, щелчок,
 * захват ручки с перетаскиванием, модификаторы Shift/Alt и клавиши.
 *
 * Состояние режима живёт в refs вызывающего компонента, а не в React: движение указателя и камеры
 * только перерисовывает холст (ADR-0004). Свежие обработчики подхватываются без пересоздания
 * подписок. Рефы слоя и холста создаёт вызывающий компонент и вешает на свои узлы.
 */
export const useZoneOverlay = (
  camera: Camera,
  page: { readonly width: number; readonly height: number },
  layerRef: RefObject<HTMLDivElement | null>,
  canvasRef: RefObject<HTMLCanvasElement | null>,
  handlers: IZoneOverlayHandlers,
): IZoneOverlay => {
  const gesture = useRef<IGesture | null>(null);
  const pointer = useRef<ScreenPoint | null>(null);
  const modifiers = useRef<IOverlayModifiers>({ shift: false, alt: false });

  const latest = useRef({ handlers, page });
  useEffect(() => {
    latest.current = { handlers, page };
  });

  const redraw = useCallback(() => {
    const element = canvasRef.current;
    const host = layerRef.current;
    const context = element?.getContext('2d');
    if (!element || !host || !context) return;
    const ratio = window.devicePixelRatio || 1;
    resizeOverlay(element, host.clientWidth, host.clientHeight, ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, host.clientWidth, host.clientHeight);
    latest.current.handlers.draw(
      context,
      placeViewportPage(latest.current.page, camera.getState()),
      { width: host.clientWidth, height: host.clientHeight },
    );
  }, [camera, layerRef, canvasRef]);

  useEffect(() => {
    const unsubscribeCamera = camera.subscribe(redraw);
    const host = layerRef.current;
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(redraw) : null;
    if (host) observer?.observe(host);

    // Shift - ortho, Alt - без привязки: пересчитать, не дожидаясь движения мыши.
    const onModifier = (event: KeyboardEvent) => {
      if (event.key !== 'Shift' && event.key !== 'Alt') return;
      modifiers.current = { shift: event.shiftKey, alt: event.altKey };
      if (pointer.current) latest.current.handlers.onHover(pointer.current, modifiers.current);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      onModifier(event);
      if (isTyping(event.target)) return;
      latest.current.handlers.onKey(event);
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('keyup', onModifier);
    redraw();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('keyup', onModifier);
      unsubscribeCamera();
      observer?.disconnect();
    };
  }, [camera, redraw, layerRef]);

  const local = (event: { clientX: number; clientY: number }): ScreenPoint => {
    const bounds = layerRef.current?.getBoundingClientRect();
    return { x: event.clientX - (bounds?.left ?? 0), y: event.clientY - (bounds?.top ?? 0) };
  };
  const modifiersOf = (event: { shiftKey: boolean; altKey: boolean }): IOverlayModifiers => {
    modifiers.current = { shift: event.shiftKey, alt: event.altKey };
    return modifiers.current;
  };

  const release = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (gesture.current !== null) return;
    if (event.pointerType === 'mouse' && event.button !== 0 && event.button !== 1) return;
    if (event.button === 1) event.preventDefault();
    const grabbed =
      event.button !== 1 &&
      (latest.current.handlers.onPress?.(local(event), modifiersOf(event)) ?? false);
    gesture.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      // Средняя кнопка двигает лист сразу, как в просмотрщике.
      panning: event.button === 1,
      grabbed,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current === null || current.pointerId !== event.pointerId) {
      pointer.current = local(event);
      latest.current.handlers.onHover(pointer.current, modifiersOf(event));
      return;
    }
    if (current.grabbed) {
      pointer.current = local(event);
      latest.current.handlers.onDrag?.(pointer.current, modifiersOf(event));
      return;
    }
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

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current === null || current.pointerId !== event.pointerId) return;
    gesture.current = null;
    release(event);
    const mods = modifiersOf(event);
    if (current.grabbed) {
      latest.current.handlers.onRelease?.(local(event), mods);
      return;
    }
    if (current.panning) return;
    latest.current.handlers.onTap(local(event), mods);
  };

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current?.pointerId !== event.pointerId) return;
    gesture.current = null;
    release(event);
    if (current.grabbed) latest.current.handlers.onRelease?.(local(event), modifiers.current);
  };

  const onPointerLeave = () => {
    pointer.current = null;
    if (gesture.current === null) latest.current.handlers.onHover(null, modifiers.current);
  };

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    camera.zoomAt(local(event), event.deltaY < 0 ? ZOOM_WHEEL_STEP : 1 / ZOOM_WHEEL_STEP);
  };

  return {
    redraw,
    bind: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onPointerLeave, onWheel },
  };
};
