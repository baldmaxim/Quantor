import type { CadFloor3dRead } from '@quantor/api-client';
import * as THREE from 'three';

import { toScenePoint, type IFloor3dCenter } from './floor3d-geometry';
import {
  buildMepElements,
  createFittingLookup,
  mepElementGeometry,
  type IFloor3dMepElement,
  type IMepElements,
} from './floor3d-mep-elements';
import {
  MM_IN_M,
  mergeSolids,
  polylineSolids,
  routeSection,
  type RouteSection,
} from './floor3d-mep-geometry';
import {
  MEP_PICK_KEY,
  createMepHighlight,
  triangleCount,
  type IMepHighlight,
  type IMepPick,
  type IMepRoutePickData,
} from './floor3d-mep-pick';
import { readMepColors } from './mep-layers';

/**
 * Трассы механики в 3D-виде этажа (ADR-0036, ADR-0039). Вершины приходят в мм DXF вида, Z - от
 * чистого пола этажа (отметка листа; отопление в стяжке имеет отрицательный Z). Перевод в сцену тот
 * же, что у призм: `toScenePoint` (метры, центр модели в нуле, `Z = -y`), по высоте к Z трассы
 * прибавляется чистый пол модели (`routesBaseZMm`; верх плиты, от которого строятся низ стен и плита,
 * ниже на пирог пола).
 *
 * Формат `cad_mep_routes3d.v2`: полилиния с сечением (`shape`) рисуется объёмно - труба цилиндрами
 * по Ø, воздуховод коробами, изоляция полупрозрачной оболочкой; геометрии слоя слиты в один Mesh.
 * Круглая без Ø - труба условного Ø (`DISPLAY_DN_UNKNOWN_MM`). Полилиния без `shape` (файл v1) или
 * короб без размеров - линией, как раньше. Фасонина, арматура, гильзы и приборы - `floor3d-mep-elements.ts`.
 *
 * Выбор кликом (`floor3d-mep-pick.ts`): слитый меш слоя хранит диапазоны треугольников по полилиниям,
 * `InstancedMesh` элементов - соответствие экземпляра элементу; оболочка изоляции и линии v1 в выбор
 * не входят. Выделение - оверлей из тел выбранной трассы или элемента.
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
  /** Выделение выбранной трассы или элемента (`--accent`). */
  readonly accent: string;
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
  /** С v15: вид полилинии, источник Ø, марка стояка, уклон, квартира; у старых файлов пусто. */
  readonly kind?: 'route' | 'jumper' | 'riser' | 'leadin' | null;
  readonly dn_source?: 'line' | 'registry' | 'rule' | null;
  readonly mark?: string | null;
  readonly slope?: number | null;
  readonly apt?: string | null;
  /** Изделие линии ЭОМ и СС (`cad_eom`): «Кабель ... в трубе Ø16»; у механики нет. */
  readonly item?: string | null;
}

export interface IFloor3dRoutes {
  readonly group: THREE.Group;
  /** Слои, у которых есть трассы или элементы: по ним применяется видимость. */
  readonly layers: readonly string[];
  /** Меши, по которым работает выбор ВИС: слитые тела трасс и `InstancedMesh` элементов. */
  readonly pickables: readonly THREE.Object3D[];
  /** Выделить трассу или элемент оверлеем; `null` - снять. Переживает смену видимости слоя. */
  setHighlight: (pick: IMepPick | null) => void;
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
      accent: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    layers: readMepColors(token),
    fallback: token('--text'),
    insulation: token('--cad-mep-insulation'),
    sleeve: token('--cad-mep-sleeve'),
    accent: token('--accent'),
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
  const pickables: THREE.Object3D[] = [];
  /** Тела трасс слоя по полилиниям: индекс полилинии и её детали (для карты треугольников). */
  const solids = new Map<string, { readonly index: number; readonly parts: THREE.BufferGeometry[] }[]>();
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

  // Тела полилинии (и её изоляции при `inflateM`): сферы стыка ставятся там, где нет фасонины.
  const bodiesOf = (
    polyline: IFloor3dRoutePolyline,
    points: readonly THREE.Vector3[],
    source: readonly (readonly [number, number, number])[],
    section: RouteSection,
    inflateM = 0,
  ): THREE.BufferGeometry[] => {
    const toleranceMm = (section.shape === 'round' ? section.dnMm / 2 : 0) + 10;
    const hasFittingAt = (index: number): boolean => {
      const at = source[index];
      return at !== undefined && hasFittingNear(polyline.layer, at[0], at[1], at[2], toleranceMm);
    };
    return polylineSolids(points, section, { inflateM, hasFittingAt });
  };

  polylines.forEach((polyline, index) => {
    const { points, source } = scenePoints(polyline, frame);
    if (points.length < 2) return;
    const section = routeSection(polyline);
    if (section === null) {
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      geometries.push(geometry);
      const line = new THREE.Line(geometry, lineMaterialOf(polyline.layer));
      line.renderOrder = ROUTES_RENDER_ORDER;
      group.add(line);
      push(byLayer, polyline.layer, line);
      return;
    }
    push(solids, polyline.layer, { index, parts: bodiesOf(polyline, points, source, section) });
    const insulation = polyline.insulation_mm;
    if (typeof insulation === 'number' && Number.isFinite(insulation) && insulation > 0) {
      for (const part of bodiesOf(polyline, points, source, section, insulation / MM_IN_M)) {
        push(shells, polyline.layer, part);
      }
    }
  });

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
  // Тела трасс: один меш на слой, у меша - карта «диапазон треугольников -> полилиния».
  for (const [layer, items] of solids) {
    const flat: THREE.BufferGeometry[] = [];
    const starts: number[] = [];
    const indices: number[] = [];
    let total = 0;
    for (const item of items) {
      if (item.parts.length === 0) continue;
      starts.push(total);
      indices.push(item.index);
      for (const part of item.parts) {
        total += triangleCount(part);
        flat.push(part);
      }
    }
    const merged = mergeSolids(flat);
    if (merged === null) continue;
    geometries.push(merged);
    const mesh = new THREE.Mesh(merged, solidMaterialOf(layer));
    mesh.renderOrder = ROUTES_RENDER_ORDER;
    const pickData: IMepRoutePickData = { kind: 'route', starts, indices, total };
    mesh.userData[MEP_PICK_KEY] = pickData;
    group.add(mesh);
    push(byLayer, layer, mesh);
    pickables.push(mesh);
  }
  addMeshes(shells, () => shellMaterial, INSULATION_RENDER_ORDER);

  const mepElements: IMepElements = buildMepElements(
    elements,
    { layers: colors.layers, fallback: colors.fallback, sleeve: colors.sleeve },
    frame,
    ROUTES_RENDER_ORDER,
  );
  group.add(mepElements.group);
  pickables.push(...mepElements.pickables);
  const layers = [...new Set([...byLayer.keys(), ...mepElements.layers])];

  // Выделение: оверлей тел выбранной трассы или элемента; скрывается вместе со своим слоем.
  const hiddenLayers = new Set<string>();
  let overlay: { readonly highlight: IMepHighlight; readonly layer: string } | null = null;
  const clearOverlay = (): void => {
    if (overlay === null) return;
    group.remove(overlay.highlight.group);
    overlay.highlight.dispose();
    overlay = null;
  };
  const highlightBodies = (
    pick: IMepPick,
  ): { readonly layer: string; readonly bodies: THREE.BufferGeometry[] } | null => {
    if (pick.kind === 'element') {
      const element = elements[pick.index];
      const body = element === undefined ? null : mepElementGeometry(element, frame);
      return element === undefined || body === null ? null : { layer: element.layer, bodies: [body] };
    }
    const polyline = polylines[pick.index];
    if (polyline === undefined) return null;
    const section = routeSection(polyline);
    const { points, source } = scenePoints(polyline, frame);
    if (section === null || points.length < 2) return null;
    return { layer: polyline.layer, bodies: bodiesOf(polyline, points, source, section) };
  };

  return {
    group,
    layers,
    pickables,
    setHighlight: (pick) => {
      clearOverlay();
      if (pick === null) return;
      const target = highlightBodies(pick);
      if (target === null) return;
      const highlight = createMepHighlight(target.bodies, colors.accent);
      if (highlight === null) return;
      highlight.group.visible = !hiddenLayers.has(target.layer);
      group.add(highlight.group);
      overlay = { highlight, layer: target.layer };
    },
    setLayerVisible: (layer, visible) => {
      if (visible) hiddenLayers.delete(layer);
      else hiddenLayers.add(layer);
      for (const object of byLayer.get(layer) ?? []) object.visible = visible;
      mepElements.setLayerVisible(layer, visible);
      if (overlay !== null && overlay.layer === layer) overlay.highlight.group.visible = visible;
    },
    setAllVisible: (visible) => {
      group.visible = visible;
    },
    dispose: () => {
      clearOverlay();
      for (const geometry of geometries) geometry.dispose();
      for (const material of lineMaterials.values()) material.dispose();
      for (const material of solidMaterials.values()) material.dispose();
      shellMaterial.dispose();
      mepElements.dispose();
      group.clear();
    },
  };
};
