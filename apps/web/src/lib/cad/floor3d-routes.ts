import type { CadFloor3dRead } from '@quantor/api-client';
import * as THREE from 'three';

import { toScenePoint, type IFloor3dCenter } from './floor3d-geometry';
import {
  buildMepElements,
  createFittingLookup,
  type IFloor3dMepElement,
  type IMepElements,
} from './floor3d-mep-elements';
import { MM_IN_M, mergeSolids, polylineSolids, routeSection } from './floor3d-mep-geometry';
import { readMepColors } from './mep-layers';

/**
 * Трассы механики в 3D-виде этажа (ADR-0036, ADR-0039). Вершины приходят в мм DXF вида, Z - от
 * чистого пола этажа (отметка листа; отопление в стяжке имеет отрицательный Z). Перевод в сцену тот
 * же, что у призм: `toScenePoint` (метры, центр модели в нуле, `Z = -y`), по высоте к Z трассы
 * прибавляется чистый пол модели (`routesBaseZMm`; верх плиты, от которого строятся низ стен и плита,
 * ниже на пирог пола). В клик трассы не входят.
 *
 * Формат `cad_mep_routes3d.v2`: полилиния с сечением (`shape`) рисуется объёмно - труба цилиндрами
 * по Ø, воздуховод коробами, изоляция полупрозрачной оболочкой; геометрии слоя слиты в один Mesh.
 * Полилиния без сечения (файл v1, нет DN или размеров) - линией, как раньше. Фасонина, арматура и
 * гильзы - `floor3d-mep-elements.ts`.
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
  /** Оболочка изоляции (`--cad-mep-insulation`). */
  readonly insulation: string;
  /** Гильзы (`--cad-mep-sleeve`). */
  readonly sleeve: string;
}

export interface IFloor3dRoutePolyline {
  readonly layer: string;
  readonly pts: readonly (readonly number[])[];
  /** С v2: форма и размеры сечения, изоляция; у v1 их нет. */
  readonly shape?: 'round' | 'rect' | null;
  readonly dn_mm?: number | null;
  readonly w_mm?: number | null;
  readonly h_mm?: number | null;
  readonly insulation_mm?: number | null;
}

export interface IFloor3dRoutes {
  readonly group: THREE.Group;
  /** Слои, у которых есть трассы или элементы: по ним применяется видимость. */
  readonly layers: readonly string[];
  setLayerVisible: (layer: string, visible: boolean) => void;
  setAllVisible: (visible: boolean) => void;
  dispose: () => void;
}

/** Трассы рисуются после стен: линии под потолком не мерцают вместе с плитой. */
export const ROUTES_RENDER_ORDER = 5;
/** Оболочка изоляции - после самих труб. */
export const INSULATION_RENDER_ORDER = 6;
export const INSULATION_OPACITY = 0.35;

const FALLBACK_COLOR = 'gray';

/** Цвета слоёв трасс из токенов темы (те же `--cad-mep-*`, что у 2D); без цвета - `--text`. */
export const readFloor3dRouteColors = (): IFloor3dRouteColors => {
  if (typeof document === 'undefined') {
    return {
      layers: readMepColors(() => FALLBACK_COLOR),
      fallback: FALLBACK_COLOR,
      insulation: FALLBACK_COLOR,
      sleeve: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    layers: readMepColors(token),
    fallback: token('--text'),
    insulation: token('--cad-mep-insulation'),
    sleeve: token('--cad-mep-sleeve'),
  };
};

const scenePoints = (
  polyline: IFloor3dRoutePolyline,
  frame: IFloor3dRoutesFrame,
): { readonly points: THREE.Vector3[]; readonly source: (readonly [number, number, number])[] } => {
  const points: THREE.Vector3[] = [];
  const source: (readonly [number, number, number])[] = [];
  for (const point of polyline.pts) {
    const [x, y, zRel] = point;
    if (x === undefined || y === undefined || zRel === undefined) continue;
    if (![x, y, zRel].every(Number.isFinite)) continue;
    const [u, h, v] = toScenePoint(x, y, frame.baseZMm + zRel, frame.center);
    points.push(new THREE.Vector3(u, h, v));
    source.push([x, y, zRel]);
  }
  return { points, source };
};

const push = <T>(map: Map<string, T[]>, key: string, item: T): void => {
  const list = map.get(key);
  if (list === undefined) map.set(key, [item]);
  else list.push(item);
};

/**
 * Трассы этажа: полилиния с сечением - слитые цилиндры или короба (один Mesh на слой) и, при
 * изоляции, отдельная полупрозрачная оболочка; без сечения - `THREE.Line`. Один материал на слой.
 * Вершины с нечисловыми значениями пропускаются. Элементы сети (v2) - в той же группе.
 */
export const buildFloor3dRoutes = (
  polylines: readonly IFloor3dRoutePolyline[],
  colors: IFloor3dRouteColors,
  frame: IFloor3dRoutesFrame,
  elements: readonly IFloor3dMepElement[] = [],
): IFloor3dRoutes => {
  const group = new THREE.Group();
  const geometries: THREE.BufferGeometry[] = [];
  const lineMaterials = new Map<string, THREE.LineBasicMaterial>();
  const solidMaterials = new Map<string, THREE.MeshStandardMaterial>();
  const byLayer = new Map<string, THREE.Object3D[]>();
  const solids = new Map<string, THREE.BufferGeometry[]>();
  const shells = new Map<string, THREE.BufferGeometry[]>();
  const hasFittingNear = createFittingLookup(elements);
  const layerColor = (layer: string): THREE.Color =>
    new THREE.Color(colors.layers[layer] ?? colors.fallback);

  const lineMaterialOf = (layer: string): THREE.LineBasicMaterial => {
    const known = lineMaterials.get(layer);
    if (known !== undefined) return known;
    const material = new THREE.LineBasicMaterial({ color: layerColor(layer), depthTest: true });
    lineMaterials.set(layer, material);
    return material;
  };
  const solidMaterialOf = (layer: string): THREE.MeshStandardMaterial => {
    const known = solidMaterials.get(layer);
    if (known !== undefined) return known;
    const material = new THREE.MeshStandardMaterial({ color: layerColor(layer) });
    solidMaterials.set(layer, material);
    return material;
  };
  // Оболочка изоляции: один цвет-токен на все слои, один материал.
  const shellMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(colors.insulation),
    transparent: true,
    opacity: INSULATION_OPACITY,
    depthWrite: false,
  });

  for (const polyline of polylines) {
    const { points, source } = scenePoints(polyline, frame);
    if (points.length < 2) continue;
    const section = routeSection(polyline);
    if (section === null) {
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      geometries.push(geometry);
      const line = new THREE.Line(geometry, lineMaterialOf(polyline.layer));
      line.renderOrder = ROUTES_RENDER_ORDER;
      group.add(line);
      push(byLayer, polyline.layer, line);
      continue;
    }
    const toleranceMm = (section.shape === 'round' ? section.dnMm / 2 : 0) + 10;
    const hasFittingAt = (index: number): boolean => {
      const at = source[index];
      return at !== undefined && hasFittingNear(polyline.layer, at[0], at[1], at[2], toleranceMm);
    };
    for (const part of polylineSolids(points, section, { hasFittingAt }))
      push(solids, polyline.layer, part);
    const insulation = polyline.insulation_mm;
    if (typeof insulation === 'number' && Number.isFinite(insulation) && insulation > 0) {
      const inflateM = insulation / MM_IN_M;
      for (const part of polylineSolids(points, section, { inflateM, hasFittingAt })) {
        push(shells, polyline.layer, part);
      }
    }
  }

  const addMeshes = (
    parts: Map<string, THREE.BufferGeometry[]>,
    materialOf: (layer: string) => THREE.Material,
    renderOrder: number,
  ): void => {
    for (const [layer, list] of parts) {
      const merged = mergeSolids(list);
      if (merged === null) continue;
      geometries.push(merged);
      const mesh = new THREE.Mesh(merged, materialOf(layer));
      mesh.renderOrder = renderOrder;
      group.add(mesh);
      push(byLayer, layer, mesh);
    }
  };
  addMeshes(solids, solidMaterialOf, ROUTES_RENDER_ORDER);
  addMeshes(shells, () => shellMaterial, INSULATION_RENDER_ORDER);

  const mepElements: IMepElements = buildMepElements(
    elements,
    { layers: colors.layers, fallback: colors.fallback, sleeve: colors.sleeve },
    frame,
    ROUTES_RENDER_ORDER,
  );
  group.add(mepElements.group);
  const layers = [...new Set([...byLayer.keys(), ...mepElements.layers])];

  return {
    group,
    layers,
    setLayerVisible: (layer, visible) => {
      for (const object of byLayer.get(layer) ?? []) object.visible = visible;
      mepElements.setLayerVisible(layer, visible);
    },
    setAllVisible: (visible) => {
      group.visible = visible;
    },
    dispose: () => {
      for (const geometry of geometries) geometry.dispose();
      for (const material of lineMaterials.values()) material.dispose();
      for (const material of solidMaterials.values()) material.dispose();
      shellMaterial.dispose();
      mepElements.dispose();
      group.clear();
    },
  };
};
