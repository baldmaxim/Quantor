import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { buildBuildingPlan, floorKey } from '@/lib/cad/building3d-geometry';

import { buildBuildingCalcGroups, floorViewKey, floorsOfLayer, sceneShiftOf } from './building-calc-layer';
import { layer, polyline } from './fixtures';

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

const floor = (patch: Partial<CadBuilding3dFloorRead> = {}): CadBuilding3dFloorRead => ({
  job_id: 'j1',
  revision_id: 'r1',
  document_id: 'd1',
  page_index: 0,
  view: 0,
  label: '15 этаж',
  elevation_known: true,
  base_z_mm: 3000,
  floor_height_mm: 3000,
  floor_height_known: true,
  slab_thickness_mm: 200,
  slab_thickness_known: true,
  // Контур этажа уже в системе здания: вид сдвинут на offset_mm.
  outline: rect(5000, 7000, 15000, 13000),
  outline_source: 'slab',
  bbox: [5000, 7000, 15000, 13000],
  corps: null,
  section: null,
  group_key: 'g',
  group_label: 'Корпус',
  offset_mm: [5000, 7000],
  alignment: 'axes',
  alignment_axes: [],
  alignment_message: null,
  ...patch,
});

describe('слой «Расчёты» в 3D здания', () => {
  it('этажи расчёта - те, ключ вида которых есть у версии', () => {
    const floors = [floor(), floor({ page_index: 1 }), floor({ revision_id: 'r2' })];
    const picked = floorsOfLayer({ view_keys: ['r1:1:0', 'r2:0:0'] }, floors);
    expect(picked.map(floorViewKey)).toEqual(['r1:1:0', 'r2:0:0']);
  });

  it('сдвиг сцены берётся из плана: контур в мм и в метрах плана', () => {
    const plan = buildBuildingPlan([floor()]);
    const spec = plan?.floors[0];
    if (!plan || !spec) throw new Error('нет плана');
    // Центр здания (10000, 10000), отметка центра по высоте: (3000 - 200 + 6000) / 2 = 4400.
    const shift = sceneShiftOf(spec);
    expect(shift?.u).toBeCloseTo(-10);
    expect(shift?.v).toBeCloseTo(-10);
    expect(shift?.h).toBeCloseTo(-4.4);
  });

  it('геометрия встаёт на этаж: +offset_mm по плану, z + base_z_mm по высоте', () => {
    const plan = buildBuildingPlan([floor()]);
    if (!plan) throw new Error('нет плана');
    const line = polyline({ shape: null, dn_mm: null, pts: [[1000, 2000, 300], [3000, 2000, 300]] });
    const built = buildBuildingCalcGroups(plan, [
      { floorKey: floorKey(floor()), layer: layer({ polylines: [line], elements: [] }) },
    ]);
    const group = built.groups.get(floorKey(floor()));
    if (!group) throw new Error('нет группы этажа');
    const box = new THREE.Box3().setFromObject(group);
    // Вид (1000..3000, 2000) + (5000, 7000) = (6000..8000, 9000) мм здания; центр (10000, 10000).
    expect(box.min.x).toBeCloseTo(-4);
    expect(box.max.x).toBeCloseTo(-2);
    // Z сцены = -(y - cy) / 1000 = 1.
    expect(box.min.z).toBeCloseTo(1);
    // Высота: (3000 + 300 - 4400) / 1000 = -1.1 - чистый пол плюс 300 мм над ним в сцене.
    expect(box.min.y).toBeCloseTo(-1.1);
    built.dispose();
    expect(built.groups.size).toBe(0);
  });

  it('этаж без расчёта группы не получает', () => {
    const plan = buildBuildingPlan([floor(), floor({ page_index: 1, base_z_mm: 6000 })]);
    if (!plan) throw new Error('нет плана');
    const built = buildBuildingCalcGroups(plan, [
      { floorKey: floorKey(floor({ page_index: 1 })), layer: layer() },
    ]);
    expect([...built.groups.keys()]).toEqual([floorKey(floor({ page_index: 1 }))]);
    built.dispose();
  });
});
