import * as THREE from 'three';

import type { ISheetPlaneInput, Point2 } from './model-sheet-overlay';

/**
 * Плоскость листа в 3D: растр страницы на четырёх углах в мм модели. Просмотрщик Speckle - оси
 * Z вверх, метры (`(x, y, z)_мм / 1000`); простой просмотр - оси glTF, Y вверх
 * (`(x/1000, z/1000, −y/1000)`), как части пакета QMP.
 */

/** Насколько лист поднят над отметкой этажа, мм: виден поверх плиты, стены проходят сквозь него. */
export const SHEET_LIFT_MM = 30;

export type UpAxis = 'z' | 'y';

export const toWorld = (point: Point2, zMm: number, up: UpAxis): [number, number, number] =>
  up === 'z'
    ? [point[0] / 1000, point[1] / 1000, zMm / 1000]
    : [point[0] / 1000, zMm / 1000, -point[1] / 1000];

/** Вершины и текстурные координаты: строка растра 0 (верх страницы) - v = 1 (CanvasTexture с flipY). */
export const sheetGeometryArrays = (
  corners: readonly Point2[],
  zMm: number,
  up: UpAxis,
): { positions: Float32Array; uvs: Float32Array; index: number[] } => {
  if (corners.length !== 4) throw new Error('у листа четыре угла');
  const positions = new Float32Array(corners.flatMap((corner) => toWorld(corner, zMm, up)));
  const uvs = new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]);
  return { positions, uvs, index: [0, 1, 2, 0, 2, 3] };
};

export const buildSheetMesh = (plane: ISheetPlaneInput, up: UpAxis): THREE.Mesh => {
  const { positions, uvs, index } = sheetGeometryArrays(
    plane.corners,
    plane.elevationMm + SHEET_LIFT_MM,
    up,
  );
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(index);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  const texture = new THREE.CanvasTexture(plane.canvas);
  texture.anisotropy = 4;
  texture.generateMipmaps = true;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    opacity: plane.opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = 'quantor:sheet-overlay';
  mesh.renderOrder = 10;
  // Не участвует в выборе элементов и во вписывании камеры (у просмотрщиков свои списки объектов).
  mesh.userData = { sheetOverlay: true };
  return mesh;
};

export const setSheetOpacity = (mesh: THREE.Mesh, opacity: number): void => {
  const material = mesh.material as THREE.MeshBasicMaterial;
  material.opacity = opacity;
  material.needsUpdate = true;
};

export const disposeSheetMesh = (mesh: THREE.Mesh): void => {
  mesh.removeFromParent();
  mesh.geometry.dispose();
  const material = mesh.material as THREE.MeshBasicMaterial;
  material.map?.dispose();
  material.dispose();
};
