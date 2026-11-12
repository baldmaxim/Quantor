/**
 * Рисовальщик отметок замечаний для просмотрщика (Canvas2D, ADR-0015).
 *
 * Отметки идут тем же слоем, что и геометрия CAD, и подчиняются тому же протоколу слоя
 * (ADR-0025): полосы панорамы, отсечение по охвату, `touches` не строже `paint`. Открытое и
 * проверенное замечание различаются не только цветом: проверенное нарисовано пунктиром и с
 * галочкой в номере.
 */

import type { NormalizedRect, SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { PixelRect } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import type { RemarkStatus } from './remarks';

export interface IRemarkMark {
  readonly id: string;
  /** Номер в списке замечаний. */
  readonly number: number;
  readonly status: RemarkStatus;
  /** Доли листа: [x0, y0, x1, y1]. */
  readonly rect: NormalizedRect;
}

export interface IRemarkColors {
  readonly open: string;
  readonly resolved: string;
  /** Цвет цифры на плашке открытого замечания. */
  readonly onOpen: string;
  /** Подложка плашки проверенного замечания. */
  readonly paper: string;
}

export interface IRemarkPaintData {
  readonly marks: readonly IRemarkMark[];
  readonly colors: IRemarkColors;
  /** Замечание, на которое смотрят: рисуется толще. */
  readonly activeId: string | null;
}

const LINE_WIDTH = 2;
const ACTIVE_LINE_WIDTH = 3.5;
const RESOLVED_DASH = [7, 5];
const FILL_ALPHA = 0.1;
const BADGE_HEIGHT = 18;
const BADGE_PAD = 5;
const FONT = '600 12px system-ui, sans-serif';
/** Запас отсечения на толщину штриха и плашку номера. */
const MARGIN = 24;

interface IBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

const boxOf = (rect: NormalizedRect, placement: SheetPlacement): IBox => ({
  x: placement.x + rect[0] * placement.width,
  y: placement.y + rect[1] * placement.height,
  width: (rect[2] - rect[0]) * placement.width,
  height: (rect[3] - rect[1]) * placement.height,
});

const hits = (box: IBox, rects: readonly IBox[]): boolean =>
  boundsIntersectAny(box.x, box.y, box.x + box.width, box.y + box.height, rects);

/** Подготовка слоя, который лежит поверх уже нарисованного: ограничение полосами, без очистки. */
export const beginOverPaint = (
  context: CanvasRenderingContext2D,
  ratio: number,
  area: readonly PixelRect[] | null,
): readonly IBox[] => {
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

const drawMark = (
  context: CanvasRenderingContext2D,
  mark: IRemarkMark,
  box: IBox,
  data: IRemarkPaintData,
): void => {
  const resolved = mark.status === 'resolved';
  const color = resolved ? data.colors.resolved : data.colors.open;
  const active = mark.id === data.activeId;

  context.globalAlpha = FILL_ALPHA;
  context.fillStyle = color;
  context.fillRect(box.x, box.y, box.width, box.height);

  context.globalAlpha = 1;
  context.strokeStyle = color;
  context.lineWidth = active ? ACTIVE_LINE_WIDTH : LINE_WIDTH;
  context.setLineDash(resolved ? RESOLVED_DASH : []);
  context.strokeRect(box.x, box.y, box.width, box.height);
  context.setLineDash([]);

  // Плашка с номером у левого верхнего угла: размер в экранных пикселях, не зависит от зума.
  const label = resolved ? `${mark.number} ✓` : String(mark.number);
  context.font = FONT;
  context.textBaseline = 'middle';
  const width = Math.ceil(context.measureText(label).width) + BADGE_PAD * 2;
  const top = box.y - BADGE_HEIGHT < 0 ? box.y : box.y - BADGE_HEIGHT;
  context.fillStyle = resolved ? data.colors.paper : color;
  context.fillRect(box.x, top, width, BADGE_HEIGHT);
  context.strokeRect(box.x, top, width, BADGE_HEIGHT);
  context.fillStyle = resolved ? color : data.colors.onOpen;
  context.fillText(label, box.x + BADGE_PAD, top + BADGE_HEIGHT / 2);
};

/**
 * Рисовальщик отметок. `clear: true` - слой только с отметками (чистит холст сам); `false` -
 * отметки поверх другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createRemarksPainter = (
  data: IRemarkPaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    for (const mark of data.marks) {
      const box = boxOf(mark.rect, placement);
      if (hits(box, rects)) drawMark(context, mark, box, data);
    }
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return data.marks.some((mark) => hits(boxOf(mark.rect, placement), rects));
  },
});

/**
 * Несколько рисовальщиков в одном слое: рисуются по порядку, первый чистит холст. `null` пропускается.
 * Нет ни одного - `null` (слоя нет).
 */
export const composePainters = (
  ...painters: readonly (LayerPainter | null)[]
): LayerPainter | null => {
  const list = painters.filter((painter): painter is LayerPainter => painter !== null);
  const [only, ...rest] = list;
  if (only === undefined) return null;
  if (rest.length === 0) return only;
  return {
    paint: (context, placement, ratio, area) => {
      for (const painter of list) painter.paint(context, placement, ratio, area);
    },
    touches: (placement, ratio, area) =>
      list.some((painter) => painter.touches(placement, ratio, area)),
  };
};
