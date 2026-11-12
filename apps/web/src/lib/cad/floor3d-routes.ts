import type { CadFloor3dRead } from '@quantor/api-client';
import * as THREE from 'three';

import { toScenePoint, type IFloor3dCenter } from './floor3d-geometry';
import { readMepColors } from './mep-layers';

/**
 * Трассы механики в 3D-виде этажа (ADR-0036, ADR-0039). Вершины приходят в мм DXF вида, Z - от
 * чистого пола этажа (отметка листа; отопление в стяжке имеет отрицательный Z). Перевод в сцену тот
 * же, что у призм: `toScenePoint` (метры, центр модели в нуле, `Z = -y`), по высоте к Z трассы
 * прибавляется чистый пол модели (`routesBaseZMm`; верх плиты, от которого строятся низ стен и плита,
 * ниже на пирог пола). В клик трассы не входят.
 */

/** Чистый пол модели этажа, мм: отметка листа, а без неё - база модели (`base_z_mm`). */
export const routesBaseZMm = (model: Pick<CadFloor3dRead, 'base_z_mm' | 'heights'>): number =>
  model.heights.floor_elevation_mm ?? model.base_z_mm;

export interface IFloor3dRoutesFrame {
  /** Центр модели этажа: тот же, что у призм плана. */
  readonly center: IFloor3dCenter;
  /** Чистый пол модели (`routesBaseZMm`), мм: от него отсчитан `z_rel` трасс. */
  readonly baseZMm: number;
}

export interface IFloor3dRouteColors {
  /** Цвет слоя трасс по имени (значения токенов темы). */
  readonly layers: Readonly<Record<string, string>>;
  /** Цвет слоя без своего цвета: нейтральный токен темы. */
  readonly fallback: string;
}

export interface IFloor3dRoutePolyline {
  readonly layer: string;
  readonly pts: readonly (readonly number[])[];
}

export interface IFloor3dRoutes {
  readonly group: THREE.Group;
  setLayerVisible: (layer: string, visible: boolean) => void;
  setAllVisible: (visible: boolean) => void;
  dispose: () => void;
}

/** Трассы рисуются после стен: линии под потолком не мерцают вместе с плитой. */
export const ROUTES_RENDER_ORDER = 5;

const FALLBACK_COLOR = 'gray';

/** Цвета слоёв трасс из токенов темы (те же `--cad-mep-*`, что у 2D); без цвета - `--text`. */
export const readFloor3dRouteColors = (): IFloor3dRouteColors => {
  if (typeof document === 'undefined') {
    return { layers: readMepColors(() => FALLBACK_COLOR), fallback: FALLBACK_COLOR };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return { layers: readMepColors(token), fallback: token('--text') };
};

/** Одна линия на полилинию, один материал на слой. Вершины с нечисловыми значениями пропускаются. */
export const buildFloor3dRoutes = (
  polylines: readonly IFloor3dRoutePolyline[],
  colors: IFloor3dRouteColors,
  frame: IFloor3dRoutesFrame,
): IFloor3dRoutes => {
  const group = new THREE.Group();
  const geometries: THREE.BufferGeometry[] = [];
  const materials = new Map<string, THREE.LineBasicMaterial>();
  const byLayer = new Map<string, THREE.Line[]>();

  const materialOf = (layer: string): THREE.LineBasicMaterial => {
    const known = materials.get(layer);
    if (known !== undefined) return known;
    const material = new THREE.LineBasicMaterial({
      color: new THREE.Color(colors.layers[layer] ?? colors.fallback),
      depthTest: true,
    });
    materials.set(layer, material);
    return material;
  };

  for (const polyline of polylines) {
    const points: THREE.Vector3[] = [];
    for (const point of polyline.pts) {
      const [x, y, zRel] = point;
      if (x === undefined || y === undefined || zRel === undefined) continue;
      if (![x, y, zRel].every(Number.isFinite)) continue;
      const [u, h, v] = toScenePoint(x, y, frame.baseZMm + zRel, frame.center);
      points.push(new THREE.Vector3(u, h, v));
    }
    if (points.length < 2) continue;
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    geometries.push(geometry);
    const line = new THREE.Line(geometry, materialOf(polyline.layer));
    line.renderOrder = ROUTES_RENDER_ORDER;
    group.add(line);
    const list = byLayer.get(polyline.layer);
    if (list === undefined) byLayer.set(polyline.layer, [line]);
    else list.push(line);
  }

  return {
    group,
    setLayerVisible: (layer, visible) => {
      for (const line of byLayer.get(layer) ?? []) line.visible = visible;
    },
    setAllVisible: (visible) => {
      group.visible = visible;
    },
    dispose: () => {
      for (const geometry of geometries) geometry.dispose();
      for (const material of materials.values()) material.dispose();
      group.clear();
    },
  };
};
