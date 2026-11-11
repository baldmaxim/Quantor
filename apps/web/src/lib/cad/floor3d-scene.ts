import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { IFloor3dPlan, IHoleSpec, IPrismSpec, Point2, PrismCategory } from './floor3d-geometry';
import { itemAtTriangle } from './floor3d-geometry';

/**
 * Сцена 3D-вида этажа (ADR-0039): three.js-объекты по плану из `floor3d-geometry`. Модуль грузится
 * только вместе с видом «3D»: `three` не попадает в общий чанк маршрута.
 *
 * Меши и клик. Призмы одной категории сливаются в один меш (плита, кладка, монолит, перемычки -
 * четыре вызова отрисовки вместо сотен). Соответствие «треугольник -> элемент» хранится в
 * `userData.pick`: у каждой призмы свой диапазон треугольников, клик находит элемент бинарным
 * поиском по номеру грани. Отдельных мешей на конструкцию нет - размер модели на скорость не влияет.
 */

/** Цвета категорий: значения CSS-токенов темы, не хардкод. */
export interface IFloor3dColors {
  readonly slab: string;
  readonly masonry: string;
  readonly monolith: string;
  readonly lintel: string;
  readonly candidate: string;
  readonly enabled: string;
  readonly edge: string;
  /** Контур отверстия в состоянии «Не отверстие». */
  readonly muted: string;
}

const FALLBACK_COLOR = 'gray';

export const readFloor3dColors = (): IFloor3dColors => {
  if (typeof document === 'undefined') {
    return {
      slab: FALLBACK_COLOR,
      masonry: FALLBACK_COLOR,
      monolith: FALLBACK_COLOR,
      lintel: FALLBACK_COLOR,
      candidate: FALLBACK_COLOR,
      enabled: FALLBACK_COLOR,
      edge: FALLBACK_COLOR,
      muted: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    slab: token('--border-strong'),
    masonry: token('--cad-construction-masonry'),
    monolith: token('--cad-construction-monolith'),
    lintel: token('--cad-construction-check'),
    candidate: token('--danger'),
    enabled: token('--success'),
    edge: token('--text'),
    muted: token('--muted'),
  };
};

/** Что лежит под мешем: элементы в порядке слияния и диапазоны их треугольников. */
export interface IFloor3dPickData {
  readonly kind: 'prism' | 'hole';
  readonly category: PrismCategory | 'hole';
  readonly ids: readonly string[];
  /** Номер первого треугольника каждого элемента. */
  readonly starts: readonly number[];
  readonly total: number;
}

export interface IFloor3dScene {
  readonly group: THREE.Group;
  /** Меши, по которым работает клик. */
  readonly pickables: readonly THREE.Mesh[];
  readonly slabCap: THREE.Object3D | null;
  dispose: () => void;
}

export interface IFloor3dPick {
  readonly kind: 'prism' | 'hole';
  readonly category: PrismCategory | 'hole';
  readonly id: string;
}

const toVector = (points: readonly Point2[]): THREE.Vector2[] =>
  points.map(([u, v]) => new THREE.Vector2(u, v));

/** Контур в плане (u, v) лежит в плоскости XY; поворот на -90° вокруг X даёт (u, высота, -v). */
const shapeOf = (shell: readonly Point2[], holes: readonly (readonly Point2[])[]): THREE.Shape => {
  const shape = new THREE.Shape(toVector(shell));
  shape.holes = holes.map((hole) => new THREE.Path(toVector(hole)));
  return shape;
};

const prismGeometry = (spec: IPrismSpec): THREE.BufferGeometry | null => {
  const depth = spec.yTop - spec.yBottom;
  if (!(depth > 0)) return null;
  try {
    const geometry = new THREE.ExtrudeGeometry(shapeOf(spec.shell, spec.holes), {
      depth,
      bevelEnabled: false,
      steps: 1,
    });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, spec.yBottom, 0);
    return geometry.getAttribute('position').count > 0 ? geometry : null;
  } catch {
    // Самопересекающийся контур триангуляция не берёт: элемент пропускается, вид строится дальше.
    return null;
  }
};

const holeGeometry = (spec: IHoleSpec, lift: number): THREE.BufferGeometry | null => {
  try {
    const geometry = new THREE.ShapeGeometry(shapeOf(spec.contour, []));
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, spec.y + lift, 0);
    return geometry.getAttribute('position').count > 0 ? geometry : null;
  } catch {
    return null;
  }
};

/** Треугольников в геометрии: у индексированной (ShapeGeometry) - по индексу, у остальных - по вершинам. */
const triangleCount = (geometry: THREE.BufferGeometry): number =>
  (geometry.index?.count ?? geometry.getAttribute('position').count) / 3;

interface IMerged {
  readonly geometry: THREE.BufferGeometry;
  readonly pick: IFloor3dPickData;
}

/** Слияние с картой «треугольник -> элемент»; элементы без геометрии пропускаются. */
const mergeItems = (
  items: readonly { id: string; geometry: THREE.BufferGeometry | null }[],
  kind: IFloor3dPickData['kind'],
  category: IFloor3dPickData['category'],
): IMerged | null => {
  const built = items.filter(
    (item): item is { id: string; geometry: THREE.BufferGeometry } => item.geometry !== null,
  );
  if (built.length === 0) return null;
  const starts: number[] = [];
  let total = 0;
  for (const item of built) {
    starts.push(total);
    total += triangleCount(item.geometry);
  }
  const geometry = mergeGeometries(built.map((item) => item.geometry), false);
  for (const item of built) item.geometry.dispose();
  if (geometry === null) return null;
  return { geometry, pick: { kind, category, ids: built.map((item) => item.id), starts, total } };
};

export const buildFloor3dScene = (
  plan: IFloor3dPlan,
  colors: IFloor3dColors,
  options: { readonly showSlabCap: boolean },
): IFloor3dScene => {
  const group = new THREE.Group();
  const pickables: THREE.Mesh[] = [];
  const disposables: { dispose: () => void }[] = [];

  const track = <T extends { dispose: () => void }>(item: T): T => {
    disposables.push(item);
    return item;
  };

  const solid = (color: string) =>
    track(new THREE.MeshLambertMaterial({ color: new THREE.Color(color) }));
  const edgeMaterial = track(
    new THREE.LineBasicMaterial({ color: new THREE.Color(colors.edge), transparent: true, opacity: 0.35 }),
  );

  const categories: readonly { category: PrismCategory; color: string }[] = [
    { category: 'slab', color: colors.slab },
    { category: 'masonry', color: colors.masonry },
    { category: 'monolith', color: colors.monolith },
    { category: 'lintel', color: colors.lintel },
  ];
  for (const { category, color } of categories) {
    const merged = mergeItems(
      plan.prisms
        .filter((item) => item.category === category)
        .map((item) => ({ id: item.id, geometry: prismGeometry(item) })),
      'prism',
      category,
    );
    if (merged === null) continue;
    track(merged.geometry);
    const mesh = new THREE.Mesh(merged.geometry, solid(color));
    mesh.userData.pick = merged.pick;
    group.add(mesh);
    pickables.push(mesh);
    const edges = new THREE.EdgesGeometry(merged.geometry, 30);
    track(edges);
    group.add(new THREE.LineSegments(edges, edgeMaterial));
  }

  // Отверстия плиты: кандидат - полупрозрачная заливка и контур, включённое - контур, «Не отверстие» -
  // тонкий нейтральный контур на сплошной плите. Для клика по включённому и выключенному отверстию
  // кладётся невидимый плоский меш (material.visible = false): не рисуется, но луч его находит, а
  // контур тонкой линии луч ловил бы ненадёжно (порог Line зависит от масштаба). Меш лежит на 3 мм
  // выше плиты, поэтому ближе к камере и перехватывает клик у плиты.
  const lift = 0.003;
  const candidates = plan.holes.filter((hole) => hole.state === 'candidate');
  const decided = [...plan.holes.filter((hole) => hole.state === 'enabled'), ...plan.disabledHoles];
  const fill = mergeItems(
    candidates.map((hole) => ({ id: hole.key, geometry: holeGeometry(hole, lift) })),
    'hole',
    'hole',
  );
  if (fill !== null) {
    track(fill.geometry);
    const material = track(
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(colors.candidate),
        transparent: true,
        opacity: 0.45,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    const mesh = new THREE.Mesh(fill.geometry, material);
    mesh.userData.pick = fill.pick;
    group.add(mesh);
    pickables.push(mesh);
  }
  const hidden = mergeItems(
    decided.map((hole) => ({ id: hole.key, geometry: holeGeometry(hole, lift) })),
    'hole',
    'hole',
  );
  if (hidden !== null) {
    track(hidden.geometry);
    const material = track(new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
    material.visible = false;
    const mesh = new THREE.Mesh(hidden.geometry, material);
    mesh.userData.pick = hidden.pick;
    group.add(mesh);
    pickables.push(mesh);
  }
  const outline = (hole: IHoleSpec, color: string): void => {
    const points = hole.contour.map(([u, v]) => new THREE.Vector3(u, hole.y + lift, -v));
    const geometry = track(new THREE.BufferGeometry().setFromPoints(points));
    group.add(new THREE.LineLoop(geometry, track(new THREE.LineBasicMaterial({ color: new THREE.Color(color) }))));
  };
  for (const hole of plan.holes) outline(hole, hole.state === 'candidate' ? colors.candidate : colors.enabled);
  for (const hole of plan.disabledHoles) outline(hole, colors.muted);

  // «Плита сверху»: полупрозрачная копия плиты на верхе стен, в клик не входит.
  let slabCap: THREE.Object3D | null = null;
  if (options.showSlabCap && plan.slabCap !== null) {
    const geometry = prismGeometry(plan.slabCap);
    if (geometry !== null) {
      track(geometry);
      const material = track(
        new THREE.MeshLambertMaterial({
          color: new THREE.Color(colors.slab),
          transparent: true,
          opacity: 0.35,
          depthWrite: false,
        }),
      );
      slabCap = new THREE.Mesh(geometry, material);
      group.add(slabCap);
    }
  }

  return {
    group,
    pickables,
    slabCap,
    dispose: () => {
      for (const item of disposables) item.dispose();
      group.clear();
    },
  };
};

/** Элемент под гранью, в которую попал луч; `null` - меш не наш или грань вне карты. */
export const pickOf = (mesh: THREE.Object3D, faceIndex: number | undefined | null): IFloor3dPick | null => {
  const data = mesh.userData.pick as IFloor3dPickData | undefined;
  if (data === undefined || faceIndex === undefined || faceIndex === null) return null;
  const index = itemAtTriangle(data.starts, data.total, faceIndex);
  const id = index < 0 ? undefined : data.ids[index];
  return id === undefined ? null : { kind: data.kind, category: data.category, id };
};
