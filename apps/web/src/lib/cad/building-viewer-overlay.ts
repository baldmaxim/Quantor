import * as THREE from 'three';

import type { Point2 } from './building3d-geometry';
import { extrudeShell } from './building-viewer-geometry';

/**
 * Подсветка одной конструкции этажа поверх его слитых мешей: отдельный меш акцентного цвета и,
 * для выбранной, контур рёбер. Меш чуть выше и ниже стены и со сдвигом глубины, чтобы совпадающие
 * грани не мерцали; цвета - токен акцента, переданный вызывающим.
 */

export type OverlayKind = 'selected' | 'hover';

export interface IOverlayTarget {
  readonly shell: readonly Point2[];
  /** Низ и верх стены в координатах плана, м. */
  readonly yBottom: number;
  readonly yTop: number;
}

/** Вынос подсветки за стену по высоте, м. */
const INFLATE_M = 0.03;
const OPACITY: Record<OverlayKind, number> = { selected: 0.9, hover: 0.45 };

/** Подсветка стены; контур нельзя построить (вырожденный) - `null`. */
export const createWallOverlay = (
  target: IOverlayTarget,
  kind: OverlayKind,
  color: THREE.ColorRepresentation,
): THREE.Group | null => {
  const geometry = extrudeShell(target.shell, target.yBottom - INFLATE_M, target.yTop + INFLATE_M);
  if (geometry === null) return null;
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: OPACITY[kind],
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  group.add(new THREE.Mesh(geometry, material));
  if (kind === 'selected') {
    group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), new THREE.LineBasicMaterial({ color })));
  }
  return group;
};

/** Освобождает геометрии и материалы подсветки и убирает её из сцены. */
export const disposeWallOverlay = (group: THREE.Group): void => {
  group.removeFromParent();
  group.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
      object.geometry.dispose();
      const material: THREE.Material | THREE.Material[] = object.material;
      for (const item of Array.isArray(material) ? material : [material]) item.dispose();
    }
  });
};
