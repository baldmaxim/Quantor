import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

/**
 * Чистые функции геометрии инженерных сетей в 3D (формат `cad_mep_routes3d.v2`): цилиндры труб,
 * короба воздуховодов, стыки. Всё в координатах сцены (метры; `Z DXF = высота`, `Y DXF = -Z сцены`),
 * сцены и материалов здесь нет: их строят `floor3d-routes.ts` и `floor3d-mep-elements.ts`.
 * Единая локальная система любой детали: ось трубы - `+Z`, сечение - `X` (горизонтально поперёк
 * оси) и `Y` (по вертикали); у вертикальной оси `X` - ось X сцены, `Y` - ось Z сцены.
 */

export const MM_IN_M = 1000;

/** Граней у цилиндра трубы (8-12 по ТЗ: труба видна мелко, но не ломаной). */
export const PIPE_RADIAL_SEGMENTS = 10;
/** Сфера стыка: меридианы и параллели. */
export const JOINT_WIDTH_SEGMENTS = 8;
export const JOINT_HEIGHT_SEGMENTS = 6;

/** Косинус, выше которого излом считается прямым продолжением: сфера там не нужна. */
const COLLINEAR_COS = 0.9999;
const MIN_LENGTH_M = 1e-9;
const UP = new THREE.Vector3(0, 1, 0);

export type RouteSection =
  | { readonly shape: 'round'; readonly dnMm: number }
  | { readonly shape: 'rect'; readonly wMm: number; readonly hMm: number };

interface ISectionFields {
  readonly shape?: 'round' | 'rect' | null;
  readonly dn_mm?: number | null;
  readonly w_mm?: number | null;
  readonly h_mm?: number | null;
}

const positive = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

/** Сечение полилинии; `null` - рисовать линией (файл v1, нет формы или размера). */
export const routeSection = (polyline: ISectionFields): RouteSection | null => {
  if (polyline.shape === 'round' && positive(polyline.dn_mm)) {
    return { shape: 'round', dnMm: polyline.dn_mm };
  }
  if (polyline.shape === 'rect' && positive(polyline.w_mm) && positive(polyline.h_mm)) {
    return { shape: 'rect', wMm: polyline.w_mm, hMm: polyline.h_mm };
  }
  return null;
};

/**
 * Ось из файла (целые, умноженные на 1000, система DXF) -> единичный вектор сцены.
 * `null` - нулевая или нечисловая ось.
 */
export const normalizeAxis = (axis: readonly number[]): THREE.Vector3 | null => {
  const [dx, dy, dz] = axis;
  if (dx === undefined || dy === undefined || dz === undefined) return null;
  if (![dx, dy, dz].every(Number.isFinite)) return null;
  const vector = new THREE.Vector3(dx, dz, -dy);
  if (vector.lengthSq() < MIN_LENGTH_M) return null;
  return vector.normalize();
};

/** Поворот локальной системы детали (ось `+Z`, см. шапку) к оси `dir` сцены. */
export const axisBasis = (dir: THREE.Vector3): THREE.Matrix4 => {
  const z = dir.clone().normalize();
  const x = new THREE.Vector3().crossVectors(UP, z);
  if (x.lengthSq() < 1e-8) x.set(1, 0, 0);
  else x.normalize();
  const y = new THREE.Vector3().crossVectors(z, x);
  return new THREE.Matrix4().makeBasis(x, y, z);
};

/** Деталь с локальной осью `+Z` -> в центр `center`, ось вдоль `dir`. */
export const placeAlong = (
  geometry: THREE.BufferGeometry,
  center: THREE.Vector3,
  dir: THREE.Vector3,
): THREE.BufferGeometry => geometry.applyMatrix4(axisBasis(dir).setPosition(center));

/** Цилиндр радиуса `radius` м от `a` до `b`; `null` - участок нулевой длины. */
export const cylinderBetween = (
  a: THREE.Vector3,
  b: THREE.Vector3,
  radius: number,
  segments: number = PIPE_RADIAL_SEGMENTS,
): THREE.BufferGeometry | null => {
  const length = a.distanceTo(b);
  if (length < MIN_LENGTH_M) return null;
  // Цилиндр three вытянут по Y; поворот на 90 вокруг X кладёт его ось на Z.
  const geometry = new THREE.CylinderGeometry(radius, radius, length, segments).rotateX(
    Math.PI / 2,
  );
  return placeAlong(geometry, a.clone().lerp(b, 0.5), b.clone().sub(a));
};

/** Короб `width` (поперёк, горизонтально) x `height` (по вертикали) м от `a` до `b`. */
export const boxBetween = (
  a: THREE.Vector3,
  b: THREE.Vector3,
  width: number,
  height: number,
): THREE.BufferGeometry | null => {
  const length = a.distanceTo(b);
  if (length < MIN_LENGTH_M) return null;
  const geometry = new THREE.BoxGeometry(width, height, length);
  return placeAlong(geometry, a.clone().lerp(b, 0.5), b.clone().sub(a));
};

/** Сфера стыка двух участков трубы. */
export const jointSphere = (center: THREE.Vector3, radius: number): THREE.BufferGeometry =>
  new THREE.SphereGeometry(radius, JOINT_WIDTH_SEGMENTS, JOINT_HEIGHT_SEGMENTS).translate(
    center.x,
    center.y,
    center.z,
  );

/** Излом в вершине `i` заметен: участки не продолжают друг друга. */
const isBend = (points: readonly THREE.Vector3[], i: number): boolean => {
  const prev = points[i - 1];
  const at = points[i];
  const next = points[i + 1];
  if (prev === undefined || at === undefined || next === undefined) return false;
  const before = at.clone().sub(prev);
  const after = next.clone().sub(at);
  if (before.lengthSq() < MIN_LENGTH_M || after.lengthSq() < MIN_LENGTH_M) return false;
  return before.normalize().dot(after.normalize()) < COLLINEAR_COS;
};

export interface IPolylineSolidOptions {
  /** Утолщение со всех сторон, м (изоляция). */
  readonly inflateM?: number;
  /** Вершина закрыта фасониной: сферы там нет. */
  readonly hasFittingAt?: (index: number) => boolean;
}

/**
 * Детали полилинии с сечением: цилиндр или короб на каждый участок; у трубы - сфера того же
 * радиуса в изломах без фасонины (внутренние вершины; концы остаются открытыми).
 */
export const polylineSolids = (
  points: readonly THREE.Vector3[],
  section: RouteSection,
  { inflateM = 0, hasFittingAt }: IPolylineSolidOptions = {},
): THREE.BufferGeometry[] => {
  const result: THREE.BufferGeometry[] = [];
  const radius = section.shape === 'round' ? section.dnMm / 2 / MM_IN_M + inflateM : 0;
  const width = section.shape === 'rect' ? section.wMm / MM_IN_M + 2 * inflateM : 0;
  const height = section.shape === 'rect' ? section.hMm / MM_IN_M + 2 * inflateM : 0;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (a === undefined || b === undefined) continue;
    const part =
      section.shape === 'round' ? cylinderBetween(a, b, radius) : boxBetween(a, b, width, height);
    if (part !== null) result.push(part);
  }
  if (section.shape === 'round') {
    for (let i = 1; i < points.length - 1; i += 1) {
      const at = points[i];
      if (at === undefined || !isBend(points, i) || hasFittingAt?.(i) === true) continue;
      result.push(jointSphere(at, radius));
    }
  }
  return result;
};

/** Слить детали в одну геометрию (один вызов отрисовки); исходные освобождаются. */
export const mergeSolids = (
  parts: readonly THREE.BufferGeometry[],
): THREE.BufferGeometry | null => {
  const [first] = parts;
  if (first === undefined) return null;
  if (parts.length === 1) return first;
  const merged = mergeGeometries([...parts], false);
  for (const part of parts) part.dispose();
  return merged;
};
