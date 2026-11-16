'use client';

import {
  useEffect,
  useRef,
  type FC,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import {
  fitPlanView,
  mmToScreen,
  panPlanView,
  snapToVertex2d,
  zoomPlanView,
  type IPlanView,
  type ISitePlan,
  type MmPoint,
  type PinPoints,
  type PinSlot,
} from '@/lib/cad/site-pin-geometry';
import { resizeOverlay } from '@/lib/viewer/overlay';

interface ISitePinPlanCanvasProps {
  readonly plan: ISitePlan;
  readonly points: PinPoints;
  /** Точка, которую поставит следующий щелчок: подсвечивается ободком. */
  readonly armed: PinSlot | null;
  /** Растёт на каждое «Вписать». */
  readonly fitSeq: number;
  readonly label: string;
  readonly onPick: (point: MmPoint) => void;
}

const WHEEL_STEP = 1.15;
const CLICK_SLOP_PX = 5;
const MARKER_RADIUS = 9;

interface IColors {
  readonly paper: string;
  readonly ink: string;
  readonly first: string;
  readonly second: string;
  readonly onMarker: string;
}

/** Цвета - токены темы: лист светлый в обеих темах, поэтому чернила листа, а не тематические. */
const readColors = (): IColors => {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string): string => style.getPropertyValue(name).trim() || fallback;
  return {
    paper: token('--canvas', 'Canvas'),
    ink: token('--canvas-ink', 'CanvasText'),
    first: token('--sheet-ink', 'CanvasText'),
    second: token('--sheet-ink-danger', 'CanvasText'),
    onMarker: token('--region-tag-text', 'Canvas'),
  };
};

interface IPointer {
  x: number;
  y: number;
}

/**
 * Панель плана этажа для привязки: контуры стен и плиты в мм кадра вида, колесо и щипок - зум, перетаскивание -
 * панорама, щелчок ставит точку с привязкой к вершине. Зум и сдвиг живут в `ref` и только перерисовывают
 * холст (ADR-0004): состояние React не участвует. Canvas2D (ADR-0015).
 */
export const SitePinPlanCanvas: FC<ISitePinPlanCanvasProps> = ({ plan, points, armed, fitSeq, label, onPick }) => {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<IPlanView | null>(null);
  const colors = useRef<IColors | null>(null);
  const pointers = useRef(new Map<number, IPointer>());
  const moved = useRef(false);
  // Свежие входные данные для обработчиков без их пересоздания.
  const latest = useRef({ plan, points, armed, onPick });
  useEffect(() => {
    latest.current = { plan, points, armed, onPick };
  });

  const draw = useRef<() => void>(() => undefined);
  useEffect(() => {
    draw.current = () => {
      const element = canvas.current;
      const box = host.current;
      const context = element?.getContext('2d');
      const current = view.current;
      if (!element || !box || !context) return;
      colors.current ??= readColors();
      const palette = colors.current;
      const ratio = window.devicePixelRatio || 1;
      resizeOverlay(element, box.clientWidth, box.clientHeight, ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.fillStyle = palette.paper;
      context.fillRect(0, 0, box.clientWidth, box.clientHeight);
      if (current === null) return;

      context.strokeStyle = palette.ink;
      context.lineWidth = 1;
      context.lineJoin = 'round';
      for (const ring of latest.current.plan.rings) {
        context.beginPath();
        ring.forEach((point, index) => {
          const screen = mmToScreen(point, current);
          if (index === 0) context.moveTo(screen.x, screen.y);
          else context.lineTo(screen.x, screen.y);
        });
        context.closePath();
        context.stroke();
      }

      const placed = latest.current.points;
      const [first, second] = placed;
      if (first !== null && second !== null) {
        const a = mmToScreen(first, current);
        const b = mmToScreen(second, current);
        context.setLineDash([6, 4]);
        context.strokeStyle = palette.first;
        context.lineWidth = 2;
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.stroke();
        context.setLineDash([]);
      }
      placed.forEach((point, index) => {
        if (point === null) return;
        const screen = mmToScreen(point, current);
        const color = index === 0 ? palette.first : palette.second;
        context.fillStyle = color;
        context.beginPath();
        context.arc(screen.x, screen.y, MARKER_RADIUS, 0, Math.PI * 2);
        context.fill();
        if (latest.current.armed === index) {
          context.strokeStyle = color;
          context.lineWidth = 2;
          context.beginPath();
          context.arc(screen.x, screen.y, MARKER_RADIUS + 4, 0, Math.PI * 2);
          context.stroke();
        }
        context.fillStyle = palette.onMarker;
        context.font = '600 12px system-ui, sans-serif';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(String(index + 1), screen.x, screen.y + 0.5);
      });
    };
  });

  const fit = useRef<() => void>(() => undefined);
  useEffect(() => {
    fit.current = () => {
      const box = host.current;
      if (!box || box.clientWidth === 0 || box.clientHeight === 0) return;
      view.current = fitPlanView(latest.current.plan.bounds, box.clientWidth, box.clientHeight);
      draw.current();
    };
  });

  // Другой этаж или «Вписать»: вид заново по габариту плана.
  useEffect(() => fit.current(), [plan, fitSeq]);
  // Точки и назначенная точка - только перерисовка.
  useEffect(() => draw.current(), [points, armed]);

  useEffect(() => {
    const box = host.current;
    if (!box) return undefined;
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => (view.current === null ? fit.current() : draw.current())) : null;
    observer?.observe(box);
    // Колесо нужно не пассивным: страница под панелью не должна прокручиваться.
    const onWheel = (event: WheelEvent): void => {
      const current = view.current;
      if (current === null) return;
      event.preventDefault();
      const bounds = box.getBoundingClientRect();
      view.current = zoomPlanView(
        current,
        { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
        event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP,
      );
      draw.current();
    };
    box.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      observer?.disconnect();
      box.removeEventListener('wheel', onWheel);
    };
  }, []);

  const localPoint = (event: { clientX: number; clientY: number }): IPointer => {
    const bounds = host.current?.getBoundingClientRect();
    return { x: event.clientX - (bounds?.left ?? 0), y: event.clientY - (bounds?.top ?? 0) };
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, { ...localPoint(event) });
    if (pointers.current.size === 1) moved.current = false;
    else moved.current = true;
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const known = pointers.current.get(event.pointerId);
    const current = view.current;
    if (!known || current === null) return;
    const next = localPoint(event);
    if (pointers.current.size >= 2) {
      const other = [...pointers.current.entries()].find(([id]) => id !== event.pointerId)?.[1];
      if (other) {
        const before = Math.hypot(known.x - other.x, known.y - other.y);
        const after = Math.hypot(next.x - other.x, next.y - other.y);
        const center = { x: (next.x + other.x) / 2, y: (next.y + other.y) / 2 };
        let updated = panPlanView(current, (next.x - known.x) / 2, (next.y - known.y) / 2);
        if (before > 0 && after > 0) updated = zoomPlanView(updated, center, after / before);
        view.current = updated;
      }
    } else {
      if (!moved.current && Math.hypot(next.x - known.x, next.y - known.y) <= CLICK_SLOP_PX) return;
      moved.current = true;
      view.current = panPlanView(current, next.x - known.x, next.y - known.y);
    }
    known.x = next.x;
    known.y = next.y;
    draw.current();
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const current = view.current;
    if (moved.current || current === null || event.type === 'pointercancel') return;
    const { point } = snapToVertex2d(localPoint(event), latest.current.plan.vertices, current);
    latest.current.onPick(point);
  };

  return (
    <div
      ref={host}
      role="application"
      aria-label={label}
      data-testid="site-pin-plan"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className="relative h-[34dvh] min-h-[220px] w-full touch-none overflow-hidden rounded-[var(--radius-sm)] border border-border lg:h-[44dvh]"
    >
      <canvas ref={canvas} className="block cursor-crosshair" />
    </div>
  );
};
