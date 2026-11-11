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
  /** Цвет каждого слоя по его индексу (из токенов темы); слой без цвета рисуется чернилами. */
  readonly layerColors: readonly string[];
  /** Чернила по умолчанию - из токенов темы. */
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

/**
 * Единицы путей `Path2D`: нормализованная координата умножается на `PATH_UNITS`, чтобы числа
 * в пути были «листовыми», а не от 0 до 1 (при глубоком зуме малые числа теряют точность).
 */
const PATH_UNITS = 1000;
/** Расхождение пропорций листа, при котором пути строятся заново (другой лист под тем же массивом). */
const ASPECT_TOLERANCE = 0.02;

/** Геометрия одного слоя: пути, охват и собранные `Path2D` (строятся один раз). */
interface ILayerGeometry {
  readonly layer: number;
  readonly paths: INormalizedPath[];
  readonly bounds: [number, number, number, number];
  stroke: Path2D | null;
  fill: Path2D | null;
}

/** Слои массива путей и пропорции листа (высота/ширина), для которых собраны `Path2D`. */
interface IGeometryEntry {
  readonly layers: Map<number, ILayerGeometry>;
  aspect: number;
  /** Растёт при каждой пересборке путей: по нему рисовальщики узнают, что их группы устарели. */
  version: number;
}

/**
 * Массив нормализованных путей неизменяем, поэтому группировка по слоям и `Path2D` живут столько
 * же, сколько он: переключение видимости слоя, цветов и рамки массив не меняет, и пути не
 * пересобираются.
 */
const geometryCache = new WeakMap<readonly INormalizedPath[], IGeometryEntry>();

const entryOf = (paths: readonly INormalizedPath[]): IGeometryEntry => {
  const cached = geometryCache.get(paths);
  if (cached) return cached;
  const layers = new Map<number, ILayerGeometry>();
  for (const path of paths) {
    let geometry = layers.get(path.layer);
    if (!geometry) {
      geometry = {
        layer: path.layer,
        paths: [],
        bounds: [path.bounds[0], path.bounds[1], path.bounds[2], path.bounds[3]],
        stroke: null,
        fill: null,
      };
      layers.set(path.layer, geometry);
    }
    geometry.paths.push(path);
    geometry.bounds[0] = Math.min(geometry.bounds[0], path.bounds[0]);
    geometry.bounds[1] = Math.min(geometry.bounds[1], path.bounds[1]);
    geometry.bounds[2] = Math.max(geometry.bounds[2], path.bounds[2]);
    geometry.bounds[3] = Math.max(geometry.bounds[3], path.bounds[3]);
  }
  const entry: IGeometryEntry = { layers, aspect: 0, version: 0 };
  geometryCache.set(paths, entry);
  return entry;
};

const tracePath = (target: Path2D, path: INormalizedPath, aspect: number): void => {
  const { points } = path;
  const ky = PATH_UNITS * aspect;
  target.moveTo((points[0] ?? 0) * PATH_UNITS, (points[1] ?? 0) * ky);
  for (let index = 2; index + 1 < points.length; index += 2) {
    target.lineTo((points[index] ?? 0) * PATH_UNITS, (points[index + 1] ?? 0) * ky);
  }
  if (path.closed) target.closePath();
};

/**
 * Пути слоёв под пропорции листа. Пропорции запоминаются при первом рисовании: масштаб по Y
 * потом считается от них же, поэтому геометрия точная, а штрих искажается не больше допуска.
 */
const ensureAspect = (entry: IGeometryEntry, aspect: number): void => {
  if (entry.aspect > 0 && Math.abs(aspect / entry.aspect - 1) <= ASPECT_TOLERANCE) return;
  entry.aspect = aspect;
  entry.version += 1;
  for (const geometry of entry.layers.values()) {
    geometry.stroke = null;
    geometry.fill = null;
  }
};

const ensureLayerPaths = (geometry: ILayerGeometry, aspect: number): void => {
  if (geometry.stroke !== null) return;
  const stroke = new Path2D();
  let fill: Path2D | null = null;
  for (const path of geometry.paths) {
    tracePath(stroke, path, aspect);
    if (path.fill && path.closed) {
      fill ??= new Path2D();
      tracePath(fill, path, aspect);
    }
  }
  geometry.stroke = stroke;
  geometry.fill = fill;
};

type ScreenRects = readonly { x: number; y: number; width: number; height: number }[];

const layerHits = (
  geometry: ILayerGeometry,
  placement: SheetPlacement,
  rects: ScreenRects,
): boolean => hits(boxOf(geometry.bounds, placement), rects);

/** Слои одного цвета склеены в один путь: один проход на цвет. */
interface IColorGroup {
  readonly layers: ILayerGeometry[];
  stroke: Path2D | null;
  fill: Path2D | null;
}

export const createCadPainter = (data: ICadPaintData): LayerPainter => {
  const entry = entryOf(data.paths);
  const shownLayers = [...data.visibleLayers]
    .sort((a, b) => a - b)
    .map((layer) => entry.layers.get(layer))
    .filter((geometry): geometry is ILayerGeometry => geometry !== undefined);

  const groups = new Map<string, IColorGroup>();
  for (const geometry of shownLayers) {
    const color = data.layerColors[geometry.layer] ?? data.ink;
    const group = groups.get(color);
    if (group) group.layers.push(geometry);
    else groups.set(color, { layers: [geometry], stroke: null, fill: null });
  }
  /** Версия путей, под которую собраны группы. */
  let builtVersion = -1;

  const buildGroups = (): void => {
    if (builtVersion === entry.version) return;
    builtVersion = entry.version;
    for (const group of groups.values()) {
      for (const geometry of group.layers) ensureLayerPaths(geometry, entry.aspect);
      const [only] = group.layers;
      if (group.layers.length === 1 && only) {
        group.stroke = only.stroke;
        group.fill = only.fill;
        continue;
      }
      const stroke = new Path2D();
      let fill: Path2D | null = null;
      for (const geometry of group.layers) {
        if (geometry.stroke) stroke.addPath(geometry.stroke);
        if (geometry.fill) {
          fill ??= new Path2D();
          fill.addPath(geometry.fill);
        }
      }
      group.stroke = stroke;
      group.fill = fill;
    }
  };

  const groupHits = (group: IColorGroup, placement: SheetPlacement, rects: ScreenRects): boolean =>
    group.layers.some((geometry) => layerHits(geometry, placement, rects));

  return {
    paint: (context, placement, ratio, area) => {
      const rects = beginLayerPaint(context, ratio, area, MARGIN);

      if (data.paper !== null) {
        context.fillStyle = data.paper;
        context.fillRect(placement.x, placement.y, placement.width, placement.height);
      }

      const shown = [...groups].filter(([, group]) => groupHits(group, placement, rects));
      if (shown.length > 0 && placement.width > 0 && placement.height > 0) {
        ensureAspect(entry, placement.height / placement.width);
        buildGroups();

        // Пути заданы в «листовых» единицах: на кадре только перенос и масштаб, без обхода точек.
        const scaleX = placement.width / PATH_UNITS;
        const scaleY = placement.height / (PATH_UNITS * entry.aspect);
        context.save();
        context.translate(placement.x, placement.y);
        context.scale(scaleX, scaleY);
        context.lineWidth = LINE_WIDTH / scaleX;
        context.lineJoin = 'round';

        // Заливки отдельным проходом и с малой плотностью: под ними должны читаться линии.
        context.globalAlpha = data.opacity * FILL_ALPHA;
        for (const [color, group] of shown) {
          if (!group.fill) continue;
          context.fillStyle = color;
          context.fill(group.fill);
        }

        context.globalAlpha = data.opacity;
        for (const [color, group] of shown) {
          if (!group.stroke) continue;
          context.strokeStyle = color;
          context.stroke(group.stroke);
        }
        context.restore();
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
      return [...groups.values()].some((group) =>
        group.layers.some(
          (geometry) =>
            layerHits(geometry, placement, rects) &&
            geometry.paths.some((path) => hits(boxOf(path.bounds, placement), rects)),
        ),
      );
    },
  };
};
