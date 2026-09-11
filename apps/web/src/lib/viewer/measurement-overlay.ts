/**
 * Слой измерений: сохранённые фигуры, черновик и ручки вершин.
 *
 * Отдельный холст поверх слоя распознанных областей (ADR-0015). Painter областей не
 * расширяется признаком «а это измерение»: `Region` — свидетельство распознавалки,
 * `Measurement` — намерение пользователя, и общая функция ломалась бы для обоих сразу.
 *
 * Canvas2D. WebGL — только после замера, и замер этот делает промт 14, а не предположение.
 */

import type {
  NormalizedPoint,
  ScreenPoint,
  ScreenRect,
  SheetPlacement,
} from '@/lib/viewer/coordinates';
import { toNormalizedBounds, toScreenPoint } from '@/lib/viewer/coordinates';
import {
  beginLayerPaint,
  boundsIntersectAny,
  visibleRects,
  type PixelRect,
} from '@/lib/viewer/layer-paint';
import type { ShapeIndex } from '@/lib/viewer/shape-index';

/** Геометрия, как её рисует слой. Ровно то, что нужно отрисовке, и ничего больше. */
export interface OverlayMeasurement {
  readonly id: string;
  readonly geometryType: 'count' | 'line' | 'polyline' | 'polygon';
  readonly points: readonly NormalizedPoint[];
  /** Ключ палитры темы: цвет строки обмера. */
  readonly colorKey: string;
}

export interface MeasurementOverlayState {
  readonly measurements: readonly OverlayMeasurement[];
  readonly selectedId: string | null;
  readonly hoveredId: string | null;
  /** Вершины незавершённой фигуры. */
  readonly draft: readonly NormalizedPoint[];
  /** Тип рисуемой сейчас фигуры: от него зависит, замыкать ли черновик. */
  readonly draftType: OverlayMeasurement['geometryType'] | null;
  readonly draftHover: NormalizedPoint | null;
  /** Геометрия перетаскиваемого измерения: рисуется вместо сохранённой. */
  readonly dragOverride: {
    readonly id: string;
    readonly points: readonly NormalizedPoint[];
  } | null;
  /**
   * Пространственный индекс измерений (промт 04). Есть — отсечение спрашивает его, нет — перебирает
   * список. Результат один и тот же, индекс только быстрее; синхронизируется со списком сам.
   */
  readonly index?: ShapeIndex<OverlayMeasurement> | null;
}

export interface MeasurementOverlayStyle {
  /** Цвета по ключу палитры. Приходят из токенов темы, а не зашиты здесь. */
  readonly colors: Readonly<Record<string, string>>;
  readonly fallbackColor: string;
}

const LINE_WIDTH = 2;
const SELECTED_LINE_WIDTH = 3;
const COUNT_RADIUS = 5;
const VERTEX_RADIUS = 4;
const FILL_ALPHA = 0.16;
const SELECTED_FILL_ALPHA = 0.26;
const DRAFT_DASH = [6, 4];

/** Радиус попадания по вершине в пикселях экрана. Меньше — в вершину не попасть мышью. */
export const VERTEX_HIT_RADIUS = 8;

/** Запас отсечения: самая широкая часть фигуры за пределами её геометрии — метка счёта. */
const CULL_MARGIN = Math.max(COUNT_RADIUS, VERTEX_RADIUS) + SELECTED_LINE_WIDTH;

const colorOf = (measurement: OverlayMeasurement, style: MeasurementOverlayStyle): string =>
  style.colors[measurement.colorKey] ?? style.fallbackColor;

/**
 * Рисует слой и возвращает число нарисованных фигур.
 *
 * Рисуются только фигуры, задевающие холст или полосы `area`: слой размером с область
 * просмотра, и при панораме сюда приходят только открывшиеся полосы (ADR-0025). Невидимое не
 * растеризуется — именно растеризация, а не обход списка, стоит основного времени кадра. Обход
 * при этом дешёвый: охват фигуры считается по нормализованным точкам, в пиксели переводятся два
 * его угла, а все точки — только у видимых фигур.
 *
 * Возврат нужен тесту: «слой отрисовался» и «слой отрисовал то, что нужно» — разные
 * утверждения, и второе проверяется числом, а не скриншотом.
 */
export const drawMeasurements = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: MeasurementOverlayState,
  style: MeasurementOverlayStyle,
  devicePixelRatio = 1,
  area: readonly PixelRect[] | null = null,
): number => {
  const visible = beginLayerPaint(context, devicePixelRatio, area, CULL_MARGIN);

  let drawn = 0;
  for (const measurement of candidatesFor(state, placement, visible)) {
    const points =
      state.dragOverride?.id === measurement.id ? state.dragOverride.points : measurement.points;
    if (!pointsVisible(points, placement, visible)) continue;

    const screen = points.map((point) => toScreenPoint(point, placement));
    drawShape(context, measurement, screen, state, style);
    drawn += 1;
  }

  if (state.draft.length > 0 && state.draftType !== null) {
    drawDraft(context, placement, state, style);
  }

  context.restore();
  return drawn;
};

/**
 * Есть ли в полосах `area` что рисовать: черновик или хоть одно видимое измерение (ADR-0025).
 *
 * Нет — слой на панораме сдвигается одним CSS и холст не трогает. Отсечение то же, что у
 * `drawMeasurements`, поэтому ответ «нечего» никогда не теряет фигуру, которую отрисовка нарисовала
 * бы. Черновик считается задевающим всегда: он живёт под курсором и дёшев.
 */
export const measurementsTouch = (
  placement: SheetPlacement,
  state: MeasurementOverlayState,
  devicePixelRatio: number,
  area: readonly PixelRect[],
): boolean => {
  if (state.draft.length > 0 && state.draftType !== null) return true;

  const visible = visibleRects(area, devicePixelRatio, CULL_MARGIN);
  return candidatesFor(state, placement, visible).some((measurement) => {
    const points =
      state.dragOverride?.id === measurement.id ? state.dragOverride.points : measurement.points;
    return pointsVisible(points, placement, visible);
  });
};

/**
 * Измерения, которые стоит проверить на видимость, в порядке списка: без индекса — все, с индексом —
 * его кандидаты по видимым прямоугольникам.
 *
 * Перетаскиваемое измерение в индексе лежит со старым охватом: жест меняет геометрию на каждом
 * движении, и переносить запись ради кадра незачем. Поэтому оно добавляется в кандидаты всегда, а
 * видимость решает его новая геометрия.
 */
const candidatesFor = (
  state: MeasurementOverlayState,
  placement: SheetPlacement,
  visible: readonly ScreenRect[],
): readonly OverlayMeasurement[] => {
  const index = state.index;
  if (!index) return state.measurements;

  index.sync(state.measurements);
  const hits = index.query(visible.map((rect) => toNormalizedBounds(rect, placement)));
  const dragged = state.dragOverride
    ? { id: state.dragOverride.id, order: index.orderOf(state.dragOverride.id) }
    : null;
  if (!dragged || dragged.order === null) return hits.map((hit) => hit.item);

  const draggedOrder = dragged.order;
  const others = hits.filter((hit) => hit.item.id !== dragged.id);
  const item = state.measurements[draggedOrder];
  if (!item) return others.map((hit) => hit.item);

  const position = others.findIndex((hit) => hit.order > draggedOrder);
  const merged = others.map((hit) => hit.item);
  merged.splice(position < 0 ? merged.length : position, 0, item);
  return merged;
};

/** Задевает ли охват точек видимые прямоугольники. Вызывается на тысячах фигур за кадр. */
const pointsVisible = (
  points: readonly NormalizedPoint[],
  placement: SheetPlacement,
  visible: readonly ScreenRect[],
): boolean => {
  if (points.length === 0) return false;

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

  // Поворот переставляет углы охвата, поэтому в пиксели переводятся оба угла, а охват
  // собирается заново — прямоугольник остаётся прямоугольником при повороте на 90°.
  const first = toScreenPoint({ x: minX, y: minY }, placement);
  const second = toScreenPoint({ x: maxX, y: maxY }, placement);
  return boundsIntersectAny(
    Math.min(first.x, second.x),
    Math.min(first.y, second.y),
    Math.max(first.x, second.x),
    Math.max(first.y, second.y),
    visible,
  );
};

const drawShape = (
  context: CanvasRenderingContext2D,
  measurement: OverlayMeasurement,
  screen: readonly ScreenPoint[],
  state: MeasurementOverlayState,
  style: MeasurementOverlayStyle,
): void => {
  const selected = state.selectedId === measurement.id;
  const hovered = state.hoveredId === measurement.id;
  const color = colorOf(measurement, style);

  context.save();
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = selected ? SELECTED_LINE_WIDTH : LINE_WIDTH;

  if (measurement.geometryType === 'count') {
    const marker = screen[0];
    if (marker) {
      context.globalAlpha = selected || hovered ? 1 : 0.85;
      context.beginPath();
      context.arc(marker.x, marker.y, COUNT_RADIUS, 0, Math.PI * 2);
      context.fill();
    }
  } else {
    const closed = measurement.geometryType === 'polygon';
    tracePath(context, screen, closed);

    if (closed) {
      context.globalAlpha = selected ? SELECTED_FILL_ALPHA : FILL_ALPHA;
      context.fill();
      context.globalAlpha = 1;
    }
    context.stroke();
  }

  // Ручки вершин только у выбранного: у всех сразу они превратили бы чертёж в россыпь точек.
  if (selected && measurement.geometryType !== 'count') {
    context.globalAlpha = 1;
    for (const point of screen) {
      context.beginPath();
      context.arc(point.x, point.y, VERTEX_RADIUS, 0, Math.PI * 2);
      context.fill();
    }
  }

  context.restore();
};

const drawDraft = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: MeasurementOverlayState,
  style: MeasurementOverlayStyle,
): void => {
  const screen = state.draft.map((point) => toScreenPoint(point, placement));
  const hover = state.draftHover ? toScreenPoint(state.draftHover, placement) : null;
  const path = hover ? [...screen, hover] : screen;

  context.save();
  context.strokeStyle = style.fallbackColor;
  context.fillStyle = style.fallbackColor;
  context.lineWidth = LINE_WIDTH;
  // Пунктир: черновик ещё не результат и выглядеть как результат не должен.
  context.setLineDash(DRAFT_DASH);

  // Многоугольник замыкается только визуально: в данные дублирующая точка не попадает.
  tracePath(context, path, state.draftType === 'polygon' && path.length > 2);
  context.stroke();
  context.setLineDash([]);

  for (const point of screen) {
    context.beginPath();
    context.arc(point.x, point.y, VERTEX_RADIUS, 0, Math.PI * 2);
    context.fill();
  }

  context.restore();
};

const tracePath = (
  context: CanvasRenderingContext2D,
  points: readonly ScreenPoint[],
  closed: boolean,
): void => {
  context.beginPath();
  points.forEach((point, index) => {
    if (index === 0) context.moveTo(point.x, point.y);
    else context.lineTo(point.x, point.y);
  });
  if (closed) context.closePath();
};

/**
 * Ищет измерение под курсором.
 *
 * Из перекрывающихся побеждает наименьшее по охвату: крупная фигура обычно окружает
 * мелкие, и выбирать нужно то, во что пользователь целился. То же правило, что у областей
 * (`coordinates.hitTest`), — иначе выбор вёл бы себя на двух слоях по-разному. При равном охвате
 * побеждает первое в списке.
 *
 * С индексом (промт 04) точная проверка идёт только по кандидатам: тем, чей охват задевает квадрат
 * вокруг курсора со стороной в радиус попадания. Это надмножество всего, во что можно попасть: метка
 * счёта ловится в радиусе метки и допуска, отрезок — в допуске, а точка внутри многоугольника лежит в
 * его охвате. Без индекса перебираются все, и ответ тот же.
 */
export const hitTestMeasurements = (
  measurements: readonly OverlayMeasurement[],
  point: NormalizedPoint,
  placement: SheetPlacement,
  tolerancePx = 6,
  index: ShapeIndex<OverlayMeasurement> | null = null,
): OverlayMeasurement | null => {
  const target = toScreenPoint(point, placement);
  let best: OverlayMeasurement | null = null;
  let bestExtent = Number.POSITIVE_INFINITY;

  let candidates = measurements;
  if (index) {
    const reach = COUNT_RADIUS + tolerancePx;
    index.sync(measurements);
    candidates = index
      .query([
        toNormalizedBounds(
          { x: target.x - reach, y: target.y - reach, width: reach * 2, height: reach * 2 },
          placement,
        ),
      ])
      .map((hit) => hit.item);
  }

  for (const measurement of candidates) {
    const screen = measurement.points.map((item) => toScreenPoint(item, placement));
    if (!hits(measurement, screen, target, tolerancePx)) continue;

    const extent = boundingExtent(screen);
    if (extent < bestExtent) {
      best = measurement;
      bestExtent = extent;
    }
  }

  return best;
};

/** Ищет вершину выбранного измерения под курсором. Возвращает индекс или `null`. */
export const hitTestVertex = (
  points: readonly NormalizedPoint[],
  point: NormalizedPoint,
  placement: SheetPlacement,
  radiusPx = VERTEX_HIT_RADIUS,
): number | null => {
  const target = toScreenPoint(point, placement);

  for (const [index, item] of points.entries()) {
    const screen = toScreenPoint(item, placement);
    if (Math.hypot(screen.x - target.x, screen.y - target.y) <= radiusPx) {
      return index;
    }
  }

  return null;
};

const hits = (
  measurement: OverlayMeasurement,
  screen: readonly ScreenPoint[],
  target: ScreenPoint,
  tolerance: number,
): boolean => {
  if (measurement.geometryType === 'count') {
    const marker = screen[0];
    return marker
      ? Math.hypot(marker.x - target.x, marker.y - target.y) <= COUNT_RADIUS + tolerance
      : false;
  }

  if (measurement.geometryType === 'polygon' && insidePolygon(screen, target)) {
    return true;
  }

  const closed = measurement.geometryType === 'polygon';
  for (let index = 1; index < screen.length; index += 1) {
    const from = screen[index - 1];
    const to = screen[index];
    if (from && to && distanceToSegment(target, from, to) <= tolerance) return true;
  }

  if (closed && screen.length > 2) {
    const first = screen[0];
    const last = screen[screen.length - 1];
    if (first && last && distanceToSegment(target, last, first) <= tolerance) return true;
  }

  return false;
};

const boundingExtent = (points: readonly ScreenPoint[]): number => {
  if (points.length === 0) return Number.POSITIVE_INFINITY;

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const point of points) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }

  // Площадь охватывающего прямоугольника, но не меньше единицы: у отрезка она нулевая,
  // и без пола отрезок всегда побеждал бы многоугольник.
  return Math.max((maxX - minX) * (maxY - minY), 1);
};

const distanceToSegment = (point: ScreenPoint, from: ScreenPoint, to: ScreenPoint): number => {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared === 0) {
    return Math.hypot(point.x - from.x, point.y - from.y);
  }

  const t = Math.max(
    0,
    Math.min(1, ((point.x - from.x) * dx + (point.y - from.y) * dy) / lengthSquared),
  );
  return Math.hypot(point.x - (from.x + t * dx), point.y - (from.y + t * dy));
};

const insidePolygon = (points: readonly ScreenPoint[], target: ScreenPoint): boolean => {
  let inside = false;
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
    const current = points[index];
    const other = points[previous];
    if (!current || !other) continue;

    const crosses = current.y > target.y !== other.y > target.y;
    if (!crosses) continue;

    const x = ((other.x - current.x) * (target.y - current.y)) / (other.y - current.y) + current.x;
    if (target.x < x) inside = !inside;
  }
  return inside;
};
