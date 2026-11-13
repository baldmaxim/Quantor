import type * as THREE from 'three';

import { isEffectivelyVisible, mepPickOf, type IMepPick } from './floor3d-mep-pick';
import type { IFloor3dRoutes } from './floor3d-routes';
import { pickOf, type IFloor3dPick, type IFloor3dScene } from './floor3d-scene';

/** Что нашёл луч: конструкция, плита, проём, отверстие (`model`) либо трасса или элемент ВИС (`mep`). */
export type Floor3dHit =
  | { readonly kind: 'model'; readonly pick: IFloor3dPick }
  | { readonly kind: 'mep'; readonly pick: IMepPick };

/**
 * Ближайший выбираемый объект под лучом среди модели этажа и трасс. Скрытое (категорией, слоем или
 * группой трасс) в выбор не входит: `Raycaster` флаг `visible` не проверяет. Оболочка изоляции и
 * линии в выбор не входят: луч проходит сквозь них к трубе.
 */
export const hitScene = (
  raycaster: THREE.Raycaster,
  model: Pick<IFloor3dScene, 'pickables'> | null,
  routes: Pick<IFloor3dRoutes, 'pickables'> | null,
): Floor3dHit | null => {
  const targets = [...(model?.pickables ?? []), ...(routes?.pickables ?? [])].filter(isEffectivelyVisible);
  for (const hit of raycaster.intersectObjects(targets, false)) {
    const mep = mepPickOf(hit);
    if (mep !== null) return { kind: 'mep', pick: mep };
    const pick = pickOf(hit.object, hit.faceIndex);
    if (pick !== null) return { kind: 'model', pick };
  }
  return null;
};
