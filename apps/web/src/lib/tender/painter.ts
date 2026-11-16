/**
 * Рисовальщик слоя «Расчёты» для просмотрщика (Canvas2D, ADR-0015, ADR-0051).
 *
 * Идёт тем же слоем, что геометрия CAD, и подчиняется тому же протоколу слоя (ADR-0025): полосы
 * панорамы, отсечение по охвату, `touches` не строже `paint`. Рисуется поверх уже нарисованного.
 * Толщина штриха и размер значков - в экранных пикселях, от зума не зависят. Подписи `mark` - только
 * при крупном зуме. Координаты - нормализованные от левого верхнего угла листа.
 */

import type { CalcElement, CalcPolyline } from '@quantor/api-client';

import { beginOverPaint } from '@/lib/cad/remarks-painter';
import type { SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import type { ITenderRef } from './info';

export interface ITenderPath {
  readonly kind: CalcPolyline['kind'];
  /** Плоский список x0, y0, x1, y1, … в нормализованных координатах листа. */
  readonly points: Float64Array;
  readonly bounds: readonly [number, number, number, number];
  /** Подпись `mark`, если задана. */
  readonly label: string | null;
  readonly color: string;
  readonly ref: ITenderRef;
}

export interface ITenderMark {
  readonly type: CalcElement['type'];
  readonly x: number;
  readonly y: number;
  /** Направление оси элемента на экране (единичный вектор). */
  readonly dx: number;
  readonly dy: number;
  readonly label: string | null;
  readonly color: string;
  readonly ref: ITenderRef;
}

export interface ITenderPaintData {
  readonly paths: readonly ITenderPath[];
  readonly marks: readonly ITenderMark[];
  /** Высота листа к ширине: нормализованные расстояния по Y и X соизмеримы только с ней. */
  readonly aspect: number;
  /** Цвет выделения (токен `--accent`). */
  readonly accent: string;
  /** Подложка подписей (токен `--surface`): текст читается на любом чертеже. */
  readonly halo: string;
  /** Выбранный объект: рисуется толще и цветом выделения. */
  readonly selected: ITenderRef | null;
}

/** Толщина штриха полилинии по виду, px. */
export const LINE_WIDTHS: Readonly<Record<CalcPolyline['kind'], number>> = {
  route: 2,
  jumper: 1.5,
  riser: 2,
  leadin: 1.5,
  cable: 1,
  tray: 4,
  duct: 4,
};
const SELECTED_EXTRA_PX = 2;
const GLYPH_HALF_PX = 5;
const RISER_RADIUS_PX = 4;
const SLEEVE_HALF_PX = 5;
const FONT = '600 11px system-ui, sans-serif';
const LABEL_OFFSET_PX = 7;
/** Подписи `mark` показываются, когда лист на экране шире этого, px (крупный зум). */
export const LABEL_MIN_SHEET_PX = 3500;
/** Запас отсечения на толщину штриха, значок и подпись. */
const MARGIN = 40;

interface IBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

const boxOf = (
  bounds: readonly [number, number, number, number],
  placement: SheetPlacement,
): readonly [number, number, number, number] => [
  placement.x + bounds[0] * placement.width,
  placement.y + bounds[1] * placement.height,
  placement.x + bounds[2] * placement.width,
  placement.y + bounds[3] * placement.height,
];

const hitsBounds = (
  bounds: readonly [number, number, number, number],
  placement: SheetPlacement,
  rects: readonly IBox[],
): boolean => {
  const [minX, minY, maxX, maxY] = boxOf(bounds, placement);
  return boundsIntersectAny(minX, minY, maxX, maxY, rects);
};

const sameObject = (ref: ITenderRef, selected: ITenderRef | null): boolean =>
  selected !== null && ref.object.data === selected.object.data;

const drawLabel = (
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  color: string,
  halo: string,
): void => {
  context.font = FONT;
  context.textBaseline = 'middle';
  context.lineJoin = 'round';
  context.lineWidth = 3;
  context.strokeStyle = halo;
  context.strokeText(text, x, y);
  context.fillStyle = color;
  context.fillText(text, x, y);
};

const drawPath = (
  context: CanvasRenderingContext2D,
  path: ITenderPath,
  placement: SheetPlacement,
  data: ITenderPaintData,
  showLabels: boolean,
): void => {
  const selected = sameObject(path.ref, data.selected);
  const color = selected ? data.accent : path.color;
  const { points } = path;
  const count = points.length / 2;
  const px = (index: number): number => placement.x + (points[index * 2] ?? 0) * placement.width;
  const py = (index: number): number => placement.y + (points[index * 2 + 1] ?? 0) * placement.height;
  const width = LINE_WIDTHS[path.kind] + (selected ? SELECTED_EXTRA_PX : 0);

  // Все вершины в одной точке плана (стояк): круг, а не штрих нулевой длины.
  let flat = true;
  for (let index = 1; index < count && flat; index += 1) {
    flat = Math.abs(px(index) - px(0)) < 0.5 && Math.abs(py(index) - py(0)) < 0.5;
  }
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = width;
  context.lineJoin = 'round';
  context.lineCap = path.kind === 'tray' || path.kind === 'duct' ? 'butt' : 'round';
  if (flat || path.kind === 'riser') {
    context.beginPath();
    context.arc(px(0), py(0), RISER_RADIUS_PX + (selected ? 1 : 0), 0, Math.PI * 2);
    context.globalAlpha = 0.35;
    context.fill();
    context.globalAlpha = 1;
    context.stroke();
  }
  if (!flat) {
    context.beginPath();
    context.moveTo(px(0), py(0));
    for (let index = 1; index < count; index += 1) context.lineTo(px(index), py(index));
    context.stroke();
  }
  if (showLabels && path.label !== null) {
    drawLabel(context, path.label, px(0) + LABEL_OFFSET_PX, py(0) - LABEL_OFFSET_PX, color, data.halo);
  }
};

const drawMark = (
  context: CanvasRenderingContext2D,
  mark: ITenderMark,
  placement: SheetPlacement,
  data: ITenderPaintData,
  showLabels: boolean,
): void => {
  const selected = sameObject(mark.ref, data.selected);
  const color = selected ? data.accent : mark.color;
  const x = placement.x + mark.x * placement.width;
  const y = placement.y + mark.y * placement.height;
  const half = GLYPH_HALF_PX + (selected ? 1.5 : 0);
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = selected ? 2.5 : 1.5;
  context.lineCap = 'round';
  context.lineJoin = 'miter';
  context.beginPath();
  if (mark.type === 'terminal' || mark.type === 'equipment') {
    context.rect(x - half, y - half, half * 2, half * 2);
    context.globalAlpha = 0.35;
    context.fill();
    context.globalAlpha = 1;
  } else if (mark.type === 'valve' || mark.type === 'fitting') {
    context.moveTo(x, y - half);
    context.lineTo(x + half, y);
    context.lineTo(x, y + half);
    context.lineTo(x - half, y);
    context.closePath();
    if (mark.type === 'valve') {
      context.globalAlpha = 0.35;
      context.fill();
      context.globalAlpha = 1;
    }
  } else {
    // Гильза: короткий штрих поперёк оси.
    context.moveTo(x - mark.dy * SLEEVE_HALF_PX, y + mark.dx * SLEEVE_HALF_PX);
    context.lineTo(x + mark.dy * SLEEVE_HALF_PX, y - mark.dx * SLEEVE_HALF_PX);
  }
  context.stroke();
  if (showLabels && mark.label !== null) {
    drawLabel(context, mark.label, x + half + 3, y, color, data.halo);
  }
};

/**
 * Рисовальщик слоя «Расчёты». `clear: true` - слой только с расчётами (чистит холст сам); `false` -
 * поверх других рисовальщиков того же слоя (см. `composePainters`).
 */
export const createTenderPainter = (
  data: ITenderPaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    const showLabels = placement.width >= LABEL_MIN_SHEET_PX;
    // Выбранный объект рисуется последним: он не прячется под соседями.
    const late: (() => void)[] = [];
    for (const path of data.paths) {
      if (!hitsBounds(path.bounds, placement, rects)) continue;
      if (sameObject(path.ref, data.selected)) late.push(() => drawPath(context, path, placement, data, showLabels));
      else drawPath(context, path, placement, data, showLabels);
    }
    for (const mark of data.marks) {
      const bounds = [mark.x, mark.y, mark.x, mark.y] as const;
      if (!hitsBounds(bounds, placement, rects)) continue;
      if (sameObject(mark.ref, data.selected)) late.push(() => drawMark(context, mark, placement, data, showLabels));
      else drawMark(context, mark, placement, data, showLabels);
    }
    for (const draw of late) draw();
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return (
      data.paths.some((path) => hitsBounds(path.bounds, placement, rects)) ||
      data.marks.some((mark) => hitsBounds([mark.x, mark.y, mark.x, mark.y], placement, rects))
    );
  },
});

const segmentDistance = (
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number => {
  const abx = bx - ax;
  const aby = by - ay;
  const lengthSq = abx * abx + aby * aby;
  const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * abx + (py - ay) * aby) / lengthSq));
  return Math.hypot(px - (ax + t * abx), py - (ay + t * aby));
};

/**
 * Объект расчёта под точкой листа (нормализованные координаты); допуск `tolerance` - в долях ширины
 * листа. Значок прибора и арматуры главнее линии под ним; из нескольких - ближайший. `null` - пусто.
 */
export const hitTender = (
  data: ITenderPaintData,
  point: { readonly x: number; readonly y: number },
  tolerance: number,
): ITenderRef | null => {
  const { aspect } = data;
  let best: ITenderRef | null = null;
  let bestDistance = tolerance;
  for (const mark of data.marks) {
    const distance = Math.hypot(point.x - mark.x, (point.y - mark.y) * aspect);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = mark.ref;
    }
  }
  if (best !== null) return best;
  for (const path of data.paths) {
    const [minX, minY, maxX, maxY] = path.bounds;
    if (
      point.x < minX - tolerance ||
      point.x > maxX + tolerance ||
      point.y < minY - tolerance / aspect ||
      point.y > maxY + tolerance / aspect
    ) {
      continue;
    }
    const { points } = path;
    const count = points.length / 2;
    for (let index = 0; index < count; index += 1) {
      const ax = points[index * 2] ?? 0;
      const ay = (points[index * 2 + 1] ?? 0) * aspect;
      const next = Math.min(index + 1, count - 1);
      const bx = points[next * 2] ?? 0;
      const by = (points[next * 2 + 1] ?? 0) * aspect;
      const distance = segmentDistance(point.x, point.y * aspect, ax, ay, bx, by);
      if (distance <= bestDistance) {
        bestDistance = distance;
        best = path.ref;
      }
    }
  }
  return best;
};
