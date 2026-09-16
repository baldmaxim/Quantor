'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type PointerEvent,
} from 'react';

import {
  drawSheet,
  hitTestShapes,
  STYLE_TOKEN,
  type IMepShape,
  type MepLayer,
  type ShapeStyle,
} from '@/lib/mep/sheet';
import { toNormalizedPoint, type SheetPlacement } from '@/lib/viewer/coordinates';

interface IMepSheetCanvasProps {
  readonly shapes: readonly IMepShape[];
  /** Высота к ширине листа. */
  readonly aspect: number;
  readonly dimmed: ReadonlySet<MepLayer>;
  readonly selectedId: string | null;
  readonly relatedIds: ReadonlySet<string>;
  readonly onSelect: (shape: IMepShape) => void;
  readonly label: string;
}

const PAD = 16;

const readColors = (element: HTMLElement) => {
  const style = getComputedStyle(element);
  const token = (name: string) => style.getPropertyValue(name).trim() || 'currentColor';
  const shapes = Object.fromEntries(
    Object.entries(STYLE_TOKEN).map(([key, name]) => [key, token(name)]),
  ) as Record<ShapeStyle, string>;
  return {
    ...shapes,
    page: token('--canvas'),
    pageInk: token('--canvas-ink'),
    focus: token('--accent'),
  };
};

/**
 * Синтетический лист: Canvas2D, без pdf.js и без камеры просмотрщика. Панорамы и зума нет —
 * лист целиком вписан в ширину панели. Доступ с клавиатуры даёт список элементов рядом.
 */
export const MepSheetCanvas: FC<IMepSheetCanvasProps> = ({
  shapes,
  aspect,
  dimmed,
  selectedId,
  relatedIds,
  onSelect,
  label,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const height = Math.round((width - PAD * 2) * aspect + PAD * 2);
  const placement = useMemo<SheetPlacement>(
    () => ({
      x: PAD,
      y: PAD,
      width: Math.max(width - PAD * 2, 0),
      height: Math.max(height - PAD * 2, 0),
      rotation: 0,
    }),
    [width, height],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.setProperty('width', `${width}px`);
    canvas.style.setProperty('height', `${height}px`);
    drawSheet(
      context,
      placement,
      { shapes, dimmed, selectedId, relatedIds, colors: readColors(canvas) },
      dpr,
    );
  }, [shapes, dimmed, selectedId, relatedIds, width, height, placement]);

  const handlePointer = useCallback(
    (event: PointerEvent<HTMLCanvasElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const point = toNormalizedPoint(
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
        placement,
      );
      const active = shapes.filter((shape) => !dimmed.has(shape.layer));
      const hit =
        hitTestShapes(active, point, placement) ?? hitTestShapes(shapes, point, placement);
      if (hit) onSelect(hit);
    },
    [shapes, dimmed, onSelect, placement],
  );

  return (
    <div ref={containerRef} className="w-full">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={label}
        className="block cursor-pointer rounded-[var(--radius-sm)] bg-surface-sunken"
        onPointerDown={handlePointer}
      />
    </div>
  );
};
