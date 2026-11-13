import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { buildViewerPlan } from './building-viewer-geometry';
import {
  GROUP_GAP_FACTOR,
  LABEL_LIFT_M,
  MIN_GROUP_GAP_M,
  buildAllGroupsPlan,
  groupGap,
  layoutGroupPlans,
} from './building-viewer-layout';

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
  label: '1 этаж',
  elevation_known: true,
  base_z_mm: 0,
  floor_height_mm: 3000,
  floor_height_known: true,
  slab_thickness_mm: 200,
  slab_thickness_known: true,
  outline: rect(0, 0, 10000, 6000),
  outline_source: 'slab',
  bbox: null,
  corps: null,
  section: null,
  group_key: 'a',
  group_label: 'К1',
  offset_mm: [0, 0],
  alignment: 'reference',
  alignment_axes: [],
  alignment_message: null,
  walls: [{ id: 'w1', kind: 'masonry', shell: rect(0, 0, 10000, 200) }],
  ...patch,
});

const group = (key: string, label: string, count = 1): CadBuilding3dGroupRead => ({
  key,
  label,
  floor_count: count,
  aligned_count: count,
});

describe('зазор между группами', () => {
  it('15% наибольшей ширины, но не меньше 10 м', () => {
    expect(GROUP_GAP_FACTOR).toBe(0.15);
    expect(groupGap([20, 40])).toBe(10);
    expect(groupGap([100, 40])).toBeCloseTo(15);
    expect(groupGap([])).toBe(MIN_GROUP_GAP_M);
  });
});

describe('раскладка групп «Весь объект»', () => {
  const floors = [
    floor({ job_id: 'a1', group_key: 'a', group_label: 'К1' }),
    // Вторая группа шире (20 м) и лежит в совсем других координатах DXF.
    floor({
      job_id: 'b1',
      group_key: 'b',
      group_label: 'К2',
      outline: rect(500000, 900000, 520000, 906000),
      walls: [{ id: 'w2', kind: 'monolith_wall', shell: rect(500000, 900000, 520000, 900200) }],
    }),
  ];
  const groups = [group('a', 'К1'), group('b', 'К2')];

  it('группы в ряд по X в порядке списка, зазор 10 м, центр раскладки в нуле', () => {
    const plan = buildAllGroupsPlan(floors, groups);
    if (plan === null) throw new Error('план не построен');
    const first = plan.floors.find((spec) => spec.key === 'a1:0:0');
    const second = plan.floors.find((spec) => spec.key === 'b1:0:0');
    const xs = (shell: readonly (readonly [number, number])[] | undefined): number[] =>
      (shell ?? []).map(([u]) => u);
    // Ширины 10 и 20 м, зазор max(10; 0,15·20) = 10 м: всего 40 м, от -20 до +20.
    expect(Math.min(...xs(first?.shell))).toBeCloseTo(-20);
    expect(Math.max(...xs(first?.shell))).toBeCloseTo(-10);
    expect(Math.min(...xs(second?.shell))).toBeCloseTo(0);
    expect(Math.max(...xs(second?.shell))).toBeCloseTo(20);
    expect(plan.size.width).toBeCloseTo(40);
    expect(plan.size.depth).toBeCloseTo(6);
  });

  it('стены сдвигаются вместе с контуром, идентификаторы сохраняются', () => {
    const plan = buildAllGroupsPlan(floors, groups);
    const second = plan?.floors.find((spec) => spec.key === 'b1:0:0');
    expect(second?.walls.map((wall) => wall.id)).toEqual(['w2']);
    expect(Math.min(...(second?.walls[0]?.shell ?? []).map(([u]) => u))).toBeCloseTo(0);
  });

  it('одна отметка - одна высота у разных групп; высоты разных групп не сдвигаются относительно друг друга', () => {
    const high = [
      floor({ job_id: 'a1', group_key: 'a' }),
      floor({ job_id: 'a2', group_key: 'a', base_z_mm: 3000 }),
      floor({ job_id: 'b1', group_key: 'b', base_z_mm: 3000, outline: rect(0, 0, 8000, 6000) }),
    ];
    const plan = buildAllGroupsPlan(high, groups);
    const top = (key: string): number | undefined => plan?.floors.find((spec) => spec.key === key)?.slabTop;
    expect(top('a2:0:0')).toBeCloseTo(top('b1:0:0') ?? NaN);
    expect((top('a2:0:0') ?? 0) - (top('a1:0:0') ?? 0)).toBeCloseTo(3);
  });

  it('подпись над верхним этажом группы со своим названием', () => {
    const plan = buildAllGroupsPlan(
      [floor({ job_id: 'a1', group_key: 'a' }), floor({ job_id: 'a2', group_key: 'a', base_z_mm: 3000 }), floors[1] as CadBuilding3dFloorRead],
      groups,
    );
    expect(plan?.labels.map((label) => label.text)).toEqual(['К1', 'К2']);
    const labelA = plan?.labels[0];
    const topA = plan?.floors.find((spec) => spec.key === 'a2:0:0');
    expect(labelA?.floorKey).toBe('a2:0:0');
    expect(labelA?.y).toBeCloseTo((topA?.volumeTop ?? 0) + LABEL_LIFT_M);
    expect(labelA?.x).toBeCloseTo(-15);
  });

  it('группа без этажей с отметкой пропускается; нет ни одной - плана нет', () => {
    const plan = buildAllGroupsPlan(floors, [group('a', 'К1'), group('c', 'К3'), group('b', 'К2')]);
    expect(plan?.labels.map((label) => label.key)).toEqual(['a', 'b']);
    expect(buildAllGroupsPlan([floor({ elevation_known: false })], groups)).toBeNull();
    expect(layoutGroupPlans([])).toBeNull();
  });

  it('план одного здания без подписей', () => {
    expect(buildViewerPlan([floor()])?.labels).toEqual([]);
  });
});
