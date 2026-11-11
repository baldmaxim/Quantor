'use client';

import {
  useEffect,
  useMemo,
  useRef,
  type FC,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import {
  buildSnapIndex,
  snapPoint,
  zonesToSnapShapes,
  type ISnapResult,
} from '@/lib/cad/zone-snap';
import { drawSnapMarker } from '@/lib/cad/zone-snap-marker';
import { readZoneColors, zoneColor } from '@/lib/cad/zones-painter';
import {
  CLOSE_RADIUS_PX,
  clickClosesPolygon,
  pointsToPairs,
  zoneToolMode,
  type ZoneKind,
} from '@/lib/cad/zones';
import type { Camera } from '@/lib/viewer/camera';
import {
  placeViewportPage,
  toNormalizedPoint,
  toScreenPoint,
  type ScreenPoint,
} from '@/lib/viewer/coordinates';
import { resizeOverlay } from '@/lib/viewer/overlay';
import { ToolController } from '@/lib/viewer/tool-controller';

interface ICadZoneCaptureProps {
  camera: Camera;
  /** Размер страницы у отрисовщика (pt при масштабе 1) - единицы листа в камере. */
  page: { readonly width: number; readonly height: number };
  kind: ZoneKind;
  /** Готовые зоны листа: их вершины и рёбра - цели привязки. */
  zones: readonly CadZoneRead[];
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
  zones,
  onComplete,
  onExit,
}) => {
  const layer = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const gesture = useRef<IGesture | null>(null);
  const controller = useMemo(() => new ToolController(zoneToolMode(kind)), [kind]);
  const colors = useMemo(() => readZoneColors(), []);
  const color = useMemo(() => zoneColor(colors, kind), [colors, kind]);
  // Индекс привязки строится один раз на смену набора зон, не на каждое движение.
  const snapIndex = useMemo(() => buildSnapIndex(zonesToSnapShapes(zones)), [zones]);
  // Привязка и модификаторы живут вне React: меняются на каждом движении указателя.
  const snap = useRef<ISnapResult | null>(null);
  const pointer = useRef<ScreenPoint | null>(null);
  const modifiers = useRef({ shift: false, alt: false });

  // Свежие обработчики без пересоздания контроллера и подписок.
  const callbacks = useRef({ onComplete, onExit });
  useEffect(() => {
    callbacks.current = { onComplete, onExit };
  });

  // Привязка точки экрана к зонам листа и черновику; масштаб - текущий размер листа в пикселях.
  const snapAt = (screen: ScreenPoint): ISnapResult => {
    const placement = placeViewportPage(page, camera.getState());
    return snapPoint(toNormalizedPoint(screen, placement), {
      index: snapIndex,
      scale: { x: placement.width, y: placement.height },
      placed: controller.getState().points,
      shift: modifiers.current.shift,
      alt: modifiers.current.alt,
    });
  };

  // Указатель двинулся (или сменился модификатор): пересчитать привязку и предварительное звено.
  const track = useRef<(screen: ScreenPoint | null) => void>(() => undefined);
  useEffect(() => {
    track.current = (screen) => {
      pointer.current = screen;
      const result = screen ? snapAt(screen) : null;
      snap.current = result;
      controller.send({ type: 'pointerMove', point: result ? result.point : null });
    };
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
      const extent = { width: host.clientWidth, height: host.clientHeight };
      if (vertices.length === 0) {
        if (hover) drawSnapMarker(context, colors, snap.current, hover, null, extent);
        return;
      }

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
      if (hover) {
        const anchor = vertices[vertices.length - 1] ?? null;
        drawSnapMarker(context, colors, snap.current, hover, anchor, extent);
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

    // Shift - ortho, Alt - без привязки: перерисовать метку, не дожидаясь движения мыши.
    const onModifier = (event: KeyboardEvent) => {
      if (event.key !== 'Shift' && event.key !== 'Alt') return;
      modifiers.current = { shift: event.shiftKey, alt: event.altKey };
      if (pointer.current) track.current(pointer.current);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      onModifier(event);
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
    document.addEventListener('keyup', onModifier);
    redraw();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('keyup', onModifier);
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
      modifiers.current = { shift: event.shiftKey, alt: event.altKey };
      track.current(local(event));
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
    modifiers.current = { shift: event.shiftKey, alt: event.altKey };
    controller.send({ type: 'pointerDown', point: snapAt(click).point });
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
      onPointerLeave={() => track.current(null)}
      onWheel={onWheel}
      className="absolute inset-0 z-10 cursor-crosshair touch-none"
    >
      <canvas ref={canvas} className="pointer-events-none absolute top-0 left-0" />
    </div>
  );
};
