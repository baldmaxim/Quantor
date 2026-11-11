/**
 * Правка контура зоны-помещения: вершины и середины рёбер как ручки (ADR-0042 п.5).
 *
 * Чистые функции без DOM. Кольцо - пары [x, y] в долях листа, как в API; каждая правка возвращает
 * новое кольцо. Попадание по ручкам считается в пикселях экрана по уже переведённым вершинам.
 */

import type { ScreenPoint } from '@/lib/viewer/coordinates';

import { MIN_ROOM_POINTS } from './zones';

export type EditRing = readonly (readonly [number, number])[];

/** Радиус попадания по ручке, пикселей экрана. */
export const HANDLE_HIT_PX = 12;
/** Ручка середины ребра появляется, только если ребро на экране не короче этого. */
export const MIDPOINT_MIN_EDGE_PX = 24;

const copy = (ring: EditRing): [number, number][] => ring.map(([x, y]) => [x, y]);

/** Новое кольцо с вершиной `index`, перенесённой в `point`; индекс вне кольца - без изменений. */
export const moveVertex = (
  ring: EditRing,
  index: number,
  point: { readonly x: number; readonly y: number },
): [number, number][] => {
  const next = copy(ring);
  if (index >= 0 && index < next.length) next[index] = [point.x, point.y];
  return next;
};

/** Удаляет вершину; `null` - вершин осталось бы меньше трёх или индекс вне кольца. */
export const removeVertex = (ring: EditRing, index: number): [number, number][] | null => {
  if (ring.length <= MIN_ROOM_POINTS || index < 0 || index >= ring.length) return null;
  return copy(ring).filter((_, at) => at !== index);
};

/** Вставляет вершину в середину ребра `edge` (от `edge` к `edge + 1`); её индекс - `edge + 1`. */
export const insertMidpoint = (
  ring: EditRing,
  edge: number,
): { readonly ring: [number, number][]; readonly index: number } | null => {
  if (edge < 0 || edge >= ring.length) return null;
  const a = ring[edge] as readonly [number, number];
  const b = ring[(edge + 1) % ring.length] as readonly [number, number];
  const next = copy(ring);
  next.splice(edge + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
  return { ring: next, index: edge + 1 };
};

/** Ближайшая вершина в радиусе от щелчка; `-1` - нет. Вершины - в пикселях экрана. */
export const hitVertex = (
  vertices: readonly ScreenPoint[],
  click: ScreenPoint,
  radius: number = HANDLE_HIT_PX,
): number => {
  let best = -1;
  let bestDistance = radius;
  vertices.forEach((vertex, index) => {
    const distance = Math.hypot(vertex.x - click.x, vertex.y - click.y);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return best;
};

/** Середина ребра на экране; `null` - ребро слишком короткое для ручки. */
export const edgeHandle = (
  vertices: readonly ScreenPoint[],
  edge: number,
  minEdgePx: number = MIDPOINT_MIN_EDGE_PX,
): ScreenPoint | null => {
  const a = vertices[edge];
  const b = vertices[(edge + 1) % vertices.length];
  if (!a || !b || Math.hypot(a.x - b.x, a.y - b.y) < minEdgePx) return null;
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
};

/** Ребро, у середины которого щелчок; `-1` - нет. */
export const hitMidpoint = (
  vertices: readonly ScreenPoint[],
  click: ScreenPoint,
  radius: number = HANDLE_HIT_PX,
  minEdgePx: number = MIDPOINT_MIN_EDGE_PX,
): number => {
  let best = -1;
  let bestDistance = radius;
  for (let edge = 0; edge < vertices.length; edge += 1) {
    const handle = edgeHandle(vertices, edge, minEdgePx);
    if (!handle) continue;
    const distance = Math.hypot(handle.x - click.x, handle.y - click.y);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = edge;
    }
  }
  return best;
};
