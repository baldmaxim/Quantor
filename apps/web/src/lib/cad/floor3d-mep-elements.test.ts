import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import {
  DARK_TONE_K,
  buildMepElements,
  createFittingLookup,
  planMepElement,
  type IFloor3dMepElement,
  type IMepElementColors,
} from './floor3d-mep-elements';

const COLORS: IMepElementColors = {
  layers: { 'M-VK-V1': 'rgb(0, 120, 200)', 'M-OV-T1': 'rgb(200, 40, 30)' },
  fallback: 'rgb(9, 9, 9)',
  sleeve: 'rgb(120, 130, 140)',
};
const frame = { center: { x: 0, y: 0, z: 0 }, baseZMm: 1000 };

const element = (patch: Partial<IFloor3dMepElement>): IFloor3dMepElement => ({
  type: 'fitting',
  subtype: 'elbow',
  layer: 'M-VK-V1',
  pos: [2000, 3000, 500],
  axis: [1000, 0, 0],
  dn_mm: 50,
  ...patch,
});

const parts = (matrix: THREE.Matrix4) => {
  const position = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  matrix.decompose(position, quaternion, scale);
  return { position, scale, axis: new THREE.Vector3(0, 0, 1).transformDirection(matrix) };
};

const instanced = (group: THREE.Group): THREE.InstancedMesh[] =>
  group.children.filter(
    (child): child is THREE.InstancedMesh => child instanceof THREE.InstancedMesh,
  );

describe('планирование элементов', () => {
  it('щит ЭОМ (device) - короб w×h×d: ширина вдоль стены, высота вертикально, глубина по нормали', () => {
    const plan = planMepElement(
      element({
        type: 'device',
        subtype: 'panel_floor',
        layer: 'E-EO-DEV',
        axis: [0, 1000, 0],
        dn_mm: null,
        w_mm: 800,
        h_mm: 1400,
        d_mm: 160,
      }),
      frame,
    );
    expect(plan?.kind).toBe('box');
    expect(plan?.tone).toBe('layer');
    const { position, scale, axis } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect(position.toArray()).toEqual([2, 1.5, -3]);
    expect([scale.x, scale.y, scale.z].map((v) => Number(v.toFixed(6)))).toEqual([0.8, 1.4, 0.16]);
    expect(axis.distanceTo(new THREE.Vector3(0, 0, -1))).toBeCloseTo(0, 6);
    const up = new THREE.Vector3(0, 1, 0).transformDirection(
      (plan as { matrix: THREE.Matrix4 }).matrix,
    );
    expect(up.distanceTo(new THREE.Vector3(0, 1, 0))).toBeCloseTo(0, 6);
  });

  it('прибор без габарита не рисуется', () => {
    expect(
      planMepElement(element({ type: 'box', w_mm: 80, h_mm: 80, d_mm: null }), frame),
    ).toBeNull();
  });

  it('фасонина elbow/tee/cross - сфера радиусом 0,65 DN в точке с учётом чистого пола', () => {
    for (const subtype of ['elbow', 'tee', 'cross']) {
      const plan = planMepElement(element({ subtype }), frame);
      expect(plan?.kind).toBe('sphere');
      const { position, scale } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
      expect(position.toArray()).toEqual([2, 1.5, -3]);
      expect(scale.x).toBeCloseTo(0.65 * 0.05, 9);
    }
  });

  it('фасонина короба - угловой блок сечения короба с запасом на фланцы, по оси', () => {
    const duct = { layer: 'M-OV-VZH', dn_mm: null, w_mm: 300, h_mm: 200, axis: [0, 1000, 0] };
    for (const subtype of ['elbow', 'tee', 'cross']) {
      const plan = planMepElement(element({ ...duct, subtype }), frame);
      expect(plan?.kind).toBe('box');
      const { position, scale, axis } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
      expect(position.toArray()).toEqual([2, 1.5, -3]);
      expect([scale.x, scale.y, scale.z]).toEqual(
        [0.33, 0.23, 0.33].map((n) => expect.closeTo(n, 9)),
      );
      expect(axis.distanceTo(new THREE.Vector3(0, 0, -1))).toBeCloseTo(0, 6);
    }
    // стык короба с круглым вводом (есть и DN, и сечение) - тоже блок короба
    expect(planMepElement(element({ ...duct, dn_mm: 110 }), frame)?.kind).toBe('box');
    expect(planMepElement(element({ ...duct, axis: [0, 0, 0] }), frame)).toBeNull();
  });

  it('переход короба: короб на короб - короб, круг на короб - конус от сечения короба', () => {
    const duct = { layer: 'M-OV-MO', subtype: 'reducer', w_mm: 200, h_mm: 200, axis: [1000, 0, 0] };
    const rect = planMepElement(element({ ...duct, dn_mm: null }), frame);
    expect(rect?.kind).toBe('box');
    const a = parts((rect as { matrix: THREE.Matrix4 }).matrix).scale;
    expect([a.x, a.y, a.z]).toEqual([0.23, 0.23, 0.8 * 0.23].map((n) => expect.closeTo(n, 9)));
    expect(planMepElement(element({ ...duct, dn_mm: 110 }), frame)?.kind).toBe('reducer');
  });

  it('reducer - конус длиной 1,5 DN вдоль оси', () => {
    const plan = planMepElement(element({ subtype: 'reducer', axis: [0, 1000, 0] }), frame);
    expect(plan?.kind).toBe('reducer');
    const { scale, axis } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect(scale.z).toBeCloseTo(1.5 * 0.05, 9);
    expect(scale.x).toBeCloseTo(0.05, 9);
    expect(axis.distanceTo(new THREE.Vector3(0, 0, -1))).toBeCloseTo(0, 6);
  });

  it('cleanout - короткий цилиндр Ø DN перпендикулярно оси трубы', () => {
    const plan = planMepElement(element({ subtype: 'cleanout', axis: [1000, 0, 0] }), frame);
    expect(plan?.kind).toBe('cleanout');
    const { axis, scale } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect(Math.abs(axis.dot(new THREE.Vector3(1, 0, 0)))).toBeCloseTo(0, 6);
    expect(scale.x).toBeCloseTo(0.05, 9);
  });

  it('valve - короб 1,6 DN x 1,6 DN x 2,2 DN, длина из length_mm главнее, цвет темнее', () => {
    const plain = planMepElement(
      element({ type: 'valve', subtype: 'ball_valve', dn_mm: 25 }),
      frame,
    );
    expect(plain?.kind).toBe('box');
    expect(plain?.tone).toBe('dark');
    const a = parts((plain as { matrix: THREE.Matrix4 }).matrix).scale;
    expect([a.x, a.y, a.z]).toEqual(
      [1.6 * 0.025, 1.6 * 0.025, 2.2 * 0.025].map((n) => expect.closeTo(n, 9)),
    );
    const long = planMepElement(
      element({ type: 'valve', subtype: 'filter', dn_mm: 25, length_mm: 180 }),
      frame,
    );
    expect(parts((long as { matrix: THREE.Matrix4 }).matrix).scale.z).toBeCloseTo(0.18, 9);
  });

  it('fire_damper - (w+60) x (h+60) x 300 мм, без w/h - по DN', () => {
    const sized = planMepElement(
      element({ type: 'valve', subtype: 'fire_damper', w_mm: 400, h_mm: 200, dn_mm: null }),
      frame,
    );
    const a = parts((sized as { matrix: THREE.Matrix4 }).matrix).scale;
    expect([a.x, a.y, a.z]).toEqual([0.46, 0.26, 0.3].map((n) => expect.closeTo(n, 9)));
    const round = planMepElement(
      element({ type: 'valve', subtype: 'fire_damper', dn_mm: 100 }),
      frame,
    );
    expect(parts((round as { matrix: THREE.Matrix4 }).matrix).scale.x).toBeCloseTo(0.16, 9);
    expect(
      planMepElement(element({ type: 'valve', subtype: 'fire_damper', dn_mm: null }), frame),
    ).toBeNull();
  });

  it('sleeve - открытый цилиндр длиной length_mm и Ø outer_d_mm', () => {
    const plan = planMepElement(
      element({ type: 'sleeve', subtype: 'wall', length_mm: 260, outer_d_mm: 135 }),
      frame,
    );
    expect(plan?.kind).toBe('sleeve');
    expect(plan?.tone).toBe('sleeve');
    const { scale } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect([scale.x, scale.y, scale.z]).toEqual(
      [0.135, 0.135, 0.26].map((n) => expect.closeTo(n, 9)),
    );
    const box = planMepElement(
      element({ type: 'sleeve', subtype: 'slab', length_mm: 260, w_mm: 400, h_mm: 200 }),
      frame,
    );
    expect(box?.kind).toBe('box');
    expect(box?.tone).toBe('sleeve');
  });

  it('гильза без outer_d_mm и без w_mm/h_mm - null', () => {
    expect(
      planMepElement(element({ type: 'sleeve', subtype: 'slab', length_mm: 260 }), frame),
    ).toBeNull();
  });

  it('ось в целых x1000 нормализуется: [2000,0,0] и [0,0,1000]', () => {
    const horizontal = planMepElement(
      element({ type: 'valve', subtype: 'ball_valve', axis: [2000, 0, 0] }),
      frame,
    );
    const vertical = planMepElement(
      element({ type: 'valve', subtype: 'ball_valve', axis: [0, 0, 1000] }),
      frame,
    );
    const h = parts((horizontal as { matrix: THREE.Matrix4 }).matrix).axis;
    const v = parts((vertical as { matrix: THREE.Matrix4 }).matrix).axis;
    expect(h.distanceTo(new THREE.Vector3(1, 0, 0))).toBeCloseTo(0, 6);
    expect(v.distanceTo(new THREE.Vector3(0, 1, 0))).toBeCloseTo(0, 6);
  });

  it('без позиции, DN или оси элемент пропускается', () => {
    expect(planMepElement(element({ pos: [1, 2] }), frame)).toBeNull();
    expect(planMepElement(element({ dn_mm: null }), frame)).toBeNull();
    expect(
      planMepElement(element({ type: 'valve', subtype: 'filter', axis: [0, 0, 0] }), frame),
    ).toBeNull();
  });
});

describe('оконечные приборы (terminal)', () => {
  const terminal = (patch: Partial<IFloor3dMepElement> = {}): IFloor3dMepElement => ({
    type: 'terminal',
    subtype: 'wc',
    layer: 'M-SAN-WC',
    pos: [2000, 3000, 400],
    axis: [0, 0, 1000],
    w_mm: 360,
    length_mm: 600,
    h_mm: 800,
    ...patch,
  });

  it('коробка w x length x h по осям вида, центр в pos с учётом чистого пола', () => {
    const plan = planMepElement(terminal(), frame);
    expect(plan?.kind).toBe('box');
    expect(plan?.tone).toBe('layer');
    const { position, scale, axis } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect(position.toArray()).toEqual([2, 1.4, -3]);
    // X сцены - ширина (вдоль X вида), Y - высота, Z - длина (вдоль Y вида).
    expect(scale.toArray()).toEqual([0.36, 0.8, 0.6]);
    // Без поворота: ось элемента корпус не вращает.
    expect(axis.distanceTo(new THREE.Vector3(0, 0, 1))).toBeCloseTo(0, 9);
    expect(
      planMepElement(terminal({ axis: [1000, 0, 0] }), frame)?.matrix.equals(
        (plan as { matrix: THREE.Matrix4 }).matrix,
      ),
    ).toBe(true);
  });

  it('ороситель - вертикальный цилиндр Ø dn_mm высотой h_mm', () => {
    const plan = planMepElement(
      terminal({ subtype: 'sprinkler', dn_mm: 15, h_mm: 50, w_mm: null, length_mm: null }),
      frame,
    );
    expect(plan?.kind).toBe('cylinder');
    const { scale } = parts((plan as { matrix: THREE.Matrix4 }).matrix);
    expect(scale.toArray()).toEqual([0.015, 0.05, 0.015]);
  });

  it('без размеров корпуса - пропускается', () => {
    expect(planMepElement(terminal({ w_mm: null }), frame)).toBeNull();
    expect(planMepElement(terminal({ h_mm: 0 }), frame)).toBeNull();
    expect(
      planMepElement(terminal({ subtype: 'sprinkler', dn_mm: null, h_mm: 50 }), frame),
    ).toBeNull();
  });

  it('InstancedMesh по слою с токеном слоя; сантехника M-SAN-* - свой цвет', () => {
    const colors: IMepElementColors = {
      ...COLORS,
      layers: { ...COLORS.layers, 'M-SAN-WC': 'rgb(10, 200, 90)' },
    };
    const built = buildMepElements(
      [
        terminal(),
        terminal({ pos: [5000, 0, 400] }),
        terminal({ layer: 'M-OV-T1', subtype: 'convector' }),
      ],
      colors,
      frame,
      5,
    );
    const meshes = instanced(built.group);
    expect(meshes.map((mesh) => mesh.count).sort()).toEqual([1, 2]);
    const san = meshes.find((mesh) => mesh.count === 2) as THREE.InstancedMesh;
    expect((san.material as THREE.MeshStandardMaterial).color.getHex()).toBe(
      new THREE.Color('rgb(10, 200, 90)').getHex(),
    );
    built.setLayerVisible('M-SAN-WC', false);
    expect(meshes.filter((mesh) => mesh.visible)).toHaveLength(1);
    built.dispose();
  });
});

describe('InstancedMesh элементов', () => {
  const all: IFloor3dMepElement[] = [
    element({ subtype: 'elbow' }),
    element({ subtype: 'tee', pos: [3000, 3000, 500] }),
    element({ subtype: 'reducer' }),
    element({ type: 'valve', subtype: 'ball_valve' }),
    element({ type: 'valve', subtype: 'ball_valve', pos: [4000, 3000, 500] }),
    element({ type: 'sleeve', subtype: 'wall', length_mm: 260, outer_d_mm: 135 }),
    element({ subtype: 'elbow', layer: 'M-OV-T1' }),
  ];

  it('один InstancedMesh на пару (слой, вид), счётчик - число экземпляров', () => {
    const built = buildMepElements(all, COLORS, frame, 5);
    const meshes = instanced(built.group);
    // V1: sphere(2), reducer, box(2), sleeve; T1: sphere
    expect(meshes).toHaveLength(5);
    expect(meshes.map((mesh) => mesh.count).sort()).toEqual([1, 1, 1, 2, 2]);
    expect([...built.layers].sort()).toEqual(['M-OV-T1', 'M-VK-V1']);
    built.dispose();
  });

  it('гильза - открытый цилиндр; арматура темнее слоя; гильза цвета токена', () => {
    const built = buildMepElements(all, COLORS, frame, 5);
    const sleeve = instanced(built.group).find(
      (mesh) => (mesh.geometry as THREE.CylinderGeometry).parameters?.openEnded === true,
    );
    expect(sleeve).toBeDefined();
    expect((sleeve?.material as THREE.MeshStandardMaterial).color.getHex()).toBe(
      new THREE.Color(COLORS.sleeve).getHex(),
    );
    const base = new THREE.Color(COLORS.layers['M-VK-V1']);
    const dark = instanced(built.group).find((mesh) => mesh.geometry instanceof THREE.BoxGeometry);
    expect((dark?.material as THREE.MeshStandardMaterial).color.getHex()).toBe(
      base.clone().multiplyScalar(DARK_TONE_K).getHex(),
    );
    built.dispose();
  });

  it('видимость по слою и dispose', () => {
    const built = buildMepElements(all, COLORS, frame, 5);
    built.setLayerVisible('M-OV-T1', false);
    const visible = instanced(built.group).filter((mesh) => mesh.visible);
    expect(visible).toHaveLength(4);
    built.setLayerVisible('M-OV-T1', true);
    expect(instanced(built.group).every((mesh) => mesh.visible)).toBe(true);
    let disposed = 0;
    for (const mesh of instanced(built.group))
      mesh.addEventListener('dispose', () => (disposed += 1));
    built.dispose();
    expect(disposed).toBe(5);
    expect(built.group.children).toHaveLength(0);
  });
});

describe('индекс фасонин', () => {
  const lookup = createFittingLookup([
    element({ pos: [1000, 1000, 0] }),
    element({ type: 'valve', subtype: 'ball_valve', pos: [5000, 0, 0] }),
  ]);

  it('находит фасонину того же слоя рядом, арматуру и чужой слой - нет', () => {
    expect(lookup('M-VK-V1', 1010, 995, 0, 25)).toBe(true);
    expect(lookup('M-VK-V1', 1100, 1000, 0, 25)).toBe(false);
    expect(lookup('M-OV-T1', 1000, 1000, 0, 25)).toBe(false);
    expect(lookup('M-VK-V1', 5000, 0, 0, 25)).toBe(false);
    expect(lookup('M-VK-V1', 1190, 1000, 0, 250)).toBe(true);
  });
});
