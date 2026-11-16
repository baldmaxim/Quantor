/**
 * Рисовальщик разметки фасадов поверх листа (Canvas2D, ADR-0015, ADR-0048).
 *
 * Рамки вида и окон приходят от генератора в долях отображаемой страницы (поворот уже учтён,
 * ADR-0008) и кладутся на лист как есть. Статус вида виден не только цветом: у отклонённого штрих
 * пунктирный. Цвета - те же токены чернил листа, что у разрезов.
 */

import type { FacadeViewRead } from '@quantor/api-client';

import { toScreenRect, type NormalizedRect, type SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { beginOverPaint } from './remarks-painter';
import type { ISectionColors } from './sections-painter';

export type IFacadeColors = ISectionColors;

export interface IFacadePaintData {
  /** Виды показанной страницы. */
  readonly views: readonly Pick<FacadeViewRead, 'id' | 'status' | 'bbox' | 'windows'>[];
  readonly colors: IFacadeColors;
  /** Выбранный вид: рисуется толще и с заливкой. */
  readonly activeId: string | null;
}

export const facadeColor = (colors: IFacadeColors, status: FacadeViewRead['status']): string =>
  colors[status];

const LINE_WIDTH = 1.5;
const ACTIVE_LINE_WIDTH = 3.5;
const WINDOW_LINE_WIDTH = 1;
const REJECTED_DASH = [5, 4];
const MARGIN = 12;

interface IBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

const boxOf = (rect: NormalizedRect, placement: SheetPlacement): IBox =>
  toScreenRect(rect, placement);

const hits = (box: IBox, rects: readonly IBox[]): boolean =>
  boundsIntersectAny(box.x, box.y, box.x + box.width, box.y + box.height, rects);

const boxesOf = (data: IFacadePaintData, placement: SheetPlacement): IBox[] =>
  data.views.flatMap((view) => [
    boxOf(view.bbox, placement),
    ...view.windows.map((window) => boxOf(window.bbox, placement)),
  ]);

const drawView = (
  context: CanvasRenderingContext2D,
  view: IFacadePaintData['views'][number],
  placement: SheetPlacement,
  data: IFacadePaintData,
  rects: readonly IBox[],
): void => {
  const color = facadeColor(data.colors, view.status);
  const active = view.id === data.activeId;
  const dash = view.status === 'rejected' ? REJECTED_DASH : [];
  context.strokeStyle = color;
  context.setLineDash([...dash]);

  const frame = boxOf(view.bbox, placement);
  if (hits(frame, rects)) {
    if (active) {
      context.globalAlpha = 0.08;
      context.fillStyle = color;
      context.fillRect(frame.x, frame.y, frame.width, frame.height);
      context.globalAlpha = 1;
    }
    context.lineWidth = active ? ACTIVE_LINE_WIDTH : LINE_WIDTH;
    context.strokeRect(frame.x, frame.y, frame.width, frame.height);
  }
  context.lineWidth = WINDOW_LINE_WIDTH;
  for (const window of view.windows) {
    const box = boxOf(window.bbox, placement);
    if (hits(box, rects)) context.strokeRect(box.x, box.y, box.width, box.height);
  }
};

/**
 * Рисовальщик разметки фасадов. `clear: true` - слой только с разметкой (чистит холст сам);
 * `false` - поверх другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createFacadesPainter = (
  data: IFacadePaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    // Выбранный вид рисуется последним: его рамки не перекрываются соседними.
    const views = [...data.views].sort(
      (a, b) => Number(a.id === data.activeId) - Number(b.id === data.activeId),
    );
    for (const view of views) drawView(context, view, placement, data, rects);
    context.setLineDash([]);
    context.globalAlpha = 1;
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return boxesOf(data, placement).some((box) => hits(box, rects));
  },
});
