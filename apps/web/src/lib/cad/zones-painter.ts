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

import {
  ZONE_CATEGORIES,
  zoneCategory,
  zoneCategoryToken,
  type ZoneCategory,
} from './zone-categories';
import { doorLabelFits, fitRoomLabel, LABEL_LINE_HEIGHT, roomLabelLines } from './zone-labels';
import { apartmentColorIndex, APARTMENT_PALETTE_SIZE, type IZoneView } from './zone-view';
import { zoneCanvasLabel, zoneCentroid, type ZoneKind } from './zones';

export interface IZoneColors {
  /** Цвет черновика помещения квартиры при разметке. */
  readonly apartment: string;
  /** Цвет по категории помещения (режим «по типу»). */
  readonly categories: Readonly<Record<ZoneCategory, string>>;
  /** Палитра квартир (режим «по квартирам»). */
  readonly apartments: readonly string[];
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
  /** Выделенная зона: рисуется толще и не скрывается. */
  readonly activeId: string | null;
  /** Окраска, скрытые категории и подписи. */
  readonly view: IZoneView;
}

const LINE_WIDTH = 2;
const ACTIVE_LINE_WIDTH = 4;
const FILL_ALPHA = 0.18;
const ACTIVE_FILL_ALPHA = 0.3;
const TICK = 6;
const FONT = '600 11px system-ui, sans-serif';
/** Запас отсечения на толщину штриха и подпись. */
const MARGIN = 80;

/** Читает цвета зон из токенов темы (на светлой бумаге чертежа в обеих темах). */
export const readZoneColors = (): IZoneColors => {
  if (typeof window === 'undefined') {
    return {
      apartment: 'CanvasText',
      categories: Object.fromEntries(
        ZONE_CATEGORIES.map((category) => [category, 'CanvasText']),
      ) as Record<ZoneCategory, string>,
      apartments: Array.from({ length: APARTMENT_PALETTE_SIZE }, () => 'CanvasText'),
      mop: 'CanvasText',
      door: 'CanvasText',
      paper: 'Canvas',
      ink: 'CanvasText',
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  const categories = Object.fromEntries(
    ZONE_CATEGORIES.map((category) => [category, token(zoneCategoryToken(category), 'CanvasText')]),
  ) as Record<ZoneCategory, string>;
  return {
    apartment: token('--cad-zone-apartment', 'CanvasText'),
    categories,
    apartments: Array.from({ length: APARTMENT_PALETTE_SIZE }, (_, index) =>
      token(`--cad-zone-apt-${index + 1}`, 'CanvasText'),
    ),
    mop: token('--cad-zone-mop', 'CanvasText'),
    door: token('--cad-zone-door', 'CanvasText'),
    paper: token('--canvas', 'Canvas'),
    ink: token('--sheet-ink', 'CanvasText'),
  };
};

export const zoneColor = (colors: IZoneColors, kind: ZoneKind): string =>
  kind === 'room_apartment'
    ? colors.apartment
    : kind === 'room_mop'
      ? colors.mop
      : kind === 'parking_space'
        ? colors.categories.parking
        : colors.door;

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

const measureWith = (context: CanvasRenderingContext2D) => (text: string) => {
  context.font = FONT;
  return context.measureText(text).width;
};

/** Строки подписи по центру `at`, с подложкой цвета бумаги. */
const drawLabelLines = (
  context: CanvasRenderingContext2D,
  lines: readonly string[],
  at: ScreenPoint,
  colors: IZoneColors,
) => {
  context.font = FONT;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.lineJoin = 'round';
  context.lineWidth = 3;
  lines.forEach((line, index) => {
    const y = at.y + (index - (lines.length - 1) / 2) * LABEL_LINE_HEIGHT;
    context.strokeStyle = colors.paper;
    context.strokeText(line, at.x, y);
    context.fillStyle = colors.ink;
    context.fillText(line, at.x, y);
  });
};

/** Цвет помещения: по квартире или по категории; МОП и дверь - свои цвета в обоих режимах. */
const roomColor = (
  zone: CadZoneRead,
  data: IZonePaintData,
  apartments: ReadonlyMap<string, number>,
): string => {
  const { colors, view } = data;
  if (zone.kind === 'room_mop') return colors.categories[zoneCategory(zone)];
  if (view.colorMode === 'apartment' && zone.apartment_no !== null) {
    const index = apartments.get(zone.apartment_no);
    if (index !== undefined) return colors.apartments[index] ?? colors.categories.other;
  }
  return colors.categories[zoneCategory(zone)];
};

const drawRoom = (
  context: CanvasRenderingContext2D,
  shape: IShape,
  data: IZonePaintData,
  apartments: ReadonlyMap<string, number>,
) => {
  const color = roomColor(shape.zone, data, apartments);
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
  if (!data.view.labelsOn) return;
  const lines = fitRoomLabel(
    roomLabelLines(shape.zone, data.view.labels),
    { width: shape.maxX - shape.minX, height: shape.maxY - shape.minY },
    measureWith(context),
  );
  if (lines.length > 0) drawLabelLines(context, lines, shape.center, data.colors);
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
  const text = zoneCanvasLabel(shape.zone);
  if (data.view.labelsOn && doorLabelFits(text, length, measureWith(context))) {
    drawLabelLines(
      context,
      [text],
      { x: (first.x + second.x) / 2 + nx * 2, y: (second.y + first.y) / 2 + ny * 2 },
      data.colors,
    );
  }
};

/**
 * Рисовальщик зон. `clear: true` - слой только с зонами (чистит холст сам); `false` - зоны поверх
 * другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createZonesPainter = (
  data: IZonePaintData,
  options: { readonly clear: boolean },
): LayerPainter => {
  const apartments = apartmentColorIndex(data.zones);
  // Скрытая категория не рисуется и не держит слой; выделенная зона видна всегда.
  const shown = data.zones.filter(
    (zone) => zone.id === data.activeId || !data.view.hidden.has(zoneCategory(zone)),
  );
  return {
    paint: (context, placement, ratio, area) => {
      const rects = options.clear
        ? beginLayerPaint(context, ratio, area, MARGIN)
        : beginOverPaint(context, ratio, area);
      // Выделенная зона - последней, чтобы контур не прятался под соседними.
      const ordered = [...shown].sort(
        (first, second) => Number(first.id === data.activeId) - Number(second.id === data.activeId),
      );
      for (const zone of ordered) {
        const shape = shapeOf(zone, placement);
        if (!hits(shape, rects)) continue;
        if (zone.kind === 'door') drawDoor(context, shape, data);
        else drawRoom(context, shape, data, apartments);
      }
      context.restore();
    },

    touches: (placement, ratio, area) => {
      const rects = visibleRects(area, ratio, MARGIN);
      return shown.some((zone) => hits(shapeOf(zone, placement), rects));
    },
  };
};
