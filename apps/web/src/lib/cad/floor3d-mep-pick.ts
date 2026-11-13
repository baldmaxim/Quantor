import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { itemAtTriangle } from './floor3d-geometry';

/**
 * Выбор трасс и элементов ВИС кликом в 3D-виде этажа. Это отдельный вид выбора: он не входит в общий
 * выбор конструкций плана и 3D. Слитые меши трасс хранят диапазоны треугольников по полилиниям
 * (как призмы конструкций), `InstancedMesh` элементов - соответствие `instanceId` -> элемент.
 * Выделение - оверлей поверх тела (заливка акцентом и контур рёбер), тот же стиль, что у конструкций.
 */

export type MepPickKind = 'route' | 'element';

/** Что выбрано: полилиния трассы или элемент сети; индекс - в массиве файла трасс. */
export interface IMepPick {
  readonly kind: MepPickKind;
  readonly index: number;
}

export interface IMepRoutePickData {
  readonly kind: 'route';
  /** Номер первого треугольника каждой полилинии меша. */
  readonly starts: readonly number[];
  /** Индекс полилинии в файле для каждого диапазона. */
  readonly indices: readonly number[];
  readonly total: number;
}

export interface IMepElementPickData {
  readonly kind: 'element';
  /** Индекс элемента в файле для каждого экземпляра. */
  readonly indices: readonly number[];
}

export type MepPickData = IMepRoutePickData | IMepElementPickData;

/** Ключ `userData` меша, который участвует в выборе ВИС. */
export const MEP_PICK_KEY = 'mepPick';

export const sameMepPick = (a: IMepPick | null, b: IMepPick | null): boolean =>
  a !== null && b !== null && a.kind === b.kind && a.index === b.index;

/** Треугольников в геометрии: у индексированной - по индексу, у остальных - по вершинам. */
export const triangleCount = (geometry: THREE.BufferGeometry): number =>
  (geometry.index?.count ?? geometry.getAttribute('position').count) / 3;

/** Выбор ВИС под попаданием луча; `null` - меш не из выбора ВИС или грань вне карты. */
export const mepPickOf = (
  hit: Pick<THREE.Intersection, 'object' | 'faceIndex' | 'instanceId'>,
): IMepPick | null => {
  const data = hit.object.userData[MEP_PICK_KEY] as MepPickData | undefined;
  if (data === undefined) return null;
  if (data.kind === 'element') {
    const index = hit.instanceId === undefined ? undefined : data.indices[hit.instanceId];
    return index === undefined ? null : { kind: 'element', index };
  }
  const face = hit.faceIndex;
  if (face === undefined || face === null) return null;
  const at = itemAtTriangle(data.starts, data.total, face);
  const index = at < 0 ? undefined : data.indices[at];
  return index === undefined ? null : { kind: 'route', index };
};

/** Объект виден с учётом скрытых предков (группа трасс, слой): луч флаг `visible` не проверяет. */
export const isEffectivelyVisible = (object: THREE.Object3D): boolean => {
  for (let node: THREE.Object3D | null = object; node !== null; node = node.parent) {
    if (!node.visible) return false;
  }
  return true;
};

export interface IMepHighlight {
  readonly group: THREE.Group;
  readonly dispose: () => void;
}

/**
 * Оверлей выделения из тел выбранной трассы или элемента: заливка акцентом с прозрачностью и контур
 * рёбер поверх всего. Переданные геометрии сливаются и освобождаются вместе с оверлеем; `null` - тел нет.
 */
export const createMepHighlight = (
  geometries: readonly THREE.BufferGeometry[],
  accent: string,
): IMepHighlight | null => {
  const [first] = geometries;
  if (first === undefined) return null;
  let merged: THREE.BufferGeometry | null = first;
  if (geometries.length > 1) {
    merged = mergeGeometries([...geometries], false);
    for (const geometry of geometries) geometry.dispose();
  }
  if (merged === null) return null;
  const color = new THREE.Color(accent);
  const fill = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.45,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  const edges = new THREE.EdgesGeometry(merged, 30);
  const lineMaterial = new THREE.LineBasicMaterial({ color, depthTest: false });
  const group = new THREE.Group();
  group.add(new THREE.Mesh(merged, fill));
  const lines = new THREE.LineSegments(edges, lineMaterial);
  lines.renderOrder = 10;
  group.add(lines);
  const body = merged;
  return {
    group,
    dispose: () => {
      body.dispose();
      edges.dispose();
      fill.dispose();
      lineMaterial.dispose();
    },
  };
};
