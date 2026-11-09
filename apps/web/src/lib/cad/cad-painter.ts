/**
 * Рисовальщик слоя CAD для просмотрщика (Canvas2D, ADR-0015).
 *
 * Слой подключается к `DrawingViewport` как отдельный холст размером с область просмотра и
 * подчиняется общему правилу (ADR-0025): на панораме пиксели сдвигаются, а сюда приходят только
 * открывшиеся полосы. Пути отсекаются по охвату - так же при рисовании и при вопросе «есть ли
 * в полосе что рисовать»: `touches` не строже `paint`.
 *
 * Координаты путей - нормализованные от левого верхнего угла листа. Поворот листа в
 * `placeViewportPage` всегда нулевой: отрисовщик применил `/Rotate` сам, повторно не применяем.
 */

import type { NormalizedRect, SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { PixelRect } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import type { INormalizedPath } from './frame';

export interface ICadPaintData {
  readonly paths: readonly INormalizedPath[];
  /** Индексы слоёв, которые показаны. */
  readonly visibleLayers: ReadonlySet<number>;
  /** Непрозрачность геометрии, 0-1. */
  readonly opacity: number;
  /** Цвета приходят из токенов темы. */
  readonly ink: string;
  /** Фон листа для автономного просмотра: у PDF бумага своя. `null` - не рисовать. */
  readonly paper: string | null;
  /** Контекст масштаба: прямоугольник и его цвет. */
  readonly crop: { readonly rect: NormalizedRect; readonly color: string } | null;
}

const LINE_WIDTH = 1;
const FILL_ALPHA = 0.18;
const CROP_LINE_WIDTH = 2;
const CROP_DASH = [8, 5];
/** Запас отсечения на толщину штриха. */
const MARGIN = CROP_LINE_WIDTH;

interface IScreenBox {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

const boxOf = (
  bounds: readonly [number, number, number, number],
  placement: SheetPlacement,
): IScreenBox => ({
  minX: placement.x + bounds[0] * placement.width,
  minY: placement.y + bounds[1] * placement.height,
  maxX: placement.x + bounds[2] * placement.width,
  maxY: placement.y + bounds[3] * placement.height,
});

const cropBox = (rect: NormalizedRect, placement: SheetPlacement): IScreenBox =>
  boxOf(
    [
      Math.min(rect[0], rect[2]),
      Math.min(rect[1], rect[3]),
      Math.max(rect[0], rect[2]),
      Math.max(rect[1], rect[3]),
    ],
    placement,
  );

const hits = (
  box: IScreenBox,
  rects: readonly { x: number; y: number; width: number; height: number }[],
) => boundsIntersectAny(box.minX, box.minY, box.maxX, box.maxY, rects);

const tracePath = (
  context: CanvasRenderingContext2D,
  path: INormalizedPath,
  placement: SheetPlacement,
): void => {
  const { points } = path;
  context.moveTo(
    placement.x + (points[0] ?? 0) * placement.width,
    placement.y + (points[1] ?? 0) * placement.height,
  );
  for (let index = 2; index + 1 < points.length; index += 2) {
    context.lineTo(
      placement.x + (points[index] ?? 0) * placement.width,
      placement.y + (points[index + 1] ?? 0) * placement.height,
    );
  }
  if (path.closed) context.closePath();
};

const visiblePaths = (
  data: ICadPaintData,
  placement: SheetPlacement,
  rects: readonly { x: number; y: number; width: number; height: number }[],
): INormalizedPath[] =>
  data.paths.filter(
    (path) => data.visibleLayers.has(path.layer) && hits(boxOf(path.bounds, placement), rects),
  );

export const createCadPainter = (data: ICadPaintData): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = beginLayerPaint(context, ratio, area, MARGIN);

    if (data.paper !== null) {
      context.fillStyle = data.paper;
      context.fillRect(placement.x, placement.y, placement.width, placement.height);
    }

    const shown = visiblePaths(data, placement, rects);
    if (shown.length > 0) {
      context.globalAlpha = data.opacity;
      context.strokeStyle = data.ink;
      context.fillStyle = data.ink;
      context.lineWidth = LINE_WIDTH;
      context.lineJoin = 'round';

      // Заливки отдельным проходом и с малой плотностью: под ними должны читаться линии.
      const fills = shown.filter((path) => path.fill && path.closed);
      if (fills.length > 0) {
        context.globalAlpha = data.opacity * FILL_ALPHA;
        context.beginPath();
        for (const path of fills) tracePath(context, path, placement);
        context.fill();
        context.globalAlpha = data.opacity;
      }

      context.beginPath();
      for (const path of shown) tracePath(context, path, placement);
      context.stroke();
    }

    if (data.crop) {
      context.globalAlpha = 1;
      context.strokeStyle = data.crop.color;
      context.lineWidth = CROP_LINE_WIDTH;
      context.setLineDash(CROP_DASH);
      const box = cropBox(data.crop.rect, placement);
      context.strokeRect(box.minX, box.minY, box.maxX - box.minX, box.maxY - box.minY);
      context.setLineDash([]);
    }

    context.restore();
  },

  touches: (placement, ratio, area: readonly PixelRect[]) => {
    const rects = visibleRects(area, ratio, MARGIN);
    if (data.paper !== null && hits(boxOf([0, 0, 1, 1], placement), rects)) return true;
    if (data.crop && hits(cropBox(data.crop.rect, placement), rects)) return true;
    return visiblePaths(data, placement, rects).length > 0;
  },
});
