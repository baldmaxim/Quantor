import * as THREE from 'three';

import { toScenePoint, type IFloor3dCenter } from './floor3d-geometry';
import {
  JOINT_HEIGHT_SEGMENTS,
  JOINT_WIDTH_SEGMENTS,
  MM_IN_M,
  PIPE_RADIAL_SEGMENTS,
  axisBasis,
  normalizeAxis,
} from './floor3d-mep-geometry';
import { MEP_PICK_KEY, type IMepElementPickData } from './floor3d-mep-pick';

/**
 * Элементы сети в 3D (`cad_mep_routes3d.v2`): фасонина, арматура, гильзы и оконечные приборы. Один
 * `InstancedMesh` на каждую пару (слой, вид геометрии); единичная деталь с осью `+Z` масштабируется
 * под размер элемента. Прибор (`terminal`) - корпус по осям вида: коробка `w x length x h` с центром
 * `pos` или цилиндр Ø `dn_mm` высотой `h_mm` (ороситель). Планирование (`planMepElement`) - чистая
 * функция без three-сцены.
 */

export interface IFloor3dMepElement {
  readonly type: 'fitting' | 'valve' | 'sleeve' | 'terminal';
  readonly subtype: string;
  readonly layer: string;
  readonly pos: readonly number[];
  readonly axis: readonly number[];
  readonly dn_mm?: number | null;
  readonly w_mm?: number | null;
  readonly h_mm?: number | null;
  readonly length_mm?: number | null;
  readonly outer_d_mm?: number | null;
  readonly apt?: string | null;
  /** Марка прибора или ПК, если известна. */
  readonly mark?: string | null;
}

export interface IMepElementColors {
  /** Цвет слоя трасс по имени (токены `--cad-mep-*`). */
  readonly layers: Readonly<Record<string, string>>;
  readonly fallback: string;
  /** Цвет гильз (токен `--cad-mep-sleeve`). */
  readonly sleeve: string;
}

export interface IMepElementsFrame {
  readonly center: IFloor3dCenter;
  /** Чистый пол модели, мм: к `z` элемента прибавляется он, как у трасс. */
  readonly baseZMm: number;
}

export type MepElementKind =
  | 'sphere'
  | 'reducer'
  | 'cleanout'
  | 'box'
  | 'damper'
  | 'sleeve'
  | 'cylinder';
/** Цвет детали: слоя, слоя темнее (арматура) или токен гильзы. */
export type MepElementTone = 'layer' | 'dark' | 'sleeve';

export interface IMepElementPlan {
  readonly layer: string;
  readonly kind: MepElementKind;
  readonly tone: MepElementTone;
  /** Положение, поворот и масштаб экземпляра (метры сцены) для единичной детали с осью `+Z`. */
  readonly matrix: THREE.Matrix4;
}

/** Размеры по ТЗ: доли DN и мм. */
export const FITTING_SPHERE_K = 0.65;
export const REDUCER_LENGTH_K = 1.5;
/** Малый торец переходника относительно большого. */
export const REDUCER_TAPER = 0.65;
export const CLEANOUT_LENGTH_K = 0.8;
export const VALVE_SIDE_K = 1.6;
export const VALVE_LENGTH_K = 2.2;
export const DAMPER_MARGIN_MM = 60;
export const DAMPER_LENGTH_MM = 300;
/** Арматура темнее слоя: множитель яркости цвета. */
export const DARK_TONE_K = 0.6;
/** Ячейка индекса фасонины, мм. */
const GRID_MM = 200;

const positive = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

const IDENTITY_QUATERNION = new THREE.Quaternion();

const compose = (
  position: THREE.Vector3,
  basis: THREE.Matrix4 | null,
  sizeX: number,
  sizeY: number,
  sizeZ: number,
): THREE.Matrix4 =>
  new THREE.Matrix4().compose(
    position,
    basis === null ? IDENTITY_QUATERNION : new THREE.Quaternion().setFromRotationMatrix(basis),
    new THREE.Vector3(sizeX, sizeY, sizeZ),
  );

/** Что и как рисовать для элемента; `null` - данных не хватает (элемент пропускается). */
export const planMepElement = (
  element: IFloor3dMepElement,
  frame: IMepElementsFrame,
): IMepElementPlan | null => {
  const [x, y, z] = element.pos;
  if (x === undefined || y === undefined || z === undefined) return null;
  if (![x, y, z].every(Number.isFinite)) return null;
  const [u, h, v] = toScenePoint(x, y, frame.baseZMm + z, frame.center);
  const position = new THREE.Vector3(u, h, v);
  const dn = positive(element.dn_mm) ? element.dn_mm / MM_IN_M : null;
  const layer = element.layer;

  if (element.type === 'terminal') {
    // Корпус по осям вида (X сцены = x DXF, Z сцены = -y DXF, Y = высота): ось элемента не нужна.
    if (element.subtype === 'sprinkler') {
      if (dn === null || !positive(element.h_mm)) return null;
      return {
        layer,
        kind: 'cylinder',
        tone: 'layer',
        matrix: compose(position, null, dn, element.h_mm / MM_IN_M, dn),
      };
    }
    if (!positive(element.w_mm) || !positive(element.length_mm) || !positive(element.h_mm)) return null;
    return {
      layer,
      kind: 'box',
      tone: 'layer',
      matrix: compose(
        position,
        null,
        element.w_mm / MM_IN_M,
        element.h_mm / MM_IN_M,
        element.length_mm / MM_IN_M,
      ),
    };
  }

  const axis = normalizeAxis(element.axis);

  if (element.type === 'fitting') {
    if (dn === null) return null;
    if (element.subtype === 'reducer' || element.subtype === 'cleanout') {
      if (axis === null) return null;
      const basis = axisBasis(axis);
      if (element.subtype === 'reducer') {
        return {
          layer,
          kind: 'reducer',
          tone: 'layer',
          matrix: compose(position, basis, dn, dn, REDUCER_LENGTH_K * dn),
        };
      }
      // Ревизия торчит от трубы перпендикулярно оси (вверх у горизонтальной трубы).
      const side = new THREE.Vector3();
      basis.extractBasis(new THREE.Vector3(), side, new THREE.Vector3());
      const length = CLEANOUT_LENGTH_K * dn;
      const center = position.clone().addScaledVector(side, dn / 2 + length / 2);
      return {
        layer,
        kind: 'cleanout',
        tone: 'layer',
        matrix: compose(center, axisBasis(side), dn, dn, length),
      };
    }
    // elbow, tee, cross и незнакомые подтипы фасонины - сфера.
    const diameter = 2 * FITTING_SPHERE_K * dn;
    return {
      layer,
      kind: 'sphere',
      tone: 'layer',
      matrix: compose(position, null, diameter / 2, diameter / 2, diameter / 2),
    };
  }

  if (axis === null) return null;
  const basis = axisBasis(axis);

  if (element.type === 'valve') {
    if (element.subtype === 'fire_damper') {
      const width = positive(element.w_mm) ? element.w_mm : dn === null ? null : dn * MM_IN_M;
      const height = positive(element.h_mm) ? element.h_mm : dn === null ? null : dn * MM_IN_M;
      if (width === null || height === null) return null;
      const matrix = compose(
        position,
        basis,
        (width + DAMPER_MARGIN_MM) / MM_IN_M,
        (height + DAMPER_MARGIN_MM) / MM_IN_M,
        DAMPER_LENGTH_MM / MM_IN_M,
      );
      return { layer, kind: 'damper', tone: 'dark', matrix };
    }
    if (dn === null) return null;
    const length = positive(element.length_mm) ? element.length_mm / MM_IN_M : VALVE_LENGTH_K * dn;
    const side = VALVE_SIDE_K * dn;
    return {
      layer,
      kind: 'box',
      tone: 'dark',
      matrix: compose(position, basis, side, side, length),
    };
  }

  // sleeve
  if (!positive(element.length_mm)) return null;
  const sleeveLength = element.length_mm / MM_IN_M;
  if (!positive(element.outer_d_mm)) {
    // Гильза короба: прямоугольная обойма по сечению (w × h) вдоль оси.
    if (!positive(element.w_mm) || !positive(element.h_mm)) return null;
    return {
      layer,
      kind: 'box',
      tone: 'sleeve',
      matrix: compose(position, basis, element.w_mm / MM_IN_M, element.h_mm / MM_IN_M, sleeveLength),
    };
  }
  const outer = element.outer_d_mm / MM_IN_M;
  return {
    layer,
    kind: 'sleeve',
    tone: 'sleeve',
    matrix: compose(position, basis, outer, outer, sleeveLength),
  };
};

/**
 * Индекс фасонин: стоит ли фасонина того же слоя рядом с точкой (мм, в системе файла).
 * Нужен трассам, чтобы не ставить сферу стыка там, где уже есть фасонина.
 */
export const createFittingLookup = (
  elements: readonly IFloor3dMepElement[],
): ((layer: string, x: number, y: number, z: number, toleranceMm: number) => boolean) => {
  const cells = new Map<string, readonly [number, number, number][]>();
  const keyOf = (layer: string, i: number, j: number, k: number): string =>
    `${layer}|${i}|${j}|${k}`;
  for (const element of elements) {
    if (element.type !== 'fitting') continue;
    const [x, y, z] = element.pos;
    if (x === undefined || y === undefined || z === undefined) continue;
    if (![x, y, z].every(Number.isFinite)) continue;
    const key = keyOf(
      element.layer,
      Math.floor(x / GRID_MM),
      Math.floor(y / GRID_MM),
      Math.floor(z / GRID_MM),
    );
    cells.set(key, [...(cells.get(key) ?? []), [x, y, z]]);
  }
  return (layer, x, y, z, toleranceMm) => {
    if (cells.size === 0) return false;
    const reach = Math.max(1, Math.ceil(toleranceMm / GRID_MM));
    const ci = Math.floor(x / GRID_MM);
    const cj = Math.floor(y / GRID_MM);
    const ck = Math.floor(z / GRID_MM);
    for (let i = ci - reach; i <= ci + reach; i += 1) {
      for (let j = cj - reach; j <= cj + reach; j += 1) {
        for (let k = ck - reach; k <= ck + reach; k += 1) {
          for (const [px, py, pz] of cells.get(keyOf(layer, i, j, k)) ?? []) {
            if (Math.hypot(px - x, py - y, pz - z) <= toleranceMm) return true;
          }
        }
      }
    }
    return false;
  };
};

export interface IMepElements {
  readonly group: THREE.Group;
  /** Слои, у которых есть хотя бы один элемент. */
  readonly layers: readonly string[];
  /** `InstancedMesh` для выбора кликом: `instanceId` -> индекс элемента (`userData.mepPick`). */
  readonly pickables: readonly THREE.InstancedMesh[];
  setLayerVisible: (layer: string, visible: boolean) => void;
  dispose: () => void;
}

/** Единичные детали с осью `+Z` и диаметром (или стороной) 1; сфера - радиусом 1. */
const unitGeometry = (kind: MepElementKind): THREE.BufferGeometry => {
  switch (kind) {
    case 'cylinder':
      // Вертикальный цилиндр (ось по Y сцены): ороситель.
      return new THREE.CylinderGeometry(0.5, 0.5, 1, PIPE_RADIAL_SEGMENTS);
    case 'sphere':
      return new THREE.SphereGeometry(1, JOINT_WIDTH_SEGMENTS, JOINT_HEIGHT_SEGMENTS);
    case 'reducer':
      return new THREE.CylinderGeometry(0.5, 0.5 * REDUCER_TAPER, 1, PIPE_RADIAL_SEGMENTS).rotateX(
        Math.PI / 2,
      );
    case 'cleanout':
      return new THREE.CylinderGeometry(0.5, 0.5, 1, PIPE_RADIAL_SEGMENTS).rotateX(Math.PI / 2);
    case 'sleeve':
      return new THREE.CylinderGeometry(0.5, 0.5, 1, PIPE_RADIAL_SEGMENTS, 1, true).rotateX(
        Math.PI / 2,
      );
    case 'box':
    case 'damper':
      return new THREE.BoxGeometry(1, 1, 1);
  }
};

/** Тело одного элемента в координатах сцены (для оверлея выделения); `null` - данных не хватает. */
export const mepElementGeometry = (
  element: IFloor3dMepElement,
  frame: IMepElementsFrame,
): THREE.BufferGeometry | null => {
  const plan = planMepElement(element, frame);
  return plan === null ? null : unitGeometry(plan.kind).applyMatrix4(plan.matrix);
};

const toneColor = (tone: MepElementTone, layer: string, colors: IMepElementColors): THREE.Color => {
  if (tone === 'sleeve') return new THREE.Color(colors.sleeve);
  const base = new THREE.Color(colors.layers[layer] ?? colors.fallback);
  return tone === 'dark' ? base.multiplyScalar(DARK_TONE_K) : base;
};

export const buildMepElements = (
  elements: readonly IFloor3dMepElement[],
  colors: IMepElementColors,
  frame: IMepElementsFrame,
  renderOrder: number,
): IMepElements => {
  const group = new THREE.Group();
  interface IPlanned {
    readonly plan: IMepElementPlan;
    /** Индекс элемента в исходном массиве. */
    readonly index: number;
  }
  const groups = new Map<string, IPlanned[]>();
  elements.forEach((element, index) => {
    const plan = planMepElement(element, frame);
    if (plan === null) return;
    const key = `${plan.layer}|${plan.kind}|${plan.tone}`;
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [{ plan, index }]);
    else list.push({ plan, index });
  });

  const geometries = new Map<MepElementKind, THREE.BufferGeometry>();
  const materials = new Map<string, THREE.MeshStandardMaterial>();
  const meshes: THREE.InstancedMesh[] = [];
  const byLayer = new Map<string, THREE.InstancedMesh[]>();

  for (const planned of groups.values()) {
    const first = planned[0]?.plan;
    if (first === undefined) continue;
    let geometry = geometries.get(first.kind);
    if (geometry === undefined) {
      geometry = unitGeometry(first.kind);
      geometries.set(first.kind, geometry);
    }
    const materialKey = `${first.layer}|${first.tone}|${first.kind === 'sleeve'}`;
    let material = materials.get(materialKey);
    if (material === undefined) {
      material = new THREE.MeshStandardMaterial({
        color: toneColor(first.tone, first.layer, colors),
        side: first.kind === 'sleeve' ? THREE.DoubleSide : THREE.FrontSide,
      });
      materials.set(materialKey, material);
    }
    const mesh = new THREE.InstancedMesh(geometry, material, planned.length);
    planned.forEach((item, at) => mesh.setMatrixAt(at, item.plan.matrix));
    mesh.instanceMatrix.needsUpdate = true;
    mesh.renderOrder = renderOrder;
    const pickData: IMepElementPickData = { kind: 'element', indices: planned.map((item) => item.index) };
    mesh.userData[MEP_PICK_KEY] = pickData;
    group.add(mesh);
    meshes.push(mesh);
    const list = byLayer.get(first.layer);
    if (list === undefined) byLayer.set(first.layer, [mesh]);
    else list.push(mesh);
  }

  return {
    group,
    layers: [...byLayer.keys()],
    pickables: meshes,
    setLayerVisible: (layer, visible) => {
      for (const mesh of byLayer.get(layer) ?? []) mesh.visible = visible;
    },
    dispose: () => {
      for (const mesh of meshes) mesh.dispose();
      for (const geometry of geometries.values()) geometry.dispose();
      for (const material of materials.values()) material.dispose();
      group.clear();
    },
  };
};
