/**
 * Слой распознанных областей.
 *
 * Отдельный холст поверх страницы, а не элементы DOM: на листе сотни областей, и столько
 * узлов заставляют браузер пересчитывать раскладку на каждом кадре панорамирования
 * (ADR-0004).
 *
 * Взят двумерный холст, а не WebGL: для сотен прямоугольников он справляется с запасом,
 * а WebGL-слой — это ещё одна тяжёлая зависимость в бандле рабочей области. Когда на лист
 * придут тысячи примитивов будущих обмеров, сюда встанет пространственный индекс и
 * упрощение по масштабу; рисование вынесено в отдельную функцию именно для этого.
 *
 * Слой измерений будет отдельным слоем и не переиспользует эти объекты: Region — это
 * свидетельство, а не намерение (ADR-0008).
 */

import {
  toScreenPolygon,
  toScreenRect,
  type NormalizedRect,
  type ScreenPoint,
  type ScreenRect,
  type SheetPlacement,
} from './coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects, type PixelRect } from './layer-paint';

export interface OverlayRegion {
  readonly id: string;
  readonly blockType: string;
  readonly shapeType: 'rectangle' | 'polygon';
  readonly coords: NormalizedRect;
  readonly polygon: readonly (readonly [number, number])[] | null;
}

export interface OverlayStyle {
  /** Цвет по типу области. Значения приходят из токенов темы, а не задаются здесь. */
  readonly colors: Readonly<Record<string, string>>;
  readonly fallbackColor: string;
}

export interface OverlayState {
  readonly regions: readonly OverlayRegion[];
  readonly hiddenTypes: ReadonlySet<string>;
  readonly selectedId: string | null;
  readonly hoveredId: string | null;
}

const LINE_WIDTH = 1.5;
const SELECTED_LINE_WIDTH = 2.5;
/** Запас отсечения — толщина штриха выделенной области. */
const CULL_MARGIN = SELECTED_LINE_WIDTH;
const FILL_ALPHA = 0.14;
const HOVER_ALPHA = 0.2;
const SELECTED_ALPHA = 0.28;

/**
 * Рисует видимую часть слоя — весь холст или только полосы `area` (ADR-0025).
 *
 * Функция чистая относительно холста: она не хранит состояния и не подписывается
 * на события. Слой размером с область просмотра; при панораме его пиксели сдвигаются, а
 * сюда приходят только открывшиеся полосы. Области вне холста или вне полос не растеризуются.
 */
export const drawOverlay = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: OverlayState,
  style: OverlayStyle,
  devicePixelRatio = 1,
  area: readonly PixelRect[] | null = null,
): number => {
  const visible = beginLayerPaint(context, devicePixelRatio, area, CULL_MARGIN);
  let drawn = 0;

  for (const region of state.regions) {
    const shape = visibleShape(region, placement, state, visible);
    if (!shape) continue;
    const { polygon, rect } = shape;

    const color = style.colors[region.blockType] ?? style.fallbackColor;
    const selected = region.id === state.selectedId;
    const hovered = region.id === state.hoveredId;

    context.strokeStyle = color;
    context.fillStyle = color;
    context.globalAlpha = selected ? SELECTED_ALPHA : hovered ? HOVER_ALPHA : FILL_ALPHA;
    context.lineWidth = selected ? SELECTED_LINE_WIDTH : LINE_WIDTH;

    if (polygon) {
      drawPolygon(context, polygon);
    } else if (rect) {
      drawRect(context, rect);
    }

    drawn += 1;
  }

  context.restore();
  return drawn;
};

/**
 * Есть ли в полосах `area` хоть одна видимая область (ADR-0025).
 *
 * Нет — слой на панораме сдвигается одним CSS и холст не трогает: передача холста композитору
 * на каждом кадре стоит дороже, чем кажется. Отсечение то же, что у `drawOverlay`, поэтому ответ
 * «нечего» никогда не теряет область, которую отрисовка нарисовала бы.
 */
export const overlayTouches = (
  placement: SheetPlacement,
  state: OverlayState,
  devicePixelRatio: number,
  area: readonly PixelRect[],
): boolean => {
  const visible = visibleRects(area, devicePixelRatio, CULL_MARGIN);
  return state.regions.some((region) => visibleShape(region, placement, state, visible) !== null);
};

/** Экранная форма области, если она не скрыта и задевает видимые прямоугольники. */
const visibleShape = (
  region: OverlayRegion,
  placement: SheetPlacement,
  state: OverlayState,
  visible: readonly ScreenRect[],
): { readonly polygon: ScreenPoint[] | null; readonly rect: ScreenRect | null } | null => {
  if (state.hiddenTypes.has(region.blockType)) return null;

  const polygon =
    region.shapeType === 'polygon' && region.polygon && region.polygon.length >= 3
      ? toScreenPolygon(region.polygon, placement)
      : null;
  if (polygon) return polygonVisible(polygon, visible) ? { polygon, rect: null } : null;

  const rect = toScreenRect(region.coords, placement);
  return rectVisible(rect, visible) ? { polygon: null, rect } : null;
};

const rectVisible = (rect: ScreenRect, visible: readonly ScreenRect[]): boolean =>
  boundsIntersectAny(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height, visible);

const polygonVisible = (
  points: readonly ScreenPoint[],
  visible: readonly ScreenRect[],
): boolean => {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    if (point.x < minX) minX = point.x;
    if (point.x > maxX) maxX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.y > maxY) maxY = point.y;
  }
  return points.length > 0 && boundsIntersectAny(minX, minY, maxX, maxY, visible);
};

const drawRect = (context: CanvasRenderingContext2D, rect: ScreenRect): void => {
  context.fillRect(rect.x, rect.y, rect.width, rect.height);
  context.globalAlpha = 1;
  context.strokeRect(rect.x, rect.y, rect.width, rect.height);
};

const drawPolygon = (context: CanvasRenderingContext2D, points: readonly ScreenPoint[]): void => {
  const first = points[0];
  if (!first) return;

  context.beginPath();
  context.moveTo(first.x, first.y);
  for (const point of points.slice(1)) context.lineTo(point.x, point.y);
  context.closePath();

  context.fill();
  context.globalAlpha = 1;
  context.stroke();
};

/** Подгоняет размер холста под область отрисовки с учётом плотности экрана. */
export const resizeOverlay = (
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
  devicePixelRatio = 1,
): void => {
  const targetWidth = Math.max(1, Math.floor(width * devicePixelRatio));
  const targetHeight = Math.max(1, Math.floor(height * devicePixelRatio));

  if (canvas.width !== targetWidth) canvas.width = targetWidth;
  if (canvas.height !== targetHeight) canvas.height = targetHeight;

  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
};
