import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { floor3dFixture, heightsFixture } from './floor3d-fixtures';
import { buildFloor3dPlan } from './floor3d-geometry';
import {
  ROUTES_RENDER_ORDER,
  buildFloor3dRoutes,
  routesBaseZMm,
  type IFloor3dRouteColors,
} from './floor3d-routes';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPickData } from './floor3d-scene';

const COLORS: IFloor3dRouteColors = {
  layers: { 'M-OV-T1': 'rgb(255, 0, 0)', 'M-VK-V1': 'rgb(0, 0, 255)' },
  fallback: 'rgb(9, 9, 9)',
};

const plan = buildFloor3dPlan(floor3dFixture());
const frame = { center: plan.center, baseZMm: 3000 };

const lines = (group: THREE.Group): THREE.Line[] =>
  group.children.filter((child): child is THREE.Line => child instanceof THREE.Line);

const vertices = (geometry: THREE.BufferGeometry): THREE.Vector3[] => {
  const position = geometry.getAttribute('position');
  return Array.from({ length: position.count }, (_, i) =>
    new THREE.Vector3(position.getX(i), position.getY(i), position.getZ(i)),
  );
};

const hasVertex = (all: readonly THREE.Vector3[], target: THREE.Vector3): boolean =>
  all.some((point) => point.distanceTo(target) < 1e-6);

describe('трассы в 3D-виде (без WebGL)', () => {
  it('точка трассы совпадает с углом призмы стены в той же точке плана на той же высоте', () => {
    // Стена w1: угол плана (0, 0) и (10000, 200); низ - отметка этажа 3000, верх - 5800 (z_rel 2800).
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    const wall = scene.pickables.find((mesh) => (mesh.userData.pick as IFloor3dPickData).category === 'masonry');
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
        { layer: 'M-OV-T1', pts: [[0, 0, 0], [1000, 0, 0]] },
        { layer: 'M-OV-T1', pts: [[0, 500, 0], [1000, 500, 0]] },
        { layer: 'M-VK-V1', pts: [[0, 900, 100], [1000, 900, 100]] },
        { layer: 'M-X', pts: [[0, 1200, 0], [1000, 1200, 0]] },
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
        { layer: 'M-OV-T1', pts: [[0, 0, 0], [1000, 0, 0]] },
        { layer: 'M-VK-V1', pts: [[0, 900, 100], [1000, 900, 100]] },
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
        { layer: 'M-OV-T1', pts: [[0, 0, 0], [1000, 0, 0]] },
        { layer: 'M-VK-V1', pts: [[0, 900, 100], [1000, 900, 100]] },
      ],
      COLORS,
      frame,
    );
    const disposed: string[] = [];
    for (const line of lines(routes.group)) {
      line.geometry.addEventListener('dispose', () => disposed.push('geometry'));
      (line.material as THREE.LineBasicMaterial).addEventListener('dispose', () => disposed.push('material'));
    }
    routes.dispose();
    expect(disposed.filter((kind) => kind === 'geometry')).toHaveLength(2);
    expect(disposed.filter((kind) => kind === 'material')).toHaveLength(2);
    expect(routes.group.children).toHaveLength(0);
  });
});

describe('чистый пол модели для трасс', () => {
  it('берёт отметку листа, а не верх плиты', () => {
    const model = floor3dFixture({ base_z_mm: 50800, heights: heightsFixture({ floor_elevation_mm: 50900 }) });
    expect(routesBaseZMm(model)).toBe(50900);
  });

  it('без отметки листа берёт базу модели', () => {
    const model = floor3dFixture({ base_z_mm: 0, heights: heightsFixture({ floor_elevation_mm: null }) });
    expect(routesBaseZMm(model)).toBe(0);
  });
});
