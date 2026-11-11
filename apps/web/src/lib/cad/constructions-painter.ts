/**
 * Рисовальщик конструкций листа для просмотрщика (Canvas2D, ADR-0015, ADR-0038).
 *
 * Конструкции идут тем же слоем, что и геометрия CAD, и подчиняются протоколу слоя (ADR-0025):
 * полосы панорамы, отсечение по охвату, `touches` не строже `paint`. Кладка, монолит и плита
 * перекрытия (под стенами, слабее) - полупрозрачная заливка разных токенов; конструкция без толщины или высоты - токеном «проверить»; принятая
 * плотнее; выделенная - контур цвета акцента потолще.
 */

import { toScreenPoint, type ScreenPoint, type SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { PixelRect } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import type { IConstructionShape } from './constructions';
import { withoutHiddenCategories, type CadLayerCategory } from './layer-categories';

export interface IConstructionColors {
  readonly masonry: string;
  readonly monolith: string;
  /** Плита перекрытия: приглушённый фон под стенами. */
  readonly slab: string;
  readonly check: string;
  /** Контур выделенных конструкций. */
  readonly accent: string;
  /** Штриховка и контур конструкций, которых нет в ВОР Заказчика. */
  readonly notInVor: string;
}

export interface IConstructionPaintData {
  readonly shapes: readonly IConstructionShape[];
  readonly colors: IConstructionColors;
  readonly selected: ReadonlySet<string>;
  /**
   * Полный показ (галка «Контуры всех конструкций»). `false` - рисуются только выбранные: кладка,
   * монолит и зоны уже видны слоями DXF, обводки не дублируются.
   */
  readonly showAll: boolean;
  /**
   * Конструкции «не в ВОР»; не задано - ВОР не загружен или подсветка выключена, ничего не рисуется.
   * Рисуются только при полном показе.
   */
  readonly notInVor?: ReadonlySet<string>;
  /** Скрытые категории вкладки «Слои»: их конструкции не рисуются (и не выбираются - индекс строится без них). */
  readonly hiddenCategories?: ReadonlySet<CadLayerCategory>;
  /** Имена скрытых слоёв DXF: конструкция скрыта, когда скрыты все её слои-источники. */
  readonly hiddenLayerNames?: ReadonlySet<string>;
}

const FILL_ALPHA = 0.22;
const ACCEPTED_FILL_ALPHA = 0.36;
const SELECTED_FILL_ALPHA = 0.45;
/** Плита перекрытия лежит под стенами: заливка слабее, принятие её не сгущает. */
const SLAB_FILL_ALPHA = 0.1;
const LINE_WIDTH = 1;
const ACCEPTED_LINE_WIDTH = 1.5;
const SELECTED_LINE_WIDTH = 3;
const NOT_IN_VOR_LINE_WIDTH = 2;
const NOT_IN_VOR_DASH: readonly number[] = [5, 3];
/** Каркасная перегородка ГКЛ: цвет кладки (токен), отличие - пунктир контура. */
const FRAME_PARTITION_DASH: readonly number[] = [3, 2];
/** Шаг штриховки в пикселях; у крупной конструкции растёт, чтобы линий было не больше предела. */
const HATCH_STEP = 8;
const HATCH_MAX_LINES = 300;
/** Запас отсечения на толщину контура. */
const MARGIN = 8;

/** Конструкции, которые слой рисует: при полном показе все, иначе только выбранные. */
const drawnShapes = (data: IConstructionPaintData): readonly IConstructionShape[] => {
  const shapes = withoutHiddenCategories(data.shapes, data.hiddenCategories, data.hiddenLayerNames);
  return data.showAll ? shapes : shapes.filter((shape) => data.selected.has(shape.id));
};

/** Читает цвета из токенов темы. */
export const readConstructionColors = (): IConstructionColors => {
  if (typeof window === 'undefined') {
    return {
      masonry: 'CanvasText',
      monolith: 'CanvasText',
      slab: 'CanvasText',
      check: 'CanvasText',
      accent: 'CanvasText',
      notInVor: 'CanvasText',
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim() || 'CanvasText';
  return {
    masonry: token('--cad-construction-masonry'),
    monolith: token('--cad-construction-monolith'),
    slab: token('--cad-construction-slab'),
    check: token('--cad-construction-check'),
    accent: token('--accent'),
    notInVor: token('--cad-construction-not-in-vor'),
  };
};

export const constructionColor = (
  colors: IConstructionColors,
  shape: Pick<IConstructionShape, 'kind' | 'status'>,
): string =>
  shape.status !== 'ok'
    ? colors.check
    : shape.kind === 'floor_slab'
      ? colors.slab
      : shape.kind === 'masonry' || shape.kind === 'frame_partition'
        ? colors.masonry
        : colors.monolith;

interface IScreenBox {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

const screenBox = (shape: IConstructionShape, placement: SheetPlacement): IScreenBox => {
  const { minX, minY, maxX, maxY } = shape.bounds;
  const corners = [
    toScreenPoint({ x: minX, y: minY }, placement),
    toScreenPoint({ x: maxX, y: maxY }, placement),
  ];
  const [first, second] = corners as [ScreenPoint, ScreenPoint];
  return {
    minX: Math.min(first.x, second.x),
    minY: Math.min(first.y, second.y),
    maxX: Math.max(first.x, second.x),
    maxY: Math.max(first.y, second.y),
  };
};

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

const trace = (
  context: CanvasRenderingContext2D,
  shape: IConstructionShape,
  placement: SheetPlacement,
) => {
  context.beginPath();
  for (const ring of shape.rings) {
    ring.forEach((point, index) => {
      const at = toScreenPoint(point, placement);
      if (index === 0) context.moveTo(at.x, at.y);
      else context.lineTo(at.x, at.y);
    });
    context.closePath();
  }
};

const drawShape = (
  context: CanvasRenderingContext2D,
  shape: IConstructionShape,
  placement: SheetPlacement,
  data: IConstructionPaintData,
) => {
  const selected = data.selected.has(shape.id);
  const color = constructionColor(data.colors, shape);
  trace(context, shape, placement);
  context.globalAlpha = selected
    ? SELECTED_FILL_ALPHA
    : shape.kind === 'floor_slab'
      ? SLAB_FILL_ALPHA
      : shape.accepted
      ? ACCEPTED_FILL_ALPHA
      : FILL_ALPHA;
  context.fillStyle = color;
  // Чётно-нечётное правило: отверстия остаются пустыми.
  context.fill('evenodd');
  context.globalAlpha = 1;
  context.strokeStyle = selected ? data.colors.accent : color;
  context.lineWidth = selected ? SELECTED_LINE_WIDTH : shape.accepted ? ACCEPTED_LINE_WIDTH : LINE_WIDTH;
  context.lineJoin = 'round';
  if (shape.kind === 'frame_partition') context.setLineDash([...FRAME_PARTITION_DASH]);
  context.stroke();
  context.setLineDash([]);
};

/**
 * «Не в ВОР»: диагональная штриховка внутри конструкции (в пределах видимой части) и пунктирный
 * контур. Штриховка ограничена контуром конструкции (evenodd: отверстия пустые).
 */
const drawNotInVor = (
  context: CanvasRenderingContext2D,
  shape: IConstructionShape,
  placement: SheetPlacement,
  color: string,
  view: PixelRect,
  selected: boolean,
) => {
  const box = screenBox(shape, placement);
  const x0 = Math.max(box.minX, view.x);
  const y0 = Math.max(box.minY, view.y);
  const x1 = Math.min(box.maxX, view.x + view.width);
  const y1 = Math.min(box.maxY, view.y + view.height);
  context.strokeStyle = color;
  if (x1 > x0 && y1 > y0) {
    const height = y1 - y0;
    const step = Math.max(HATCH_STEP, (x1 - x0 + height) / HATCH_MAX_LINES);
    context.save();
    trace(context, shape, placement);
    context.clip('evenodd');
    context.beginPath();
    for (let x = x0 - height; x <= x1; x += step) {
      context.moveTo(x, y1);
      context.lineTo(x + height, y0);
    }
    context.lineWidth = LINE_WIDTH;
    context.stroke();
    context.restore();
  }
  // Выделенная конструкция сохраняет контур акцента.
  if (selected) return;
  trace(context, shape, placement);
  context.setLineDash([...NOT_IN_VOR_DASH]);
  context.lineWidth = NOT_IN_VOR_LINE_WIDTH;
  context.stroke();
  context.setLineDash([]);
};

const boundsOfRects = (rects: readonly PixelRect[]): PixelRect => {
  const x0 = Math.min(...rects.map((rect) => rect.x));
  const y0 = Math.min(...rects.map((rect) => rect.y));
  const x1 = Math.max(...rects.map((rect) => rect.x + rect.width));
  const y1 = Math.max(...rects.map((rect) => rect.y + rect.height));
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
};

/**
 * Рисовальщик конструкций. `clear: true` - слой только с ними (чистит холст сам); `false` -
 * поверх другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createConstructionsPainter = (
  data: IConstructionPaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    const visible = drawnShapes(data).filter((shape) => {
      const box = screenBox(shape, placement);
      return boundsIntersectAny(box.minX, box.minY, box.maxX, box.maxY, rects);
    });
    // Плита - первой (под стенами); выделенные - последними, чтобы контур не прятался под соседними.
    const isSlab = (shape: IConstructionShape) => shape.kind === 'floor_slab';
    const isSelected = (shape: IConstructionShape) => data.selected.has(shape.id);
    const ordered = [
      ...visible.filter((shape) => isSlab(shape) && !isSelected(shape)),
      ...visible.filter((shape) => !isSlab(shape) && !isSelected(shape)),
      ...visible.filter((shape) => isSlab(shape) && isSelected(shape)),
      ...visible.filter((shape) => !isSlab(shape) && isSelected(shape)),
    ];
    const hatchView =
      data.showAll && data.notInVor && data.notInVor.size > 0 && rects.length > 0
        ? boundsOfRects(rects)
        : null;
    for (const shape of ordered) {
      drawShape(context, shape, placement, data);
      if (hatchView && data.notInVor?.has(shape.id)) {
        drawNotInVor(context, shape, placement, data.colors.notInVor, hatchView, data.selected.has(shape.id));
      }
    }
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return drawnShapes(data).some((shape) => {
      const box = screenBox(shape, placement);
      return boundsIntersectAny(box.minX, box.minY, box.maxX, box.maxY, rects);
    });
  },
});
