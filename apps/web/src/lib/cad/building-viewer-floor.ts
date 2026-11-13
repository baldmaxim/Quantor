import * as THREE from 'three';

import {
  extrudeShell,
  mergeWalls,
  type IViewerFloorSpec,
  type IWallRange,
} from './building-viewer-geometry';

/** Меши одного этажа просмотрщика объекта: плита, слитые стены по материалам, объём. */

export type Part = 'slab' | 'monolith' | 'masonry' | 'volume';

export interface IFloorEntry {
  readonly key: string;
  readonly group: THREE.Group;
  /** Смещение по высоте при полном разнесении, м. */
  readonly offset: number;
  readonly meshes: ReadonlyMap<Part, THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>>;
}

type FloorMesh = THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>;

/** Диапазоны треугольников слитых стен по мешам: по ним `faceIndex` луча находит конструкцию. */
export const wallRanges = new WeakMap<THREE.Object3D, readonly IWallRange[]>();

const makeMesh = (geometry: THREE.BufferGeometry, key: string): FloorMesh => {
  const mesh = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ transparent: true }));
  mesh.userData.floorKey = key;
  return mesh;
};

/** Меши этажа: плита, стены двух материалов (слиянием), а без стен - прозрачный объём этажа. */
export const buildFloor = (spec: IViewerFloorSpec, offset: number): IFloorEntry | null => {
  const meshes = new Map<Part, FloorMesh>();
  const slab = extrudeShell(spec.shell, spec.slabBottom, spec.slabTop);
  if (slab !== null) meshes.set('slab', makeMesh(slab, spec.key));
  for (const material of ['monolith', 'masonry'] as const) {
    const merged = mergeWalls(
      spec.walls.filter((wall) => wall.material === material),
      spec.slabTop,
      spec.wallTop,
    );
    if (merged === null) continue;
    const mesh = makeMesh(merged.geometry, spec.key);
    wallRanges.set(mesh, merged.ranges);
    meshes.set(material, mesh);
  }
  if (!meshes.has('monolith') && !meshes.has('masonry')) {
    const volume = extrudeShell(spec.shell, spec.slabTop, spec.volumeTop);
    if (volume !== null) {
      const mesh = makeMesh(volume, spec.key);
      mesh.material.depthWrite = false;
      meshes.set('volume', mesh);
    }
  }
  if (meshes.size === 0) return null;
  const group = new THREE.Group();
  group.userData.floorKey = spec.key;
  for (const mesh of meshes.values()) group.add(mesh);
  return { key: spec.key, group, offset, meshes };
};
