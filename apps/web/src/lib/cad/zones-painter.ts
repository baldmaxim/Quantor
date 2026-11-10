/**
 * Рисовальщик зон листа для просмотрщика (Canvas2D, ADR-0015).
 *
 * Зоны идут тем же слоем, что и геометрия CAD, и подчиняются протоколу слоя (ADR-0025): полосы
 * панорамы, отсечение по охвату, `touches` не строже `paint`. Помещение - заливка с прозрачностью
 * и контур с подписью в центре тяжести; дверь - отрезок поперёк проёма с засечками на концах.
 */

import type { CadZoneRead } from '@quantor/api-client';

import { toScreenPoint, type ScreenPoint, type SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { PixelRect } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { zoneCanvasLabel, zoneCentroid, type ZoneKind } from './zones';

export interface IZoneColors {
  readonly apartment: string;
  readonly mop: string;
  readonly door: string;
  /** Подложка подписи (бумага листа). */
  readonly paper: string;
  /** Цвет текста подписи. */
  readonly ink: string;
}

export interface IZonePaintData {
  readonly zones: readonly CadZoneRead[];
  readonly colors: IZoneColors;
  /** Выделенная зона: рисуется толще. */
  readonly activeId: string | null;
}

const LINE_WIDTH = 2;
const ACTIVE_LINE_WIDTH = 4;
const FILL_ALPHA = 0.18;
const ACTIVE_FILL_ALPHA = 0.3;
const TICK = 6;
const FONT = '600 12px system-ui, sans-serif';
/** Запас отсечения на толщину штриха и подпись. */
const MARGIN = 80;

/** Читает цвета зон из токенов темы (на светлой бумаге чертежа в обеих темах). */
export const readZoneColors = (): IZoneColors => {
  if (typeof window === 'undefined') {
    return {
      apartment: 'CanvasText',
      mop: 'CanvasText',
      door: 'CanvasText',
      paper: 'Canvas',
      ink: 'CanvasText',
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    apartment: token('--cad-zone-apartment', 'CanvasText'),
    mop: token('--cad-zone-mop', 'CanvasText'),
    door: token('--cad-zone-door', 'CanvasText'),
    paper: token('--canvas', 'Canvas'),
    ink: token('--sheet-ink', 'CanvasText'),
  };
};

export const zoneColor = (colors: IZoneColors, kind: ZoneKind): string =>
  kind === 'room_apartment' ? colors.apartment : kind === 'room_mop' ? colors.mop : colors.door;

interface IShape {
  readonly zone: CadZoneRead;
  readonly screen: readonly ScreenPoint[];
  /** Центр тяжести контура (место подписи помещения). */
  readonly center: ScreenPoint;
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

const shapeOf = (zone: CadZoneRead, placement: SheetPlacement): IShape => {
  const screen = zone.points.map(([x, y]) => toScreenPoint({ x, y }, placement));
  const xs = screen.map((point) => point.x);
  const ys = screen.map((point) => point.y);
  return {
    zone,
    screen,
    center: toScreenPoint(zoneCentroid(zone.points), placement),
    minX: Math.min(...xs),
    minY: Math.min(...ys),
    maxX: Math.max(...xs),
    maxY: Math.max(...ys),
  };
};

const hits = (
  shape: IShape,
  rects: readonly { x: number; y: number; width: number; height: number }[],
) => boundsIntersectAny(shape.minX, shape.minY, shape.maxX, shape.maxY, rects);

/** Подготовка слоя поверх уже нарисованного: ограничение полосами, без очистки. */
const beginOverPaint = (
  context: CanvasRenderingContext2D,
  ratio: number,
  area: readonly PixelRect[] | null,
) => {
  const scale = ratio > 0 ? ratio : 1;
  const { canvas } = context;
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.save();
  const rects = area ?? [{ x: 0, y: 0, width: canvas.width, height: canvas.height }];
  if (area) {
    context.beginPath();
    for (const rect of area) context.rect(rect.x, rect.y, rect.width, rect.height);
    context.clip();
  }
  context.scale(scale, scale);
  return visibleRects(rects, scale, MARGIN);
};

const traceRoom = (context: CanvasRenderingContext2D, screen: readonly ScreenPoint[]) => {
  context.beginPath();
  screen.forEach((point, index) => {
    if (index === 0) context.moveTo(point.x, point.y);
    else context.lineTo(point.x, point.y);
  });
  context.closePath();
};

const drawLabel = (
  context: CanvasRenderingContext2D,
  text: string,
  at: ScreenPoint,
  colors: IZoneColors,
) => {
  if (text === '') return;
  context.font = FONT;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.lineJoin = 'round';
  context.lineWidth = 3;
  context.strokeStyle = colors.paper;
  context.strokeText(text, at.x, at.y);
  context.fillStyle = colors.ink;
  context.fillText(text, at.x, at.y);
};

const drawRoom = (context: CanvasRenderingContext2D, shape: IShape, data: IZonePaintData) => {
  const color = zoneColor(data.colors, shape.zone.kind);
  const active = shape.zone.id === data.activeId;
  traceRoom(context, shape.screen);
  context.globalAlpha = active ? ACTIVE_FILL_ALPHA : FILL_ALPHA;
  context.fillStyle = color;
  context.fill();
  context.globalAlpha = 1;
  context.strokeStyle = color;
  context.lineWidth = active ? ACTIVE_LINE_WIDTH : LINE_WIDTH;
  context.lineJoin = 'round';
  context.stroke();
  drawLabel(context, zoneCanvasLabel(shape.zone), shape.center, data.colors);
};

const drawDoor = (context: CanvasRenderingContext2D, shape: IShape, data: IZonePaintData) => {
  const [first, second] = shape.screen;
  if (!first || !second) return;
  const color = zoneColor(data.colors, 'door');
  const active = shape.zone.id === data.activeId;
  context.strokeStyle = color;
  context.lineWidth = active ? ACTIVE_LINE_WIDTH + 1 : LINE_WIDTH + 1;
  context.lineCap = 'round';
  context.beginPath();
  context.moveTo(first.x, first.y);
  context.lineTo(second.x, second.y);
  context.stroke();
  // Засечки перпендикулярно отрезку: видно, где кончается проём.
  const dx = second.x - first.x;
  const dy = second.y - first.y;
  const length = Math.hypot(dx, dy) || 1;
  const nx = (-dy / length) * TICK;
  const ny = (dx / length) * TICK;
  context.lineWidth = LINE_WIDTH;
  context.beginPath();
  for (const end of [first, second]) {
    context.moveTo(end.x - nx, end.y - ny);
    context.lineTo(end.x + nx, end.y + ny);
  }
  context.stroke();
  drawLabel(
    context,
    zoneCanvasLabel(shape.zone),
    { x: (first.x + second.x) / 2 + nx * 2, y: (second.y + first.y) / 2 + ny * 2 },
    data.colors,
  );
};

/**
 * Рисовальщик зон. `clear: true` - слой только с зонами (чистит холст сам); `false` - зоны поверх
 * другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createZonesPainter = (
  data: IZonePaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    // Выделенная зона - последней, чтобы контур не прятался под соседними.
    const ordered = [...data.zones].sort(
      (first, second) => Number(first.id === data.activeId) - Number(second.id === data.activeId),
    );
    for (const zone of ordered) {
      const shape = shapeOf(zone, placement);
      if (!hits(shape, rects)) continue;
      if (zone.kind === 'door') drawDoor(context, shape, data);
      else drawRoom(context, shape, data);
    }
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return data.zones.some((zone) => hits(shapeOf(zone, placement), rects));
  },
});
