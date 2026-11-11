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
