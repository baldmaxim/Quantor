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
 * (не ниже 100 мм); все стены одного материала сливаются в одну геометрию. Стена с верхом по знаку
 * отметки (парапет кровли, `top_mm`) поднимается до него.
 *
 * Этаж с участками уровней (`levels`: кровля со скатами и нишами, ступенчатый первый этаж) - плита из
 * участков, каждый своей толщины плиты под своим верхом, с отверстиями.
 */

export type ViewerWallMaterial = 'monolith' | 'masonry';

export interface IViewerWall {
  /** Идентификатор конструкции из walls.json: по нему клик в 3D находит карточку конструкции. */
  readonly id: string;
  readonly material: ViewerWallMaterial;
  /** Контур в плане, м, от общего центра. */
  readonly shell: readonly Point2[];
  /** Верх по знаку отметки (парапет), м, от общего центра по высоте; нет - верх стен этажа. */
  readonly top?: number;
}

/** Участок плиты на своей отметке; контуры, м, от общего центра; верх плиты, м, по высоте. */
export interface IViewerLevel {
  readonly shell: readonly Point2[];
  readonly holes: readonly (readonly Point2[])[];
  readonly top: number;
}

export interface IViewerFloorSpec extends IBuildingFloorSpec {
  readonly walls: readonly IViewerWall[];
  /** Участки уровней плиты; пусто - одна плита по `shell`. */
  readonly levels: readonly IViewerLevel[];
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
  const toPlan = ([x, y]: readonly [number, number]): Point2 => [
    (x - base.center.x) / MM_IN_M,
    (y - base.center.y) / MM_IN_M,
  ];
  const height = (mm: number): number => (mm - base.center.z) / MM_IN_M;
  const specs: IViewerFloorSpec[] = base.floors.map((spec) => {
    const walls: IViewerWall[] = [];
    for (const wall of spec.floor.walls ?? []) {
      const material = wallMaterialOf(wall.kind);
      const outline = cleanOutline(wall.shell);
      if (material === null || outline === null) continue;
      const shell = outline.map(toPlan);
      if (polygonAreaM2(shell) < MIN_AREA_M2) continue;
      const top = wall.top_mm;
      walls.push(
        top === null || top === undefined ? { id: wall.id, material, shell } : { id: wall.id, material, shell, top: height(top) },
      );
    }
    const levels: IViewerLevel[] = [];
    for (const zone of spec.floor.levels ?? []) {
      const outline = cleanOutline(zone.shell);
      if (outline === null) continue;
      const holes = zone.holes
        .map((ring) => cleanOutline(ring))
        .filter((ring): ring is NonNullable<typeof ring> => ring !== null)
        .map((ring) => ring.map(toPlan));
      levels.push({ shell: outline.map(toPlan), holes, top: height(zone.top_mm) });
    }
    return { ...spec, walls, levels, wallTop: spec.slabTop + wallHeightMm(spec.floor) / MM_IN_M };
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

/** Контур призмы: вершины против часовой стрелки в плане и треугольники крышки (тройки индексов). */
interface IPrism {
  readonly points: readonly Point2[];
  readonly caps: readonly number[];
}

/** Удвоенная ориентированная площадь треугольника плана: > 0 - против часовой стрелки. */
const cross2 = (a: Point2, b: Point2, c: Point2): number => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

/** Подготовка призмы: обход против часовой стрелки и триангуляция крышки; нечего строить - `null`. */
const preparePrism = (shell: readonly Point2[]): IPrism | null => {
  const deduped = dedupe(shell);
  if (deduped === null) return null;
  let area = 0;
  for (let i = 0; i < deduped.length; i += 1) {
    const a = deduped[i] as Point2;
    const b = deduped[(i + 1) % deduped.length] as Point2;
    area += a[0] * b[1] - b[0] * a[1];
  }
  if (area === 0 || !Number.isFinite(area)) return null;
  const points = area > 0 ? deduped : [...deduped].reverse();
  let faces: number[][];
  try {
    faces = THREE.ShapeUtils.triangulateShape(
      points.map(([u, v]) => new THREE.Vector2(u, v)),
      [],
    );
  } catch {
    // Триангуляция самопересечения не берёт: контур пропускается, остальные строятся.
    return null;
  }
  const caps: number[] = [];
  for (const face of faces) {
    const [i, j, k] = face;
    if (i === undefined || j === undefined || k === undefined) continue;
    const a = points[i];
    const b = points[j];
    const c = points[k];
    if (a === undefined || b === undefined || c === undefined) continue;
    // Крышка против часовой стрелки в плане: в сцене её нормаль смотрит вверх.
    if (cross2(a, b, c) >= 0) caps.push(i, j, k);
    else caps.push(i, k, j);
  }
  return caps.length === 0 ? null : { points, caps };
};

/** Треугольников в призме: две крышки и по два на каждую боковую грань. */
const prismTriangles = (prism: IPrism): number => (prism.caps.length / 3) * 2 + prism.points.length * 2;

/**
 * Запись призмы в общие буферы с позиции `offset` (в вершинах). Сцена: `X = u`, `Y` - высота, `Z = -v`.
 * Нормали плоские, по граням - как у `ExtrudeGeometry` без фасок; UV не нужны (материалы без текстур).
 */
const writePrism = (
  prism: IPrism,
  yBottom: number,
  yTop: number,
  positions: Float32Array,
  normals: Float32Array,
  offset: number,
): number => {
  let at = offset * 3;
  const put = (u: number, y: number, v: number, nx: number, ny: number, nz: number): void => {
    positions[at] = u;
    positions[at + 1] = y;
    positions[at + 2] = -v;
    normals[at] = nx;
    normals[at + 1] = ny;
    normals[at + 2] = nz;
    at += 3;
  };
  const { points, caps } = prism;
  for (let t = 0; t < caps.length; t += 3) {
    const a = points[caps[t] as number] as Point2;
    const b = points[caps[t + 1] as number] as Point2;
    const c = points[caps[t + 2] as number] as Point2;
    // Верх: обход против часовой стрелки в плане - нормаль +Y; низ - обратный обход, нормаль -Y.
    put(a[0], yTop, a[1], 0, 1, 0);
    put(b[0], yTop, b[1], 0, 1, 0);
    put(c[0], yTop, c[1], 0, 1, 0);
    put(a[0], yBottom, a[1], 0, -1, 0);
    put(c[0], yBottom, c[1], 0, -1, 0);
    put(b[0], yBottom, b[1], 0, -1, 0);
  }
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i] as Point2;
    const b = points[(i + 1) % points.length] as Point2;
    const du = b[0] - a[0];
    const dv = b[1] - a[1];
    const length = Math.hypot(du, dv);
    // Наружная нормаль ребра обхода против часовой стрелки: (dv, -du) в плане, в сцене (dv, 0, du).
    const nx = length > 0 ? dv / length : 0;
    const nz = length > 0 ? du / length : 0;
    put(a[0], yBottom, a[1], nx, 0, nz);
    put(b[0], yBottom, b[1], nx, 0, nz);
    put(b[0], yTop, b[1], nx, 0, nz);
    put(a[0], yBottom, a[1], nx, 0, nz);
    put(b[0], yTop, b[1], nx, 0, nz);
    put(a[0], yTop, a[1], nx, 0, nz);
  }
  return at / 3;
};

const geometryOf = (positions: Float32Array, normals: Float32Array): THREE.BufferGeometry => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  return geometry;
};

/** Призма из контура от `yBottom` до `yTop`, м; нельзя построить (вырожденный или самопересекающийся контур) - `null`. */
export const extrudeShell = (shell: readonly Point2[], yBottom: number, yTop: number): THREE.BufferGeometry | null =>
  mergeWalls([{ id: '', shell }], yBottom, yTop)?.geometry ?? null;

/**
 * Конструкции одним мешем: все призмы пишутся сразу в один буфер (без промежуточных геометрий и
 * слияния), с диапазонами треугольников каждой. Контур, который не строится, пропускается. Нечего
 * строить - `null`.
 */
export const mergeWalls = (
  walls: readonly { readonly id: string; readonly shell: readonly Point2[]; readonly top?: number }[],
  yBottom: number,
  yTop: number,
): IMergedWalls | null => {
  const prisms: { id: string; prism: IPrism; top: number }[] = [];
  const ranges: IWallRange[] = [];
  let triangles = 0;
  for (const wall of walls) {
    // Верх по знаку отметки (парапет) - свой; ниже низа стены - стена не строится.
    const top = wall.top ?? yTop;
    if (!(top - yBottom > 0)) continue;
    const prism = preparePrism(wall.shell);
    if (prism === null) continue;
    const count = prismTriangles(prism);
    ranges.push({ id: wall.id, start: triangles, end: triangles + count });
    triangles += count;
    prisms.push({ id: wall.id, prism, top });
  }
  if (prisms.length === 0) return null;
  const positions = new Float32Array(triangles * 9);
  const normals = new Float32Array(triangles * 9);
  let offset = 0;
  for (const { prism, top } of prisms) offset = writePrism(prism, yBottom, top, positions, normals, offset);
  return { geometry: geometryOf(positions, normals), ranges };
};

/**
 * Плита из участков уровней: каждый участок с отверстиями - призма толщиной `thickness` под своим верхом.
 * Сцена та же: `X = u`, `Y` - высота, `Z = -v` (форма в плоскости XY выдавливается по Z и
 * поворачивается на -90° вокруг X). Нечего строить - `null`.
 */
export const extrudeLevels = (levels: readonly IViewerLevel[], thickness: number): THREE.BufferGeometry | null => {
  if (!(thickness > 0)) return null;
  const parts: THREE.BufferGeometry[] = [];
  for (const level of levels) {
    const shape = new THREE.Shape(level.shell.map(([u, v]) => new THREE.Vector2(u, v)));
    for (const hole of level.holes) shape.holes.push(new THREE.Path(hole.map(([u, v]) => new THREE.Vector2(u, v))));
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, level.top - thickness, 0);
    // Атрибуты как у слитых призм (позиция и нормали): без UV слияние не спотыкается о разный состав.
    geometry.deleteAttribute('uv');
    parts.push(geometry.index === null ? geometry : geometry.toNonIndexed());
  }
  if (parts.length === 0) return null;
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  return merged;
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
