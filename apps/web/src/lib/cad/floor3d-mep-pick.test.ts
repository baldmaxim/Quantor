import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { hitScene } from './floor3d-hit';
import type { IFloor3dMepElement } from './floor3d-mep-elements';
import { MEP_PICK_KEY, mepPickOf, sameMepPick } from './floor3d-mep-pick';
import {
  buildFloor3dRoutes,
  type IFloor3dRouteColors,
  type IFloor3dRoutePolyline,
} from './floor3d-routes';

const COLORS: IFloor3dRouteColors = {
  layers: { 'M-VK-V1': 'rgb(0, 0, 255)', 'M-OV-T1': 'rgb(255, 0, 0)' },
  fallback: 'rgb(9, 9, 9)',
  insulation: 'rgb(220, 200, 120)',
  sleeve: 'rgb(120, 130, 140)',
  accent: 'rgb(255, 0, 255)',
};
const frame = { center: { x: 0, y: 0, z: 0 }, baseZMm: 0 };

const pipe = (y: number, patch: Partial<IFloor3dRoutePolyline> = {}): IFloor3dRoutePolyline => ({
  layer: 'M-VK-V1',
  pts: [
    [0, y, 500],
    [1000, y, 500],
  ],
  shape: 'round',
  dn_mm: 100,
  insulation_mm: 0,
  ...patch,
});

const terminal = (y: number, patch: Partial<IFloor3dMepElement> = {}): IFloor3dMepElement => ({
  type: 'terminal',
  subtype: 'wc',
  layer: 'M-VK-V1',
  pos: [500, y, 400],
  axis: [0, 0, 1000],
  w_mm: 360,
  length_mm: 600,
  h_mm: 800,
  ...patch,
});

/** Луч сверху вниз над точкой плана (x, y в мм DXF): сцена X = x, Z = -y. */
const rayDown = (xMm: number, yMm: number): THREE.Raycaster => {
  const raycaster = new THREE.Raycaster();
  raycaster.set(new THREE.Vector3(xMm / 1000, 10, -yMm / 1000), new THREE.Vector3(0, -1, 0));
  return raycaster;
};

describe('выбор трасс кликом', () => {
  it('слитый меш слоя находит полилинию по треугольнику луча', () => {
    const routes = buildFloor3dRoutes([pipe(0), pipe(2000), pipe(4000, { layer: 'M-OV-T1' })], COLORS, frame);
    expect(routes.pickables).toHaveLength(2);
    expect(hitScene(rayDown(500, 0), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'route', index: 0 } });
    expect(hitScene(rayDown(500, 2000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'route', index: 1 } });
    expect(hitScene(rayDown(500, 4000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'route', index: 2 } });
    expect(hitScene(rayDown(500, 3000), null, routes)).toBeNull();
    routes.dispose();
  });

  it('индекс - номер полилинии в файле, даже если предыдущие без тела', () => {
    const empty: IFloor3dRoutePolyline = { layer: 'M-VK-V1', pts: [[0, 0, 0]], shape: 'round', dn_mm: 50 };
    const line: IFloor3dRoutePolyline = { layer: 'M-VK-V1', pts: [[0, 500, 0], [10, 500, 0]] };
    const routes = buildFloor3dRoutes([empty, line, pipe(2000)], COLORS, frame);
    expect(hitScene(rayDown(500, 2000), null, routes)?.kind).toBe('mep');
    expect(hitScene(rayDown(500, 2000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'route', index: 2 } });
    routes.dispose();
  });

  it('оболочка изоляции не цель: клик попадает в трубу, линии v1 не выбираются', () => {
    const routes = buildFloor3dRoutes(
      [pipe(0, { insulation_mm: 30 }), { layer: 'M-VK-V1', pts: [[0, 1000, 500], [1000, 1000, 500]] }],
      COLORS,
      frame,
    );
    const transparent = routes.pickables.filter(
      (object) => object instanceof THREE.Mesh && (object.material as THREE.Material).transparent,
    );
    expect(transparent).toHaveLength(0);
    expect(hitScene(rayDown(500, 0), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'route', index: 0 } });
    expect(hitScene(rayDown(500, 1000), null, routes)).toBeNull();
    routes.dispose();
  });

  it('скрытый слой и скрытая группа трасс в выбор не входят', () => {
    const routes = buildFloor3dRoutes([pipe(0)], COLORS, frame, [terminal(2000)]);
    routes.setLayerVisible('M-VK-V1', false);
    expect(hitScene(rayDown(500, 0), null, routes)).toBeNull();
    expect(hitScene(rayDown(500, 2000), null, routes)).toBeNull();
    routes.setLayerVisible('M-VK-V1', true);
    expect(hitScene(rayDown(500, 0), null, routes)?.kind).toBe('mep');
    routes.setAllVisible(false);
    expect(hitScene(rayDown(500, 0), null, routes)).toBeNull();
    expect(hitScene(rayDown(500, 2000), null, routes)).toBeNull();
    routes.dispose();
  });
});

describe('выбор элементов ВИС кликом', () => {
  it('экземпляр InstancedMesh -> индекс элемента в файле', () => {
    const elements = [
      { ...terminal(0), type: 'valve' as const, subtype: 'ball_valve', dn_mm: 50, pos: [5000, 5000, 400] },
      terminal(0),
      terminal(2000, { subtype: 'sprinkler', dn_mm: 15, h_mm: 50, w_mm: null, length_mm: null }),
      terminal(4000, { layer: 'M-SAN-WC' }),
    ];
    const routes = buildFloor3dRoutes([], COLORS, frame, elements);
    expect(hitScene(rayDown(500, 0), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'element', index: 1 } });
    expect(hitScene(rayDown(500, 2000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'element', index: 2 } });
    expect(hitScene(rayDown(500, 4000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'element', index: 3 } });
    expect(hitScene(rayDown(5000, 5000), null, routes)).toEqual({ kind: 'mep', pick: { kind: 'element', index: 0 } });
    routes.dispose();
  });

  it('mepPickOf: меш без карты и выход за границы - null', () => {
    const plain = new THREE.Mesh();
    expect(mepPickOf({ object: plain, faceIndex: 0, instanceId: 0 })).toBeNull();
    const routes = buildFloor3dRoutes([pipe(0)], COLORS, frame);
    const mesh = routes.pickables[0] as THREE.Mesh;
    expect(mesh.userData[MEP_PICK_KEY]).toBeDefined();
    expect(mepPickOf({ object: mesh, faceIndex: 99999 })).toBeNull();
    expect(mepPickOf({ object: mesh, faceIndex: undefined })).toBeNull();
    routes.dispose();
  });

  it('sameMepPick сравнивает вид и индекс', () => {
    expect(sameMepPick({ kind: 'route', index: 1 }, { kind: 'route', index: 1 })).toBe(true);
    expect(sameMepPick({ kind: 'route', index: 1 }, { kind: 'element', index: 1 })).toBe(false);
    expect(sameMepPick({ kind: 'route', index: 1 }, null)).toBe(false);
  });
});

describe('выделение выбранной трассы или элемента', () => {
  const overlayOf = (group: THREE.Group, before: number): THREE.Group | undefined =>
    group.children.length > before ? (group.children[group.children.length - 1] as THREE.Group) : undefined;

  it('трасса: оверлей из заливки и контура, снимается и освобождается', () => {
    const routes = buildFloor3dRoutes([pipe(0)], COLORS, frame);
    const before = routes.group.children.length;
    routes.setHighlight({ kind: 'route', index: 0 });
    const overlay = overlayOf(routes.group, before);
    expect(overlay).toBeDefined();
    const [fill, edges] = (overlay as THREE.Group).children;
    expect(fill).toBeInstanceOf(THREE.Mesh);
    expect(edges).toBeInstanceOf(THREE.LineSegments);
    expect(((fill as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHex()).toBe(
      new THREE.Color(COLORS.accent).getHex(),
    );
    routes.setHighlight({ kind: 'route', index: 0 });
    expect(routes.group.children.length).toBe(before + 1);
    routes.setHighlight(null);
    expect(routes.group.children.length).toBe(before);
    routes.setHighlight({ kind: 'route', index: 99 });
    expect(routes.group.children.length).toBe(before);
    routes.dispose();
  });

  it('элемент: оверлей по его телу; скрытие слоя прячет оверлей, показ возвращает', () => {
    const routes = buildFloor3dRoutes([pipe(0)], COLORS, frame, [terminal(2000)]);
    const before = routes.group.children.length;
    routes.setHighlight({ kind: 'element', index: 0 });
    const overlay = overlayOf(routes.group, before) as THREE.Group;
    expect(overlay.visible).toBe(true);
    routes.setLayerVisible('M-VK-V1', false);
    expect(overlay.visible).toBe(false);
    routes.setLayerVisible('M-VK-V1', true);
    expect(overlay.visible).toBe(true);
    routes.dispose();
    expect(routes.group.children).toHaveLength(0);
  });

  it('выбор в уже скрытом слое создаёт скрытый оверлей', () => {
    const routes = buildFloor3dRoutes([pipe(0)], COLORS, frame);
    routes.setLayerVisible('M-VK-V1', false);
    const before = routes.group.children.length;
    routes.setHighlight({ kind: 'route', index: 0 });
    expect((overlayOf(routes.group, before) as THREE.Group).visible).toBe(false);
    routes.dispose();
  });
});
