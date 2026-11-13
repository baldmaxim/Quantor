import type { CadBuilding3dFloorRead, CadBuilding3dWallRead } from '@quantor/api-client';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import {
  MM_IN_M,
  buildBuildingPlan,
  cleanOutline,
  type IBuildingFloorSpec,
  type Point2,
} from './building3d-geometry';

/**
 * Просмотрщик объекта (страница «3D: общий вид объекта»): чистая геометрия без DOM и без рендерера.
 *
 * Конвенция та же, что в колонке «Здание» и в 3D этажа: контур `(u, v) = (x, y)` DXF в метрах от общего
 * центра здания, в сцене three `X = u`, `Y` = высота, `Z = -v` (поворот призмы на -90° вокруг X).
 * Стены этажа - экструзия `shell` от верха плиты на высоту `floor_height - slab_thickness`
 * (не ниже 100 мм); все стены одного материала сливаются в одну геометрию.
 */

export type ViewerWallMaterial = 'monolith' | 'masonry';

export interface IViewerWall {
  /** Идентификатор конструкции из walls.json: по нему клик в 3D находит карточку конструкции. */
  readonly id: string;
  readonly material: ViewerWallMaterial;
  /** Контур в плане, м, от общего центра. */
  readonly shell: readonly Point2[];
}

export interface IViewerFloorSpec extends IBuildingFloorSpec {
  readonly walls: readonly IViewerWall[];
  /** Верх стен, м, от общего центра по высоте (низ стен = верх плиты). */
  readonly wallTop: number;
}

/** Подпись группы (корпус, секция) над зданием в режиме «Весь объект»; координаты сцены, м. */
export interface IViewerGroupLabel {
  readonly key: string;
  readonly text: string;
  readonly x: number;
  readonly y: number;
  readonly z: number;
  /** Верхний этаж группы: при разнесении подпись поднимается вместе с ним. */
  readonly floorKey: string;
}

export interface IViewerPlan {
  readonly floors: readonly IViewerFloorSpec[];
  readonly size: { readonly width: number; readonly depth: number; readonly height: number };
  /** Отметка (мм), от которой отсчитаны высоты плана: нужна, чтобы свести группы к общим отметкам. */
  readonly zCenterMm: number;
  /** Подписи групп; у плана одного здания пусто. */
  readonly labels: readonly IViewerGroupLabel[];
}

/** Диапазон треугольников слитой геометрии, принадлежащий одной конструкции: `[start, end)`. */
export interface IWallRange {
  readonly id: string;
  readonly start: number;
  readonly end: number;
}

export interface IMergedWalls {
  readonly geometry: THREE.BufferGeometry;
  /** Диапазоны по порядку слияния: по ним `faceIndex` луча переводится в конструкцию. */
  readonly ranges: readonly IWallRange[];
}

export interface IViewerBounds {
  /** Центр описанной сферы в координатах сцены, м. */
  readonly center: readonly [number, number, number];
  readonly radius: number;
}

export interface IWallCounts {
  readonly monolith: number;
  readonly masonry: number;
  readonly partition: number;
}

/** Нижняя граница высоты стены, мм: толщина плиты не должна «съедать» этаж. */
export const MIN_WALL_HEIGHT_MM = 100;
/** Зазор между этажами при «разнесении» - в высотах этажа. */
export const EXPLODE_GAP_FACTOR = 1.5;
/** Площадь контура меньше этого (м2) - вырожденный контур, не строится. */
const MIN_AREA_M2 = 1e-6;
const FALLBACK_FLOOR_HEIGHT_M = 3;

/** Высота стен этажа, мм. */
export const wallHeightMm = (floor: Pick<CadBuilding3dFloorRead, 'floor_height_mm' | 'slab_thickness_mm'>): number => {
  const height = floor.floor_height_mm - (Number.isFinite(floor.slab_thickness_mm) ? floor.slab_thickness_mm : 0);
  return Number.isFinite(height) ? Math.max(MIN_WALL_HEIGHT_MM, height) : MIN_WALL_HEIGHT_MM;
};

/**
 * Материал стены для окраски: монолит - отдельно, кладка и перегородки - вместе. Плита перекрытия как
 * стена не строится (плита этажа рисуется по контуру), для неё `null`.
 */
export const wallMaterialOf = (kind: CadBuilding3dWallRead['kind']): ViewerWallMaterial | null => {
  if (kind === 'floor_slab') return null;
  return kind === 'monolith_wall' || kind === 'monolith_pylon' || kind === 'monolith_column' ? 'monolith' : 'masonry';
};

/** Число конструкций этажа по видам; `null` - контуров конструкций в ответе нет. */
export const countWalls = (walls: readonly CadBuilding3dWallRead[] | null | undefined): IWallCounts | null => {
  if (!walls) return null;
  let monolith = 0;
  let masonry = 0;
  let partition = 0;
  for (const wall of walls) {
    if (wall.kind === 'frame_partition') partition += 1;
    else if (wallMaterialOf(wall.kind) === 'monolith') monolith += 1;
    else if (wall.kind === 'masonry') masonry += 1;
  }
  return { monolith, masonry, partition };
};

const polygonAreaM2 = (shell: readonly Point2[]): number => {
  let sum = 0;
  for (let i = 0; i < shell.length; i += 1) {
    const a = shell[i] as Point2;
    const b = shell[(i + 1) % shell.length] as Point2;
    sum += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(sum) / 2;
};

/** План просмотрщика: призмы этажей колонки «Здание» плюс контуры стен каждого этажа. Нет этажей с отметкой - `null`. */
export const buildViewerPlan = (floors: readonly CadBuilding3dFloorRead[]): IViewerPlan | null => {
  const base = buildBuildingPlan(floors);
  if (base === null) return null;
  const specs: IViewerFloorSpec[] = base.floors.map((spec) => {
    const walls: IViewerWall[] = [];
    for (const wall of spec.floor.walls ?? []) {
      const material = wallMaterialOf(wall.kind);
      const outline = cleanOutline(wall.shell);
      if (material === null || outline === null) continue;
      const shell = outline.map(([x, y]): Point2 => [
        (x - base.center.x) / MM_IN_M,
        (y - base.center.y) / MM_IN_M,
      ]);
      if (polygonAreaM2(shell) < MIN_AREA_M2) continue;
      walls.push({ id: wall.id, material, shell });
    }
    return { ...spec, walls, wallTop: spec.slabTop + wallHeightMm(spec.floor) / MM_IN_M };
  });
  return { floors: specs, size: base.size, zCenterMm: base.center.z, labels: [] };
};

/** Номер уровня каждого этажа снизу вверх: этажи на одной отметке (мм) делят уровень. */
const levelRanks = (plan: IViewerPlan): { ranks: ReadonlyMap<string, number>; levels: number } => {
  const marks = [...new Set(plan.floors.map((spec) => Math.round(spec.floor.base_z_mm)))].sort((a, b) => a - b);
  const index = new Map(marks.map((mark, position) => [mark, position]));
  const ranks = new Map<string, number>();
  for (const spec of plan.floors) ranks.set(spec.key, index.get(Math.round(spec.floor.base_z_mm)) ?? 0);
  return { ranks, levels: marks.length };
};

/** Типовая (медианная) высота этажа плана, м. */
const typicalFloorHeightM = (plan: IViewerPlan): number => {
  const heights = plan.floors
    .map((spec) => spec.floor.floor_height_mm / MM_IN_M)
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  return heights[Math.floor(heights.length / 2)] ?? FALLBACK_FLOOR_HEIGHT_M;
};

/**
 * Сдвиг каждого этажа по вертикали при «разнесении», м: уровень снизу вверх × зазор
 * (`EXPLODE_GAP_FACTOR` типовых высот этажа). Нижний уровень остаётся на месте.
 */
export const explodeOffsets = (plan: IViewerPlan): ReadonlyMap<string, number> => {
  const gap = EXPLODE_GAP_FACTOR * typicalFloorHeightM(plan);
  const { ranks } = levelRanks(plan);
  return new Map([...ranks].map(([key, rank]) => [key, rank * gap]));
};

/** Описанная сфера здания в координатах сцены; с `exploded` - с учётом раздвинутых этажей. */
export const viewerBounds = (plan: IViewerPlan, exploded: boolean): IViewerBounds => {
  const offsets = exploded ? explodeOffsets(plan) : null;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const spec of plan.floors) {
    const shift = offsets?.get(spec.key) ?? 0;
    minY = Math.min(minY, spec.slabBottom + shift);
    maxY = Math.max(maxY, spec.volumeTop + shift);
  }
  const height = Math.max(0, maxY - minY);
  const { width, depth } = plan.size;
  return {
    center: [0, (minY + maxY) / 2, 0],
    radius: Math.max(0.5, Math.sqrt(width * width + depth * depth + height * height) / 2),
  };
};

/**
 * Расстояние от камеры до центра, при котором сфера радиуса `radius` целиком в кадре
 * (по меньшему из вертикального и горизонтального углов обзора), с запасом `margin`.
 */
export const fitDistance = (radius: number, fovDeg: number, aspect: number, margin = 1.08): number => {
  const vertical = THREE.MathUtils.degToRad(fovDeg) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * Math.max(0.1, aspect));
  return (Math.max(radius, 0.1) / Math.sin(Math.min(vertical, horizontal))) * margin;
};

/** Контур без подряд идущих одинаковых вершин; меньше трёх вершин - `null`. */
const dedupe = (shell: readonly Point2[]): Point2[] | null => {
  const points: Point2[] = [];
  for (const point of shell) {
    const last = points[points.length - 1];
    if (last === undefined || last[0] !== point[0] || last[1] !== point[1]) points.push(point);
  }
  return points.length >= 3 ? points : null;
};

/** Призма из контура от `yBottom` до `yTop`, м; нельзя построить (вырожденный или самопересекающийся контур) - `null`. */
export const extrudeShell = (shell: readonly Point2[], yBottom: number, yTop: number): THREE.BufferGeometry | null => {
  const depth = yTop - yBottom;
  const points = dedupe(shell);
  if (!(depth > 0) || points === null) return null;
  try {
    const geometry = new THREE.ExtrudeGeometry(new THREE.Shape(points.map(([u, v]) => new THREE.Vector2(u, v))), {
      depth,
      bevelEnabled: false,
      steps: 1,
    });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, yBottom, 0);
    if (geometry.getAttribute('position').count > 0) return geometry;
    geometry.dispose();
    return null;
  } catch {
    // Триангуляция самопересечения не берёт: контур пропускается, остальные строятся.
    return null;
  }
};

const triangleCount = (geometry: THREE.BufferGeometry): number =>
  (geometry.index?.count ?? geometry.getAttribute('position').count) / 3;

/**
 * Конструкции одним мешем: слияние в одну геометрию с диапазонами треугольников каждой. Контур, который
 * не строится, пропускается. Нечего сливать - `null`.
 */
export const mergeWalls = (
  walls: readonly { readonly id: string; readonly shell: readonly Point2[] }[],
  yBottom: number,
  yTop: number,
): IMergedWalls | null => {
  const parts: THREE.BufferGeometry[] = [];
  const ranges: IWallRange[] = [];
  let triangles = 0;
  for (const wall of walls) {
    const part = extrudeShell(wall.shell, yBottom, yTop);
    if (part === null) continue;
    const count = triangleCount(part);
    ranges.push({ id: wall.id, start: triangles, end: triangles + count });
    triangles += count;
    parts.push(part);
  }
  if (parts.length === 0) return null;
  const merged = parts.length === 1 ? (parts[0] ?? null) : mergeGeometries(parts, false);
  if (parts.length > 1) for (const part of parts) part.dispose();
  return merged === null ? null : { geometry: merged, ranges };
};

/** Все контуры одним мешем: слияние в одну геометрию. Нечего сливать - `null`. */
export const mergeShells = (
  shells: readonly (readonly Point2[])[],
  yBottom: number,
  yTop: number,
): THREE.BufferGeometry | null =>
  mergeWalls(
    shells.map((shell) => ({ id: '', shell })),
    yBottom,
    yTop,
  )?.geometry ?? null;

/** Конструкция, которой принадлежит треугольник слитой геометрии; номера нет в диапазонах - `null`. */
export const wallIdAtFace = (ranges: readonly IWallRange[], faceIndex: number | null | undefined): string | null => {
  if (faceIndex === undefined || faceIndex === null || !Number.isInteger(faceIndex) || faceIndex < 0) return null;
  let low = 0;
  let high = ranges.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const range = ranges[mid] as IWallRange;
    if (faceIndex < range.start) high = mid - 1;
    else if (faceIndex >= range.end) low = mid + 1;
    else return range.id;
  }
  return null;
};
