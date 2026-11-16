import type { CadBuilding3dFloorRead, CadSitePinCreate } from '@quantor/api-client';

import { cleanOutline } from './building3d-geometry';

/**
 * Ручная привязка корпуса к площадке по двум точкам (ADR-0052): чистая геометрия панелей плана.
 * Точки хранятся в мм кадра вида ЭТАЖА (до `rotation_deg` и `offset_mm` этажа) - так их ждёт сервер.
 * Итоговый поворот, сдвиг и невязку считает сервер; здесь только предварительная подсказка.
 */

export type MmPoint = readonly [number, number];
/** Две точки привязки; `null` - ещё не поставлена. */
export type PinPoints = readonly [MmPoint | null, MmPoint | null];
export type PinSlot = 0 | 1;

export const EMPTY_PIN_POINTS: PinPoints = [null, null];

/** Те же пороги, что на сервере (`cad_site_pins_math`): короткая база и расхождение длин отрезков. */
export const SITE_PIN_MIN_BASELINE_MM = 5000;
export const SITE_PIN_MAX_MISMATCH = 0.01;
/** Экранный допуск привязки к вершине контура, px. */
export const SITE_PIN_SNAP_PX = 14;

const QUARTER_DEG = 90;

/** Поворот вокруг начала против часовой стрелки; кратные 90 градусам - точно, как на сервере. */
const rotate = (point: MmPoint, degrees: number): MmPoint => {
  const [x, y] = point;
  const turns = degrees / QUARTER_DEG;
  if (turns === Math.round(turns)) {
    const quarter = ((Math.round(turns) % 4) + 4) % 4;
    return ([[x, y], [-y, x], [-x, -y], [y, -x]] as const)[quarter] as MmPoint;
  }
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [x * cos - y * sin, x * sin + y * cos];
};

const clean = (value: number): number => Math.round(value * 1000) / 1000 + 0;

/**
 * Точка этажа из его итоговых координат в сборке (`R(rotation_deg) · p + offset_mm`) обратно в кадр
 * вида листа: `p = R(-rotation_deg) · (q - offset_mm)`.
 */
export const toViewFrame = (point: MmPoint, floor: Pick<CadBuilding3dFloorRead, 'rotation_deg' | 'offset_mm'>): MmPoint => {
  const [ox, oy] = floor.offset_mm;
  const [x, y] = rotate([point[0] - ox, point[1] - oy], -(floor.rotation_deg ?? 0));
  return [clean(x), clean(y)];
};

export interface IPlanBounds {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

/** Вид сверху этажа в мм кадра вида: контуры и вершины привязки. */
export interface ISitePlan {
  readonly rings: readonly (readonly MmPoint[])[];
  readonly vertices: readonly MmPoint[];
  readonly bounds: IPlanBounds;
}

/**
 * План этажа из того, что отдаёт запрос здания: контур плиты и внешние кольца конструкций (кроме плит
 * перекрытия), переведённые из координат сборки в кадр вида. Нет ни контура, ни стен - `null`.
 */
export const buildSitePlan = (floor: CadBuilding3dFloorRead): ISitePlan | null => {
  const rings: MmPoint[][] = [];
  const outline = cleanOutline(floor.outline);
  if (outline !== null) rings.push(outline.map((point) => toViewFrame(point, floor)));
  for (const wall of floor.walls ?? []) {
    if (wall.kind === 'floor_slab') continue;
    const ring = cleanOutline(wall.shell);
    if (ring !== null) rings.push(ring.map((point) => toViewFrame(point, floor)));
  }
  if (rings.length === 0) return null;

  const seen = new Set<string>();
  const vertices: MmPoint[] = [];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const ring of rings) {
    for (const point of ring) {
      minX = Math.min(minX, point[0]);
      minY = Math.min(minY, point[1]);
      maxX = Math.max(maxX, point[0]);
      maxY = Math.max(maxY, point[1]);
      const key = `${point[0]}:${point[1]}`;
      if (seen.has(key)) continue;
      seen.add(key);
      vertices.push(point);
    }
  }
  return { rings, vertices, bounds: { minX, minY, maxX, maxY } };
};

// --------------------------------------------------------------------------- экран <-> мм

/** Вид панели: `px/мм` и положение начала кадра на экране; ось Y кадра направлена вверх. */
export interface IPlanView {
  readonly scale: number;
  readonly originX: number;
  readonly originY: number;
}

export interface IScreenXY {
  readonly x: number;
  readonly y: number;
}

export const MIN_PLAN_SCALE = 1e-5;
export const MAX_PLAN_SCALE = 5;

export const mmToScreen = (point: MmPoint, view: IPlanView): IScreenXY => ({
  x: view.originX + point[0] * view.scale,
  y: view.originY - point[1] * view.scale,
});

export const screenToMm = (screen: IScreenXY, view: IPlanView): MmPoint => [
  (screen.x - view.originX) / view.scale,
  (view.originY - screen.y) / view.scale,
];

/** Вид, вписывающий габарит плана в холст с отступом; холст нулевого размера - вид по умолчанию. */
export const fitPlanView = (bounds: IPlanBounds, width: number, height: number, paddingPx = 16): IPlanView => {
  const spanX = Math.max(bounds.maxX - bounds.minX, 1);
  const spanY = Math.max(bounds.maxY - bounds.minY, 1);
  const availableX = Math.max(width - 2 * paddingPx, 1);
  const availableY = Math.max(height - 2 * paddingPx, 1);
  const scale = Math.min(MAX_PLAN_SCALE, Math.max(MIN_PLAN_SCALE, Math.min(availableX / spanX, availableY / spanY)));
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;
  return { scale, originX: width / 2 - centerX * scale, originY: height / 2 + centerY * scale };
};

/** Зум к точке экрана: точка плана под курсором остаётся на месте. */
export const zoomPlanView = (view: IPlanView, anchor: IScreenXY, factor: number): IPlanView => {
  const scale = Math.min(MAX_PLAN_SCALE, Math.max(MIN_PLAN_SCALE, view.scale * factor));
  const ratio = scale / view.scale;
  return {
    scale,
    originX: anchor.x - (anchor.x - view.originX) * ratio,
    originY: anchor.y - (anchor.y - view.originY) * ratio,
  };
};

export const panPlanView = (view: IPlanView, dx: number, dy: number): IPlanView => ({
  ...view,
  originX: view.originX + dx,
  originY: view.originY + dy,
});

export interface ISnapped {
  readonly point: MmPoint;
  readonly snapped: boolean;
}

/**
 * Привязка щелчка к ближайшей вершине контура в пределах экранного допуска; дальше допуска остаётся
 * точка щелчка как есть (`snapped = false`).
 */
export const snapToVertex2d = (
  click: IScreenXY,
  vertices: readonly MmPoint[],
  view: IPlanView,
  thresholdPx: number = SITE_PIN_SNAP_PX,
): ISnapped => {
  let best: MmPoint | null = null;
  let bestDistance = thresholdPx;
  for (const vertex of vertices) {
    const screen = mmToScreen(vertex, view);
    const distance = Math.hypot(screen.x - click.x, screen.y - click.y);
    if (distance <= bestDistance) {
      best = vertex;
      bestDistance = distance;
    }
  }
  return best === null ? { point: screenToMm(click, view), snapped: false } : { point: best, snapped: true };
};

// --------------------------------------------------------------------------- точки и подсказка

/**
 * Куда встанет следующий щелчок: в назначенную точку (щелчок по номеру в легенде), иначе в первую
 * пустую; обе стоят и ничего не назначено - никуда (`null`).
 */
export const nextSlot = (points: PinPoints, armed: PinSlot | null): PinSlot | null => {
  if (armed !== null) return armed;
  if (points[0] === null) return 0;
  if (points[1] === null) return 1;
  return null;
};

export const withPoint = (points: PinPoints, slot: PinSlot, point: MmPoint): PinPoints =>
  slot === 0 ? [point, points[1]] : [points[0], point];

export const isComplete = (points: PinPoints): points is readonly [MmPoint, MmPoint] =>
  points[0] !== null && points[1] !== null;

export const distanceMm = (a: MmPoint, b: MmPoint): number => Math.hypot(b[0] - a[0], b[1] - a[1]);

export interface IPinHint {
  readonly sourceMm: number;
  readonly targetMm: number;
  /** Расхождение длин отрезков, доля от длины на корпусе. */
  readonly mismatch: number;
  readonly shortBaseline: boolean;
  readonly mismatchTooBig: boolean;
}

/** Предварительная сверка отрезков 1-2 на корпусе и на площадке; окончательно считает сервер. */
export const pinHint = (source: readonly [MmPoint, MmPoint], target: readonly [MmPoint, MmPoint]): IPinHint => {
  const sourceMm = distanceMm(source[0], source[1]);
  const targetMm = distanceMm(target[0], target[1]);
  const mismatch = sourceMm > 0 ? Math.abs(targetMm - sourceMm) / sourceMm : Infinity;
  return {
    sourceMm,
    targetMm,
    mismatch,
    shortBaseline: sourceMm < SITE_PIN_MIN_BASELINE_MM || targetMm < SITE_PIN_MIN_BASELINE_MM,
    mismatchTooBig: mismatch > SITE_PIN_MAX_MISMATCH,
  };
};

export const formatPercent = (fraction: number): string =>
  Number.isFinite(fraction) ? `${(fraction * 100).toFixed(2).replace('.', ',')} %` : '-';

type SheetAddress = Pick<CadBuilding3dFloorRead, 'revision_id' | 'page_index' | 'view'>;

const sheetOf = (floor: SheetAddress) => ({
  revision_id: floor.revision_id,
  page_index: floor.page_index,
  view: floor.view,
});

const toPoint = (point: MmPoint) => ({ x_mm: point[0], y_mm: point[1] });

/**
 * Тело запроса: лист и две точки корпуса, лист и две точки площадки. Точек не хватает - `null`
 * (отправка недоступна).
 */
export const buildSitePinBody = (
  sourceFloor: SheetAddress,
  targetFloor: SheetAddress,
  sourcePoints: PinPoints,
  targetPoints: PinPoints,
  note: string,
): CadSitePinCreate | null => {
  if (!isComplete(sourcePoints) || !isComplete(targetPoints)) return null;
  const trimmed = note.trim();
  return {
    source: sheetOf(sourceFloor),
    target: sheetOf(targetFloor),
    source_points: [toPoint(sourcePoints[0]), toPoint(sourcePoints[1])],
    target_points: [toPoint(targetPoints[0]), toPoint(targetPoints[1])],
    ...(trimmed === '' ? {} : { note: trimmed }),
  };
};
