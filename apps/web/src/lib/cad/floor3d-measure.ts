import { MM_IN_M, type IFloor3dCenter } from './floor3d-geometry';

/**
 * Измерение расстояний в 3D-виде этажа (ADR-0039): чистые функции без DOM и без three.js.
 * Вид только показывает: это справочный замер «от точки до точки», не величина для расчёта.
 */

/** Точка сцены three (м, относительно центра модели): X, высота, Z. */
export type SceneVec3 = readonly [number, number, number];

/** Точка в системе DXF, мм: x, y - план, z - высота. */
export interface IPointMm {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

/** Порог привязки к вершине треугольника, px. */
export const SNAP_THRESHOLD_PX = 12;

/** Сцена -> мм DXF: обратное к `toScenePoint` (центрирование и деление на 1000, ось Z сцены = -Y DXF). */
export const sceneToMm = (point: SceneVec3, center: IFloor3dCenter): IPointMm => ({
  x: point[0] * MM_IN_M + center.x,
  y: -point[2] * MM_IN_M + center.y,
  z: point[1] * MM_IN_M + center.z,
});

export interface IMeasurement {
  readonly distanceMm: number;
  readonly dx: number;
  readonly dy: number;
  /** По высоте. */
  readonly dz: number;
}

export const measureBetween = (a: IPointMm, b: IPointMm): IMeasurement => {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dz = b.z - a.z;
  return { distanceMm: Math.hypot(dx, dy, dz), dx, dy, dz };
};

/** Целые мм с пробелами тысяч; знак - только у ненулевого значения (после округления). */
export const formatMm = (valueMm: number, signed = false): string => {
  const rounded = Math.round(valueMm);
  const text = Math.abs(rounded).toLocaleString('ru-RU', { maximumFractionDigits: 0, useGrouping: true });
  if (!signed || rounded === 0) return text;
  return `${rounded < 0 ? '−' : '+'}${text}`;
};

export interface IMeasureText {
  /** «1 234 мм». */
  readonly distance: string;
  /** «Δx +1 000 · Δy −500 · Δz 0 мм». */
  readonly deltas: string;
}

export const measureText = (measurement: IMeasurement): IMeasureText => ({
  distance: `${formatMm(measurement.distanceMm)} мм`,
  deltas: `Δx ${formatMm(measurement.dx, true)} · Δy ${formatMm(measurement.dy, true)} · Δz ${formatMm(measurement.dz, true)} мм`,
});

/** Подпись для двух точек сцены. */
export const measureLabel = (a: SceneVec3, b: SceneVec3, center: IFloor3dCenter): IMeasureText =>
  measureText(measureBetween(sceneToMm(a, center), sceneToMm(b, center)));

export interface IScreenPoint {
  readonly x: number;
  readonly y: number;
}

/**
 * Привязка к вершине: из вершин треугольника попадания берётся ближайшая к точке клика на экране;
 * дальше порога - остаётся сама точка попадания. `project` вернул `null` - вершина не видна.
 */
export const snapToNearestVertex = (
  hit: SceneVec3,
  vertices: readonly SceneVec3[],
  clickScreen: IScreenPoint,
  project: (point: SceneVec3) => IScreenPoint | null,
  thresholdPx: number = SNAP_THRESHOLD_PX,
): { readonly point: SceneVec3; readonly snapped: boolean } => {
  let best: SceneVec3 | null = null;
  let bestDistance = thresholdPx;
  for (const vertex of vertices) {
    const screen = project(vertex);
    if (screen === null) continue;
    const distance = Math.hypot(screen.x - clickScreen.x, screen.y - clickScreen.y);
    if (distance <= bestDistance) {
      best = vertex;
      bestDistance = distance;
    }
  }
  return best === null ? { point: hit, snapped: false } : { point: best, snapped: true };
};

/** Середина отрезка в сцене - к ней привязана подпись. */
export const midpoint = (a: SceneVec3, b: SceneVec3): SceneVec3 => [
  (a[0] + b[0]) / 2,
  (a[1] + b[1]) / 2,
  (a[2] + b[2]) / 2,
];

// --------------------------------------------------------------------------- привязка при наведении

/** Порог привязки к ребру, px. */
export const SNAP_EDGE_THRESHOLD_PX = 8;

/** Что поймано под курсором: угол призмы, ребро или просто точка на грани. */
export type SnapKind = 'vertex' | 'edge' | 'face';

export const SNAP_KIND_LABELS: Record<SnapKind, string> = {
  vertex: 'угол',
  edge: 'ребро',
  face: 'грань',
};

export interface ISnapResult {
  readonly kind: SnapKind;
  readonly point: SceneVec3;
}

export type Triangle3 = readonly [SceneVec3, SceneVec3, SceneVec3];
export type ProjectFn = (point: SceneVec3) => IScreenPoint | null;

const lerp3 = (a: SceneVec3, b: SceneVec3, t: number): SceneVec3 => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];

const TERNARY_STEPS = 28;

/**
 * Ближайшая к курсору (по экрану) точка отрезка ребра. Образ отрезка на экране монотонен по
 * параметру, поэтому расстояние до курсора унимодально - тернарный поиск точен и не требует
 * глубины (перспективная интерполяция учтена самой проекцией). Конец за камерой - `null`.
 */
export const closestPointOnEdge = (
  a: SceneVec3,
  b: SceneVec3,
  cursor: IScreenPoint,
  project: ProjectFn,
): { readonly point: SceneVec3; readonly distancePx: number } | null => {
  if (project(a) === null || project(b) === null) return null;
  const distanceAt = (t: number): number => {
    const screen = project(lerp3(a, b, t));
    return screen === null ? Infinity : Math.hypot(screen.x - cursor.x, screen.y - cursor.y);
  };
  let low = 0;
  let high = 1;
  for (let step = 0; step < TERNARY_STEPS; step += 1) {
    const m1 = low + (high - low) / 3;
    const m2 = high - (high - low) / 3;
    if (distanceAt(m1) <= distanceAt(m2)) high = m2;
    else low = m1;
  }
  const t = (low + high) / 2;
  const distancePx = distanceAt(t);
  return Number.isFinite(distancePx) ? { point: lerp3(a, b, t), distancePx } : null;
};

/**
 * Привязка точки под курсором в порядке приоритета: угол треугольника в 12 px -> ближайшая точка
 * ребра в 8 px (только рёбра, помеченные `featureEdges`: граница грани, не диагональ триангуляции)
 * -> сама точка попадания на грани. Ребро `i` идёт от вершины `i` к вершине `(i + 1) % 3`.
 */
export const snapPoint = (
  hit: SceneVec3,
  triangle: Triangle3,
  featureEdges: readonly [boolean, boolean, boolean],
  cursor: IScreenPoint,
  project: ProjectFn,
  vertexPx: number = SNAP_THRESHOLD_PX,
  edgePx: number = SNAP_EDGE_THRESHOLD_PX,
): ISnapResult => {
  const vertex = snapToNearestVertex(hit, triangle, cursor, project, vertexPx);
  if (vertex.snapped) return { kind: 'vertex', point: vertex.point };
  let best: { point: SceneVec3; distancePx: number } | null = null;
  for (let edge = 0; edge < 3; edge += 1) {
    if (featureEdges[edge] !== true) continue;
    const found = closestPointOnEdge(
      triangle[edge] as SceneVec3,
      triangle[(edge + 1) % 3] as SceneVec3,
      cursor,
      project,
    );
    if (found !== null && found.distancePx <= edgePx && (best === null || found.distancePx < best.distancePx)) {
      best = found;
    }
  }
  return best === null ? { kind: 'face', point: hit } : { kind: 'edge', point: best.point };
};

/** Рёбра сетки: какие из них - настоящие рёбра призм, а не диагонали внутри плоской грани. */
export interface IFeatureEdges {
  /** Ребро `edge` (0..2) треугольника `triangle`. */
  readonly isFeature: (triangle: number, edge: 0 | 1 | 2) => boolean;
}

const COPLANAR_DOT = 1 - 1e-6;
/** Координаты в метрах: ключ вершины с точностью 0,1 мм. */
const KEY_SCALE = 1e4;

/**
 * Индекс рёбер сетки треугольников: ребро - «настоящее», если у него один треугольник или среди
 * смежных (по совпадающим концам, в том числе у соседних слитых призм) есть два с неколлинеарными
 * нормалями. Диагональ плоской грани (два треугольника с одной нормалью) настоящей не считается.
 * `positions` - xyz подряд; `indices` - `null` для неиндексированной сетки.
 */
export const buildFeatureEdges = (
  positions: ArrayLike<number>,
  indices: ArrayLike<number> | null,
): IFeatureEdges => {
  const triangles = Math.floor((indices === null ? positions.length / 3 : indices.length) / 3);
  const vertexAt = (triangle: number, corner: number): SceneVec3 => {
    const index = indices === null ? triangle * 3 + corner : (indices[triangle * 3 + corner] as number);
    return [positions[index * 3] as number, positions[index * 3 + 1] as number, positions[index * 3 + 2] as number];
  };
  const keyOf = (v: SceneVec3): string =>
    `${Math.round(v[0] * KEY_SCALE)},${Math.round(v[1] * KEY_SCALE)},${Math.round(v[2] * KEY_SCALE)}`;

  const normals: (SceneVec3 | null)[] = [];
  const edgeTriangles = new Map<string, number[]>();
  const edgeKeys: string[] = [];
  for (let t = 0; t < triangles; t += 1) {
    const [a, b, c] = [vertexAt(t, 0), vertexAt(t, 1), vertexAt(t, 2)];
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const n = [
      (u[1] as number) * (w[2] as number) - (u[2] as number) * (w[1] as number),
      (u[2] as number) * (w[0] as number) - (u[0] as number) * (w[2] as number),
      (u[0] as number) * (w[1] as number) - (u[1] as number) * (w[0] as number),
    ] as [number, number, number];
    const length = Math.hypot(n[0], n[1], n[2]);
    normals.push(length > 0 ? [n[0] / length, n[1] / length, n[2] / length] : null);
    const corners = [a, b, c];
    for (let e = 0; e < 3; e += 1) {
      const ka = keyOf(corners[e] as SceneVec3);
      const kb = keyOf(corners[(e + 1) % 3] as SceneVec3);
      const key = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
      edgeKeys.push(key);
      const list = edgeTriangles.get(key);
      if (list === undefined) edgeTriangles.set(key, [t]);
      else list.push(t);
    }
  }

  const featureByKey = new Map<string, boolean>();
  const featureOfKey = (key: string): boolean => {
    const cached = featureByKey.get(key);
    if (cached !== undefined) return cached;
    const list = edgeTriangles.get(key) ?? [];
    let feature = list.length < 2;
    for (let i = 0; i < list.length && !feature; i += 1) {
      const ni = normals[list[i] as number];
      if (ni === null || ni === undefined) continue;
      for (let j = i + 1; j < list.length; j += 1) {
        const nj = normals[list[j] as number];
        if (nj === null || nj === undefined) continue;
        if (ni[0] * nj[0] + ni[1] * nj[1] + ni[2] * nj[2] < COPLANAR_DOT) {
          feature = true;
          break;
        }
      }
    }
    featureByKey.set(key, feature);
    return feature;
  };

  return {
    isFeature: (triangle, edge) => {
      const key = edgeKeys[triangle * 3 + edge];
      return key === undefined ? false : featureOfKey(key);
    },
  };
};
