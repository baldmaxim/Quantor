/**
 * Привязка точек при ручном рисовании зон листа: к вершинам и рёбрам готовых зон, к уже
 * поставленным вершинам черновика, строго по горизонтали или вертикали (Shift).
 *
 * Чистая логика без DOM. Расстояния меряются в пикселях экрана: нормализованные доли по x и y
 * неизотропны (лист не квадратный), поэтому разности переводятся в пиксели масштабом листа.
 * Приоритет: вершина > ребро. Индекс строится один раз на смену набора зон, а не на каждое
 * движение указателя.
 */

import type { CadZoneRead } from '@quantor/api-client';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import { GridIndex } from '@/lib/viewer/spatial-index';

/** Радиус привязки, пикселей экрана. */
export const SNAP_RADIUS_PX = 10;

export type SnapKind = 'vertex' | 'edge' | 'ortho' | 'none';

export interface ISnapResult {
  readonly point: NormalizedPoint;
  readonly kind: SnapKind;
}

/** Пикселей экрана на единицу нормализованной координаты по каждой оси. */
export interface ISnapScale {
  readonly x: number;
  readonly y: number;
}

/** Контур для привязки: помещение замкнуто, дверь - отрезок. */
export interface ISnapShape {
  readonly points: readonly (readonly [number, number])[];
  readonly closed: boolean;
}

interface ISnapEdge {
  readonly a: NormalizedPoint;
  readonly b: NormalizedPoint;
}

export interface ISnapIndex {
  readonly vertices: readonly NormalizedPoint[];
  readonly edges: readonly ISnapEdge[];
  readonly vertexGrid: GridIndex<number>;
  readonly edgeGrid: GridIndex<number>;
}

export interface ISnapOptions {
  readonly index: ISnapIndex;
  readonly scale: ISnapScale;
  /** Уже поставленные вершины черновика по порядку; последняя - опорная для ortho. */
  readonly placed: readonly NormalizedPoint[];
  readonly shift: boolean;
  readonly alt: boolean;
  readonly radiusPx?: number;
}

/** Зоны листа -> контуры привязки. */
export const zonesToSnapShapes = (zones: readonly CadZoneRead[]): ISnapShape[] =>
  zones.map((zone) => ({ points: zone.points, closed: zone.kind !== 'door' }));

export const buildSnapIndex = (shapes: readonly ISnapShape[]): ISnapIndex => {
  const vertices: NormalizedPoint[] = [];
  const edges: ISnapEdge[] = [];
  const vertexGrid = new GridIndex<number>();
  const edgeGrid = new GridIndex<number>();

  for (const shape of shapes) {
    const points = shape.points.map(([x, y]) => ({ x, y }));
    for (const point of points) {
      vertexGrid.set(vertices.length, {
        minX: point.x,
        minY: point.y,
        maxX: point.x,
        maxY: point.y,
      });
      vertices.push(point);
    }
    const count = points.length;
    const last = shape.closed && count > 2 ? count : count - 1;
    for (let at = 0; at < last; at += 1) {
      const a = points[at] as NormalizedPoint;
      const b = points[(at + 1) % count] as NormalizedPoint;
      edgeGrid.set(edges.length, {
        minX: Math.min(a.x, b.x),
        minY: Math.min(a.y, b.y),
        maxX: Math.max(a.x, b.x),
        maxY: Math.max(a.y, b.y),
      });
      edges.push({ a, b });
    }
  }
  return { vertices, edges, vertexGrid, edgeGrid };
};

/** Расстояние между точками в пикселях экрана. */
const screenDistance = (a: NormalizedPoint, b: NormalizedPoint, scale: ISnapScale): number =>
  Math.hypot((a.x - b.x) * scale.x, (a.y - b.y) * scale.y);

const windowAround = (point: NormalizedPoint, scale: ISnapScale, radiusPx: number) => ({
  minX: point.x - radiusPx / scale.x,
  minY: point.y - radiusPx / scale.y,
  maxX: point.x + radiusPx / scale.x,
  maxY: point.y + radiusPx / scale.y,
});

const samePoint = (a: NormalizedPoint, b: NormalizedPoint): boolean => a.x === b.x && a.y === b.y;

/**
 * Ближайшая вершина в радиусе: вершины готовых зон и поставленные вершины черновика.
 * Последняя поставленная (и совпадающая с ней вершина зоны) не цель: звено нулевой длины
 * бессмысленно.
 */
const nearestVertex = (
  target: NormalizedPoint,
  { index, scale, placed }: ISnapOptions,
  radiusPx: number,
): NormalizedPoint | null => {
  let best: NormalizedPoint | null = null;
  let bestDistance = radiusPx;
  const anchor = placed[placed.length - 1];
  const consider = (vertex: NormalizedPoint) => {
    if (anchor && samePoint(vertex, anchor)) return;
    const distance = screenDistance(vertex, target, scale);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = vertex;
    }
  };
  for (const at of index.vertexGrid.search(windowAround(target, scale, radiusPx))) {
    const vertex = index.vertices[at];
    if (vertex) consider(vertex);
  }
  placed.slice(0, -1).forEach(consider);
  return best;
};

/** Ближайшая к точке точка ребра в радиусе (проекция на отрезок в пикселях). */
const nearestOnEdge = (
  target: NormalizedPoint,
  { index, scale }: ISnapOptions,
  radiusPx: number,
): NormalizedPoint | null => {
  let best: NormalizedPoint | null = null;
  let bestDistance = radiusPx;
  for (const at of index.edgeGrid.search(windowAround(target, scale, radiusPx))) {
    const edge = index.edges[at];
    if (!edge) continue;
    const dx = (edge.b.x - edge.a.x) * scale.x;
    const dy = (edge.b.y - edge.a.y) * scale.y;
    const lengthSquared = dx * dx + dy * dy;
    if (lengthSquared === 0) continue;
    const t = Math.min(
      1,
      Math.max(
        0,
        ((target.x - edge.a.x) * scale.x * dx + (target.y - edge.a.y) * scale.y * dy) /
          lengthSquared,
      ),
    );
    const candidate = {
      x: edge.a.x + (edge.b.x - edge.a.x) * t,
      y: edge.a.y + (edge.b.y - edge.a.y) * t,
    };
    const distance = screenDistance(candidate, target, scale);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = candidate;
    }
  }
  return best;
};

/** Пересечение оси ortho (через anchor) с ближайшим ребром около точки проекции. */
const orthoEdgeCrossing = (
  anchor: NormalizedPoint,
  horizontal: boolean,
  projected: NormalizedPoint,
  options: ISnapOptions,
  radiusPx: number,
): NormalizedPoint | null => {
  const { index, scale } = options;
  let best: NormalizedPoint | null = null;
  let bestDistance = radiusPx;
  for (const at of index.edgeGrid.search(windowAround(projected, scale, radiusPx))) {
    const edge = index.edges[at];
    if (!edge) continue;
    // Ось горизонтальна: y = anchor.y; вертикальна: x = anchor.x.
    const from = horizontal ? edge.a.y : edge.a.x;
    const to = horizontal ? edge.b.y : edge.b.x;
    const level = horizontal ? anchor.y : anchor.x;
    if (from === to) continue; // ребро параллельно оси
    const t = (level - from) / (to - from);
    if (t < 0 || t > 1) continue;
    const crossing = horizontal
      ? { x: edge.a.x + (edge.b.x - edge.a.x) * t, y: anchor.y }
      : { x: anchor.x, y: edge.a.y + (edge.b.y - edge.a.y) * t };
    const distance = screenDistance(crossing, projected, scale);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = crossing;
    }
  }
  return best;
};

/**
 * Точка с учётом привязки. Alt - привязка выключена. Shift при поставленной вершине - ortho:
 * через предыдущую вершину по оси с большим сдвигом на экране; вершина рядом с проекцией
 * важнее, затем пересечение оси с ребром, иначе чистая проекция.
 */
export const snapPoint = (raw: NormalizedPoint, options: ISnapOptions): ISnapResult => {
  const { scale, placed, shift, alt } = options;
  const radiusPx = options.radiusPx ?? SNAP_RADIUS_PX;
  if (alt || !(scale.x > 0) || !(scale.y > 0)) return { point: raw, kind: 'none' };

  const anchor = placed[placed.length - 1];
  if (shift && anchor) {
    const horizontal =
      Math.abs((raw.x - anchor.x) * scale.x) >= Math.abs((raw.y - anchor.y) * scale.y);
    const projected = horizontal ? { x: raw.x, y: anchor.y } : { x: anchor.x, y: raw.y };
    const vertex = nearestVertex(projected, options, radiusPx);
    if (vertex) return { point: vertex, kind: 'vertex' };
    const crossing = orthoEdgeCrossing(anchor, horizontal, projected, options, radiusPx);
    if (crossing && !samePoint(crossing, anchor)) return { point: crossing, kind: 'edge' };
    return { point: projected, kind: 'ortho' };
  }

  const vertex = nearestVertex(raw, options, radiusPx);
  if (vertex) return { point: vertex, kind: 'vertex' };
  const edge = nearestOnEdge(raw, options, radiusPx);
  if (edge) return { point: edge, kind: 'edge' };
  return { point: raw, kind: 'none' };
};
