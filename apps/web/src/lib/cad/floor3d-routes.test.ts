import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { floor3dFixture, heightsFixture } from './floor3d-fixtures';
import { buildFloor3dPlan } from './floor3d-geometry';
import {
  ROUTES_RENDER_ORDER,
  buildFloor3dRoutes,
  routesBaseZMm,
  type IFloor3dRouteColors,
  type IFloor3dRoutePolyline,
} from './floor3d-routes';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPickData } from './floor3d-scene';

const COLORS: IFloor3dRouteColors = {
  layers: { 'M-OV-T1': 'rgb(255, 0, 0)', 'M-VK-V1': 'rgb(0, 0, 255)' },
  fallback: 'rgb(9, 9, 9)',
  insulation: 'rgb(220, 200, 120)',
  sleeve: 'rgb(120, 130, 140)',
  accent: 'rgb(255, 0, 255)',
};

const plan = buildFloor3dPlan(floor3dFixture());
const frame = { center: plan.center, baseZMm: 3000 };

const lines = (group: THREE.Group): THREE.Line[] =>
  group.children.filter((child): child is THREE.Line => child instanceof THREE.Line);

const vertices = (geometry: THREE.BufferGeometry): THREE.Vector3[] => {
  const position = geometry.getAttribute('position');
  return Array.from(
    { length: position.count },
    (_, i) => new THREE.Vector3(position.getX(i), position.getY(i), position.getZ(i)),
  );
};

const hasVertex = (all: readonly THREE.Vector3[], target: THREE.Vector3): boolean =>
  all.some((point) => point.distanceTo(target) < 1e-6);

describe('трассы в 3D-виде (без WebGL)', () => {
  it('точка трассы совпадает с углом призмы стены в той же точке плана на той же высоте', () => {
    // Стена w1: угол плана (0, 0) и (10000, 200); низ - отметка этажа 3000, верх - 5800 (z_rel 2800).
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    const wall = scene.pickables.find(
      (mesh) => (mesh.userData.pick as IFloor3dPickData).category === 'masonry',
    );
    expect(wall).toBeDefined();
    const corners = vertices((wall as THREE.Mesh).geometry);
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 0, 0],
            [10000, 200, 2800],
          ],
        },
      ],
      COLORS,
      frame,
    );
    const [first, second] = vertices(lines(routes.group)[0]!.geometry);
    expect(hasVertex(corners, first!)).toBe(true);
    expect(hasVertex(corners, second!)).toBe(true);
    routes.dispose();
    scene.dispose();
  });

  it('одна линия на полилинию, один материал на слой, цвета по слою и нейтральный запасной', () => {
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 0, 0],
            [1000, 0, 0],
          ],
        },
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 500, 0],
            [1000, 500, 0],
          ],
        },
        {
          layer: 'M-VK-V1',
          pts: [
            [0, 900, 100],
            [1000, 900, 100],
          ],
        },
        {
          layer: 'M-X',
          pts: [
            [0, 1200, 0],
            [1000, 1200, 0],
          ],
        },
        { layer: 'M-OV-T1', pts: [[5, 5, 0]] },
      ],
      COLORS,
      frame,
    );
    const all = lines(routes.group);
    expect(all).toHaveLength(4);
    const material = (index: number) => all[index]!.material as THREE.LineBasicMaterial;
    expect(material(0)).toBe(material(1));
    expect(material(0)).not.toBe(material(2));
    expect(material(0).color.getHex()).toBe(new THREE.Color(COLORS.layers['M-OV-T1']).getHex());
    expect(material(3).color.getHex()).toBe(new THREE.Color(COLORS.fallback).getHex());
    expect(material(0).depthTest).toBe(true);
    expect(all.every((line) => line.renderOrder === ROUTES_RENDER_ORDER)).toBe(true);
    routes.dispose();
  });

  it('скрытие слоя и всех трасс', () => {
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 0, 0],
            [1000, 0, 0],
          ],
        },
        {
          layer: 'M-VK-V1',
          pts: [
            [0, 900, 100],
            [1000, 900, 100],
          ],
        },
      ],
      COLORS,
      frame,
    );
    const [heating, water] = lines(routes.group);
    routes.setLayerVisible('M-OV-T1', false);
    expect(heating!.visible).toBe(false);
    expect(water!.visible).toBe(true);
    routes.setLayerVisible('M-OV-T1', true);
    expect(heating!.visible).toBe(true);
    routes.setAllVisible(false);
    expect(routes.group.visible).toBe(false);
    routes.dispose();
  });

  it('dispose освобождает геометрии и материалы', () => {
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 0, 0],
            [1000, 0, 0],
          ],
        },
        {
          layer: 'M-VK-V1',
          pts: [
            [0, 900, 100],
            [1000, 900, 100],
          ],
        },
      ],
      COLORS,
      frame,
    );
    const disposed: string[] = [];
    for (const line of lines(routes.group)) {
      line.geometry.addEventListener('dispose', () => disposed.push('geometry'));
      (line.material as THREE.LineBasicMaterial).addEventListener('dispose', () =>
        disposed.push('material'),
      );
    }
    routes.dispose();
    expect(disposed.filter((kind) => kind === 'geometry')).toHaveLength(2);
    expect(disposed.filter((kind) => kind === 'material')).toHaveLength(2);
    expect(routes.group.children).toHaveLength(0);
  });
});

const meshes = (group: THREE.Group): THREE.Mesh[] =>
  group.children.filter(
    (child): child is THREE.Mesh =>
      child instanceof THREE.Mesh && !(child instanceof THREE.InstancedMesh),
  );

const boundsOf = (mesh: THREE.Mesh): THREE.Box3 => {
  mesh.geometry.computeBoundingBox();
  return mesh.geometry.boundingBox as THREE.Box3;
};

describe('объёмные трассы (cad_mep_routes3d.v2)', () => {
  const pipe = (patch: Partial<IFloor3dRoutePolyline> = {}): IFloor3dRoutePolyline => ({
    layer: 'M-VK-V1',
    pts: [
      [0, 0, 0],
      [0, 0, 2000],
    ],
    shape: 'round',
    dn_mm: 100,
    insulation_mm: 0,
    ...patch,
  });

  it('полилиния без shape (файл v1) или короб без размеров остаётся линией; круглая без Ø - труба', () => {
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-T1',
          pts: [
            [0, 0, 0],
            [1000, 0, 0],
          ],
        },
        pipe({ shape: 'rect', w_mm: 400, h_mm: null }),
      ],
      COLORS,
      frame,
    );
    expect(lines(routes.group)).toHaveLength(2);
    expect(meshes(routes.group)).toHaveLength(0);
    routes.dispose();
  });

  it('круглая без Ø рисуется трубой условного Ø 20 мм', () => {
    const routes = buildFloor3dRoutes([pipe({ dn_mm: null })], COLORS, frame);
    expect(lines(routes.group)).toHaveLength(0);
    const [mesh] = meshes(routes.group);
    const box = new THREE.Box3().setFromObject(mesh as THREE.Mesh);
    expect(box.getSize(new THREE.Vector3()).x).toBeCloseTo(0.02, 2);
    routes.dispose();
  });

  it('труба - цилиндр по Ø от чистого пола; участки слоя слиты в один Mesh цвета слоя', () => {
    const routes = buildFloor3dRoutes(
      [
        pipe(),
        pipe({
          pts: [
            [500, 0, 100],
            [1500, 0, 100],
          ],
        }),
      ],
      COLORS,
      frame,
    );
    const all = meshes(routes.group);
    expect(all).toHaveLength(1);
    const material = all[0]!.material as THREE.MeshStandardMaterial;
    expect(material).toBeInstanceOf(THREE.MeshStandardMaterial);
    expect(material.color.getHex()).toBe(new THREE.Color(COLORS.layers['M-VK-V1']).getHex());
    const box = boundsOf(all[0]!);
    // Вертикальный стояк: низ - baseZ (3000 мм) минус центр модели, радиус 50 мм.
    expect(box.min.y).toBeCloseTo((3000 - plan.center.z) / 1000, 6);
    expect(box.max.y).toBeCloseTo((5000 - plan.center.z) / 1000, 6);
    routes.dispose();
  });

  it('оболочка изоляции - только при insulation_mm > 0, полупрозрачная, радиус DN/2 + изоляция', () => {
    const bare = buildFloor3dRoutes([pipe()], COLORS, frame);
    expect(meshes(bare.group)).toHaveLength(1);
    bare.dispose();

    const routes = buildFloor3dRoutes([pipe({ insulation_mm: 20 })], COLORS, frame);
    const [solid, shell] = meshes(routes.group);
    expect(solid).toBeDefined();
    const material = shell!.material as THREE.MeshStandardMaterial;
    expect(material.transparent).toBe(true);
    expect(material.opacity).toBeCloseTo(0.35, 6);
    expect(material.depthWrite).toBe(false);
    expect(material.color.getHex()).toBe(new THREE.Color(COLORS.insulation).getHex());
    const size = boundsOf(shell!).getSize(new THREE.Vector3());
    const plainSize = boundsOf(solid!).getSize(new THREE.Vector3());
    expect(size.x / plainSize.x).toBeCloseTo(0.14 / 0.1, 2);
    routes.dispose();
  });

  it('воздуховод - короб w x h; вертикальный участок: w по X, h по Z сцены', () => {
    const routes = buildFloor3dRoutes(
      [pipe({ shape: 'rect', dn_mm: null, w_mm: 400, h_mm: 200 })],
      COLORS,
      frame,
    );
    const size = boundsOf(meshes(routes.group)[0]!).getSize(new THREE.Vector3());
    expect([size.x, size.y, size.z]).toEqual([0.4, 2, 0.2].map((n) => expect.closeTo(n, 6)));
    routes.dispose();
  });

  it('элементы идут вместе с трассами: слои, скрытие по слою, dispose', () => {
    const routes = buildFloor3dRoutes([pipe()], COLORS, frame, [
      {
        type: 'valve',
        subtype: 'ball_valve',
        layer: 'M-OV-T1',
        pos: [0, 0, 0],
        axis: [0, 0, 1000],
        dn_mm: 25,
      },
      {
        type: 'fitting',
        subtype: 'elbow',
        layer: 'M-VK-V1',
        pos: [0, 0, 500],
        axis: [1000, 0, 0],
        dn_mm: 100,
      },
    ]);
    expect([...routes.layers].sort()).toEqual(['M-OV-T1', 'M-VK-V1']);
    const instances = (): THREE.InstancedMesh[] => {
      const found: THREE.InstancedMesh[] = [];
      routes.group.traverse((object) => {
        if (object instanceof THREE.InstancedMesh) found.push(object);
      });
      return found;
    };
    expect(instances()).toHaveLength(2);
    routes.setLayerVisible('M-OV-T1', false);
    expect(instances().filter((mesh) => mesh.visible)).toHaveLength(1);
    expect(meshes(routes.group)[0]!.visible).toBe(true);
    routes.setLayerVisible('M-VK-V1', false);
    expect(meshes(routes.group)[0]!.visible).toBe(false);
    expect(instances().every((mesh) => !mesh.visible)).toBe(true);
    routes.dispose();
    expect(routes.group.children).toHaveLength(0);
  });

  it('фасонина в вершине убирает сферу стыка трубы', () => {
    const bent: IFloor3dRoutePolyline = pipe({
      pts: [
        [0, 0, 0],
        [1000, 0, 0],
        [1000, 0, 1000],
      ],
    });
    const count = (elements: Parameters<typeof buildFloor3dRoutes>[3]): number => {
      const routes = buildFloor3dRoutes([bent], COLORS, frame, elements);
      const total = meshes(routes.group)[0]!.geometry.getAttribute('position').count;
      routes.dispose();
      return total;
    };
    const withoutFitting = count([]);
    const withFitting = count([
      {
        type: 'fitting',
        subtype: 'elbow',
        layer: 'M-VK-V1',
        pos: [1000, 0, 0],
        axis: [1000, 0, 0],
        dn_mm: 100,
      },
    ]);
    expect(withFitting).toBeLessThan(withoutFitting);
  });
});

describe('чистый пол модели для трасс', () => {
  it('берёт отметку листа, а не верх плиты', () => {
    const model = floor3dFixture({
      base_z_mm: 50800,
      heights: heightsFixture({ floor_elevation_mm: 50900 }),
    });
    expect(routesBaseZMm(model)).toBe(50900);
  });

  it('без отметки листа берёт базу модели', () => {
    const model = floor3dFixture({
      base_z_mm: 0,
      heights: heightsFixture({ floor_elevation_mm: null }),
    });
    expect(routesBaseZMm(model)).toBe(0);
  });
});
