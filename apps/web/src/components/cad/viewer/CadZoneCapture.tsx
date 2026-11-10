'use client';

import {
  useEffect,
  useMemo,
  useRef,
  type FC,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';

import { readZoneColors, zoneColor } from '@/lib/cad/zones-painter';
import {
  CLOSE_RADIUS_PX,
  clickClosesPolygon,
  pointsToPairs,
  zoneToolMode,
  type ZoneKind,
} from '@/lib/cad/zones';
import type { Camera } from '@/lib/viewer/camera';
import { placeViewportPage, toNormalizedPoint, toScreenPoint } from '@/lib/viewer/coordinates';
import { resizeOverlay } from '@/lib/viewer/overlay';
import { ToolController } from '@/lib/viewer/tool-controller';

interface ICadZoneCaptureProps {
  camera: Camera;
  /** Размер страницы у отрисовщика (pt при масштабе 1) - единицы листа в камере. */
  page: { readonly width: number; readonly height: number };
  kind: ZoneKind;
  /** Контур или линия двери готовы: точки [x, y] в долях листа от левого верхнего угла. */
  onComplete: (points: [number, number][]) => void;
  /** Esc при пустом черновике: режим рисования закрыт. */
  onExit: () => void;
}

/** Шаг зума на щелчок колеса - тот же, что у просмотрщика. */
const ZOOM_WHEEL_STEP = 1.12;
/** Сдвиг указателя, после которого жест - панорама, а не щелчок. */
const CLICK_SLOP_PX = 5;
const VERTEX_RADIUS = 4;
const DRAFT_DASH = [6, 4];

interface IGesture {
  readonly pointerId: number;
  readonly startX: number;
  readonly startY: number;
  lastX: number;
  lastY: number;
  panning: boolean;
}

const isTyping = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement &&
  (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

/**
 * Слой рисования зоны поверх холста: щелчок ставит вершину, Enter, двойной щелчок или щелчок по
 * первой вершине замыкают помещение (дверь завершается второй точкой), Esc отменяет черновик,
 * Backspace убирает последнюю вершину.
 *
 * Точки ведёт та же чистая машина инструментов, что у обмера, в своём контроллере вне React:
 * движение указателя и камеры только перерисовывает холст черновика (ADR-0004). Перетаскивание
 * и колесо двигают камеру, чтобы лист можно было подвинуть, не выходя из режима.
 */
export const CadZoneCapture: FC<ICadZoneCaptureProps> = ({
  camera,
  page,
  kind,
  onComplete,
  onExit,
}) => {
  const layer = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const gesture = useRef<IGesture | null>(null);
  const controller = useMemo(() => new ToolController(zoneToolMode(kind)), [kind]);
  const color = useMemo(() => zoneColor(readZoneColors(), kind), [kind]);

  // Свежие обработчики без пересоздания контроллера и подписок.
  const callbacks = useRef({ onComplete, onExit });
  useEffect(() => {
    callbacks.current = { onComplete, onExit };
  });

  const draw = useRef<() => void>(() => undefined);
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

      const state = controller.getState();
      const placement = placeViewportPage(page, camera.getState());
      const vertices = state.points.map((point) => toScreenPoint(point, placement));
      const hover = state.hover ? toScreenPoint(state.hover, placement) : null;
      if (vertices.length === 0) return;

      context.strokeStyle = color;
      context.fillStyle = color;
      context.lineWidth = 2;
      context.lineJoin = 'round';
      context.beginPath();
      vertices.forEach((point, index) => {
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.stroke();
      if (hover) {
        // Предварительное звено до курсора; для помещения - и замыкающее к первой вершине.
        context.setLineDash(DRAFT_DASH);
        context.beginPath();
        const last = vertices[vertices.length - 1];
        if (last) context.moveTo(last.x, last.y);
        context.lineTo(hover.x, hover.y);
        if (kind !== 'door' && vertices[0]) context.lineTo(vertices[0].x, vertices[0].y);
        context.stroke();
        context.setLineDash([]);
      }
      for (const point of vertices) {
        context.beginPath();
        context.arc(point.x, point.y, VERTEX_RADIUS, 0, Math.PI * 2);
        context.fill();
      }
      const first = vertices[0];
      if (kind !== 'door' && first && vertices.length >= 3) {
        // Кольцо у первой вершины: щелчок в него замыкает контур.
        context.beginPath();
        context.arc(first.x, first.y, CLOSE_RADIUS_PX, 0, Math.PI * 2);
        context.stroke();
      }
    };
  });

  useEffect(() => {
    const redraw = () => draw.current();
    controller.setHandlers({
      onCompleted: (shape) => callbacks.current.onComplete(pointsToPairs(shape.points)),
    });
    const unsubscribeTool = controller.subscribe(redraw);
    const unsubscribeCamera = camera.subscribe(redraw);
    const host = layer.current;
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(redraw) : null;
    if (host) observer?.observe(host);

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return;
      if (event.key === 'Enter') {
        controller.send({ type: 'finish' });
        event.preventDefault();
      } else if (event.key === 'Escape') {
        if (controller.getState().points.length > 0) controller.send({ type: 'cancel' });
        else callbacks.current.onExit();
      } else if (event.key === 'Backspace') {
        controller.send({ type: 'backspace' });
        event.preventDefault();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    redraw();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      unsubscribeTool();
      unsubscribeCamera();
      observer?.disconnect();
      controller.dispose();
    };
  }, [controller, camera]);

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
      // Средняя кнопка двигает лист сразу, как в просмотрщике.
      panning: event.button === 1,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (current === null || current.pointerId !== event.pointerId) {
      const point = local(event);
      controller.send({
        type: 'pointerMove',
        point: toNormalizedPoint(point, placeViewportPage(page, camera.getState())),
      });
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

    const click = local(event);
    const placement = placeViewportPage(page, camera.getState());
    const state = controller.getState();
    const vertices = state.points.map((point) => toScreenPoint(point, placement));
    if (clickClosesPolygon(state.mode, vertices, click)) {
      controller.send({ type: 'finish' });
      return;
    }
    controller.send({ type: 'pointerDown', point: toNormalizedPoint(click, placement) });
  };

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (gesture.current?.pointerId !== event.pointerId) return;
    gesture.current = null;
    release(event);
  };

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const point = local(event);
    camera.zoomAt(point, event.deltaY < 0 ? ZOOM_WHEEL_STEP : 1 / ZOOM_WHEEL_STEP);
  };

  return (
    <div
      ref={layer}
      data-testid="zone-capture"
      role="application"
      aria-label="Область разметки зоны: щелчок ставит вершину"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onPointerLeave={() => controller.send({ type: 'pointerMove', point: null })}
      onWheel={onWheel}
      className="absolute inset-0 z-10 cursor-crosshair touch-none"
    >
      <canvas ref={canvas} className="pointer-events-none absolute top-0 left-0" />
    </div>
  );
};
