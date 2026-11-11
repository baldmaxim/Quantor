/**
 * Разрез зоны-помещения линией от границы до границы (ADR-0042 п.5).
 *
 * Чистая геометрия без DOM и сети, в нормализованных координатах листа. Проверки (пересечения,
 * «середина внутри») аффинно-инвариантны, поэтому неизотропность долей по x и y им не мешает.
 * Площадь и периметр частей считает сервер; здесь площадь нужна только как знак и чтобы
 * отличить большую часть от меньшей.
 */

import type { NormalizedPoint } from '@/lib/viewer/coordinates';

export type ZoneRing = readonly (readonly [number, number])[];

/** Точка разреза: индекс ребра (от вершины `edge` к `edge + 1` по кругу) и сама точка на нём. */
export interface ISplitPoint {
  readonly edge: number;
  readonly point: NormalizedPoint;
}

export type SplitResult =
  | { readonly ok: true; readonly rings: readonly [ZoneRing, ZoneRing] }
  | { readonly ok: false; readonly reason: string };

/** Разрезать можно помещение квартиры и МОП: дверь и парковочное место - нет. */
export const canSplitZoneKind = (kind: string): boolean =>
  kind === 'room_apartment' || kind === 'room_mop';

export const SPLIT_OUTSIDE_TEXT =
  'Линия разреза должна пройти внутри помещения от границы до границы';

/** Допуск совпадения точки с вершиной и принадлежности ребру, доли листа. */
const POINT_EPS = 1e-6;
/** Знаки векторных произведений и площади ниже этого - нуль. */
const CROSS_EPS = 1e-12;
const AREA_EPS = 1e-10;

type Pair = [number, number];

const toPair = (point: NormalizedPoint): Pair => [point.x, point.y];

const ringPoint = (ring: ZoneRing, index: number): Pair => {
  const point = ring[((index % ring.length) + ring.length) % ring.length] as readonly [
    number,
    number,
  ];
  return [point[0], point[1]];
};

/** Площадь многоугольника (всегда неотрицательная). */
export const ringArea = (ring: ZoneRing): number => {
  let twice = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const [x0, y0] = ringPoint(ring, index);
    const [x1, y1] = ringPoint(ring, index + 1);
    twice += x0 * y1 - x1 * y0;
  }
  return Math.abs(twice) / 2;
};

/** Ближайшая к точке точка отрезка и расстояние до неё. */
const nearestOnSegment = (
  point: NormalizedPoint,
  a: Pair,
  b: Pair,
): { readonly t: number; readonly distance: number } => {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  const t =
    lengthSquared === 0
      ? 0
      : Math.min(1, Math.max(0, ((point.x - a[0]) * dx + (point.y - a[1]) * dy) / lengthSquared));
  return { t, distance: Math.hypot(point.x - (a[0] + dx * t), point.y - (a[1] + dy * t)) };
};

/**
 * Ребро кольца, на котором лежит точка; `null` - точка не на границе. Точка на вершине получает
 * любое из двух смежных рёбер: `splitRing` сама распознаёт вершину.
 */
export const locateOnRing = (ring: ZoneRing, point: NormalizedPoint): ISplitPoint | null => {
  let best: { edge: number; distance: number } | null = null;
  for (let edge = 0; edge < ring.length; edge += 1) {
    const { distance } = nearestOnSegment(point, ringPoint(ring, edge), ringPoint(ring, edge + 1));
    if (best === null || distance < best.distance) best = { edge, distance };
  }
  return best !== null && best.distance <= POINT_EPS ? { edge: best.edge, point } : null;
};

type Resolved =
  | { readonly kind: 'vertex'; readonly index: number }
  | { readonly kind: 'edge'; readonly edge: number; readonly t: number; readonly point: Pair };

/** Точка разреза -> существующая вершина или вставка в ребро; `null` - точка не на своём ребре. */
const resolve = (ring: ZoneRing, split: ISplitPoint): Resolved | null => {
  const count = ring.length;
  if (!Number.isInteger(split.edge) || split.edge < 0 || split.edge >= count) return null;
  const a = ringPoint(ring, split.edge);
  const b = ringPoint(ring, split.edge + 1);
  const { point } = split;
  if (Math.hypot(point.x - a[0], point.y - a[1]) <= POINT_EPS) {
    return { kind: 'vertex', index: split.edge };
  }
  if (Math.hypot(point.x - b[0], point.y - b[1]) <= POINT_EPS) {
    return { kind: 'vertex', index: (split.edge + 1) % count };
  }
  const { t, distance } = nearestOnSegment(point, a, b);
  if (distance > POINT_EPS) return null;
  return { kind: 'edge', edge: split.edge, t, point: toPair(point) };
};

const sign = (value: number): number => (Math.abs(value) < CROSS_EPS ? 0 : value > 0 ? 1 : -1);

const orient = (o: Pair, a: Pair, b: Pair): number =>
  sign((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]));

const withinBox = (a: Pair, b: Pair, p: Pair): boolean =>
  p[0] >= Math.min(a[0], b[0]) - POINT_EPS &&
  p[0] <= Math.max(a[0], b[0]) + POINT_EPS &&
  p[1] >= Math.min(a[1], b[1]) - POINT_EPS &&
  p[1] <= Math.max(a[1], b[1]) + POINT_EPS;

/** Пересекаются ли отрезки, включая касание и наложение. */
const segmentsTouch = (a: Pair, b: Pair, c: Pair, d: Pair): boolean => {
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  if (o1 * o2 < 0 && o3 * o4 < 0) return true;
  return (
    (o1 === 0 && withinBox(a, b, c)) ||
    (o2 === 0 && withinBox(a, b, d)) ||
    (o3 === 0 && withinBox(c, d, a)) ||
    (o4 === 0 && withinBox(c, d, b))
  );
};

/** Точка строго внутри многоугольника: на границе - не внутри. */
const strictlyInside = (ring: ZoneRing, point: Pair): boolean => {
  const probe = { x: point[0], y: point[1] };
  let inside = false;
  for (let index = 0; index < ring.length; index += 1) {
    const a = ringPoint(ring, index);
    const b = ringPoint(ring, index + 1);
    if (nearestOnSegment(probe, a, b).distance <= POINT_EPS) return false;
    if (a[1] > point[1] !== b[1] > point[1]) {
      const crossingX = a[0] + ((point[1] - a[1]) / (b[1] - a[1])) * (b[0] - a[0]);
      if (point[0] < crossingX) inside = !inside;
    }
  }
  return inside;
};

const fail = (): SplitResult => ({ ok: false, reason: SPLIT_OUTSIDE_TEXT });

/** Вершины кольца от `from` до `to` включительно, обходом по кругу. */
const slice = (ring: readonly Pair[], from: number, to: number): Pair[] => {
  const out: Pair[] = [];
  for (let index = from; ; index = (index + 1) % ring.length) {
    out.push(ring[index] as Pair);
    if (index === to) return out;
  }
};

/**
 * Делит кольцо отрезком между двумя точками на границе. Точки вставляются в кольцо (точка на
 * вершине не дублирует её), части идут по ходу кольца: от `a` к `b` и от `b` к `a`.
 *
 * Отказ (`ok: false`), если точка не на границе, точки совпадают, отрезок пересекает или касается
 * других рёбер, его середина не строго внутри многоугольника, или у части меньше трёх вершин
 * либо нулевая площадь.
 */
export const splitRing = (ring: ZoneRing, a: ISplitPoint, b: ISplitPoint): SplitResult => {
  if (ring.length < 3) return fail();
  const first = resolve(ring, a);
  const second = resolve(ring, b);
  if (first === null || second === null) return fail();

  // Вставки в рёбра; вершины остаются на месте. Две вставки в одно ребро идут по возрастанию t.
  const inserts = [first, second].flatMap((resolved, order) =>
    resolved.kind === 'edge' ? [{ ...resolved, order }] : [],
  );
  inserts.sort((left, right) => left.edge - right.edge || left.t - right.t);

  const points: Pair[] = [];
  const at: [number, number] = [-1, -1];
  for (let index = 0; index < ring.length; index += 1) {
    if (first.kind === 'vertex' && first.index === index) at[0] = points.length;
    if (second.kind === 'vertex' && second.index === index) at[1] = points.length;
    points.push(ringPoint(ring, index));
    for (const insert of inserts) {
      if (insert.edge !== index) continue;
      at[insert.order] = points.length;
      points.push(insert.point);
    }
  }
  const [ia, ib] = at;
  if (ia < 0 || ib < 0 || ia === ib) return fail();
  const start = points[ia] as Pair;
  const end = points[ib] as Pair;
  if (Math.hypot(start[0] - end[0], start[1] - end[1]) <= POINT_EPS) return fail();

  // Отрезок не должен задевать рёбра, не примыкающие к его концам.
  for (let index = 0; index < points.length; index += 1) {
    const next = (index + 1) % points.length;
    if (index === ia || index === ib || next === ia || next === ib) continue;
    if (segmentsTouch(start, end, points[index] as Pair, points[next] as Pair)) return fail();
  }
  if (!strictlyInside(points, [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2])) return fail();

  const half1 = slice(points, ia, ib);
  const half2 = slice(points, ib, ia);
  for (const half of [half1, half2]) {
    if (half.length < 3 || ringArea(half) <= AREA_EPS) return fail();
  }
  return { ok: true, rings: [half1, half2] };
};
