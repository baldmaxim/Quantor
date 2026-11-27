import * as THREE from 'three';

import { extrudeLevels, mergeShells, mergeWalls, type IViewerFloorSpec } from './building-viewer-geometry';

/** Меши одного этажа просмотрщика объекта: плита, слитые стены по материалам, окна, объём. */

/** `sill` - подоконная часть и перемычки окон; `glass` и `glassCandidate` - стекло по принятой высоте и кандидат. */
export type Part = 'slab' | 'monolith' | 'masonry' | 'sill' | 'glass' | 'glassCandidate' | 'volume';

export interface IFloorEntry {
  readonly key: string;
  readonly group: THREE.Group;
  /** Смещение по высоте при полном разнесении, м. */
  readonly offset: number;
  /** Этаж здания, не поставленного на объект: рисуется полупрозрачным. */
  readonly ghost: boolean;
  readonly meshes: ReadonlyMap<Part, THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>>;
}

type FloorMesh = THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>;

const makeMesh = (geometry: THREE.BufferGeometry, key: string): FloorMesh => {
  const mesh = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ transparent: true }));
  mesh.userData.floorKey = key;
  return mesh;
};

/**
 * Окна этажа: подоконная часть (от верха плиты до низа стекла) и перемычка (от верха окна до верха
 * стены) - один меш цветом кладки; стекло принятых высот и кандидатов - два меша (разная прозрачность).
 * Каждый слит в один буфер, как стены.
 */
const addWindows = (meshes: Map<Part, FloorMesh>, spec: IViewerFloorSpec): void => {
  const solid = spec.windows.flatMap((window) => [
    { id: window.id, shell: window.shell, bottom: window.sillBottom, top: window.glassBottom },
    { id: window.id, shell: window.shell, bottom: window.glassTop, top: window.lintelTop },
  ]);
  const sill = mergeWalls(solid, spec.slabTop, spec.wallTop);
  if (sill !== null) meshes.set('sill', makeMesh(sill.geometry, spec.key));
  for (const [part, accepted] of [
    ['glass', true],
    ['glassCandidate', false],
  ] as const) {
    const glass = mergeWalls(
      spec.windows
        .filter((window) => window.accepted === accepted)
        .map((window) => ({ id: window.id, shell: window.shell, bottom: window.glassBottom, top: window.glassTop })),
      spec.slabTop,
      spec.wallTop,
    );
    if (glass !== null) meshes.set(part, makeMesh(glass.geometry, spec.key));
  }
};

/** Меши этажа: плита, стены двух материалов (слиянием), а без стен - прозрачный объём этажа. */
export const buildFloor = (spec: IViewerFloorSpec, offset: number): IFloorEntry | null => {
  const meshes = new Map<Part, FloorMesh>();
  // Участки уровней (кровля, ступенчатый этаж) - плита по ним, иначе одна плита по контуру.
  const slab =
    spec.levels.length > 0
      ? extrudeLevels(spec.levels, spec.slabTop - spec.slabBottom)
      : mergeShells([spec.shell, ...(spec.extraShells ?? [])], spec.slabBottom, spec.slabTop);
  if (slab !== null) meshes.set('slab', makeMesh(slab, spec.key));
  for (const material of ['monolith', 'masonry'] as const) {
    const merged = mergeWalls(
      spec.walls.filter((wall) => wall.material === material),
      spec.slabTop,
      spec.wallTop,
    );
    if (merged === null) continue;
    meshes.set(material, makeMesh(merged.geometry, spec.key));
  }
  addWindows(meshes, spec);
  if (!meshes.has('monolith') && !meshes.has('masonry')) {
    const volume = mergeShells([spec.shell, ...(spec.extraShells ?? [])], spec.slabTop, spec.volumeTop);
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
  return { key: spec.key, group, offset, ghost: spec.ghost === true, meshes };
};
