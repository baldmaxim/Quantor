import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { buildViewerPlan } from './building-viewer-geometry';
import {
  GROUP_GAP_FACTOR,
  LABEL_LIFT_M,
  MIN_GROUP_GAP_M,
  MIN_LOST_GAP_M,
  NOT_PLACED_NOTE,
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

const group = (
  key: string,
  label: string,
  count = 1,
  placement: CadBuilding3dGroupRead['placement'] = 'none',
): CadBuilding3dGroupRead => ({
  key,
  label,
  floor_count: count,
  aligned_count: count,
  placement,
  site_offset_mm: [0, 0],
  placement_axes: [],
  placement_anchor: null,
  placement_message: null,
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

describe('группы, поставленные на объект по осям', () => {
  // Паркинг (опора) 40×30 м внизу, над ним два корпуса на своих местах в системе объекта, третий не поставлен.
  const floors = [
    floor({ job_id: 'p1', group_key: 'p', group_label: 'Паркинг', base_z_mm: -4000, floor_height_mm: 4000, outline: rect(0, 0, 40000, 30000) }),
    floor({ job_id: 'k1', group_key: 'k1', group_label: 'К1', outline: rect(2000, 2000, 12000, 8000) }),
    floor({ job_id: 'k2', group_key: 'k2', group_label: 'К2', outline: rect(25000, 20000, 35000, 26000) }),
    floor({ job_id: 'k3', group_key: 'k3', group_label: 'К3', outline: rect(900000, 900000, 910000, 906000) }),
  ];
  const groups = [
    group('k1', 'К1', 1, 'axes'),
    group('k2', 'К2', 1, 'axes'),
    group('k3', 'К3'),
    group('p', 'Паркинг', 1, 'reference'),
  ];
  const span = (shell: readonly (readonly [number, number])[] | undefined, axis: 0 | 1): [number, number] => {
    const values = (shell ?? []).map((point) => point[axis]);
    return [Math.min(...values), Math.max(...values)];
  };

  it('поставленные группы сохраняют взаимное положение из системы объекта', () => {
    const plan = buildAllGroupsPlan(floors, groups);
    const shell = (key: string) => plan?.floors.find((spec) => spec.key === key)?.shell;
    const [parkingMinX] = span(shell('p1:0:0'), 0);
    const [parkingMinY] = span(shell('p1:0:0'), 1);
    expect(span(shell('k1:0:0'), 0)[0] - parkingMinX).toBeCloseTo(2);
    expect(span(shell('k1:0:0'), 1)[0] - parkingMinY).toBeCloseTo(2);
    expect(span(shell('k2:0:0'), 0)[0] - parkingMinX).toBeCloseTo(25);
    expect(span(shell('k2:0:0'), 1)[0] - parkingMinY).toBeCloseTo(20);
  });

  it('не поставленная группа - отдельным блоком за поставленными, полупрозрачная и с пометкой', () => {
    const plan = buildAllGroupsPlan(floors, groups);
    const spec = (key: string) => plan?.floors.find((item) => item.key === key);
    // Не в ряд с поставленными: по X - по центру, по глубине - за блоком поставленных с зазором.
    const [lostMinX, lostMaxX] = span(spec('k3:0:0')?.shell, 0);
    expect((lostMinX + lostMaxX) / 2).toBeCloseTo(0);
    const placedBack = span(spec('p1:0:0')?.shell, 1)[1];
    expect(span(spec('k3:0:0')?.shell, 1)[0] - placedBack).toBeCloseTo(MIN_LOST_GAP_M);
    expect(plan?.size.width).toBeCloseTo(40);
    expect(plan?.size.depth).toBeCloseTo(30 + MIN_LOST_GAP_M + 6);
    expect(spec('k3:0:0')?.ghost).toBe(true);
    expect([spec('p1:0:0')?.ghost, spec('k1:0:0')?.ghost]).toEqual([undefined, undefined]);
    const label = plan?.labels.find((item) => item.key === 'k3');
    expect(label?.note).toBe(NOT_PLACED_NOTE);
    // Подпись стоит над своей группой: ось v уходит в сцене в -Z.
    const [lostMinV, lostMaxV] = span(spec('k3:0:0')?.shell, 1);
    expect(label?.z).toBeCloseTo(-(lostMinV + lostMaxV) / 2);
    expect(plan?.labels.find((item) => item.key === 'k1')?.note).toBeUndefined();
  });

  it('подпись каждой поставленной группы - над её верхним этажом по центру её контура', () => {
    const plan = buildAllGroupsPlan(floors, groups);
    expect(plan?.labels.map((label) => label.key)).toEqual(['k1', 'k2', 'p', 'k3']);
    const shellK2 = plan?.floors.find((spec) => spec.key === 'k2:0:0');
    const labelK2 = plan?.labels.find((label) => label.key === 'k2');
    const [minU, maxU] = span(shellK2?.shell, 0);
    const [minV, maxV] = span(shellK2?.shell, 1);
    expect(labelK2?.x).toBeCloseTo((minU + maxU) / 2);
    expect(labelK2?.z).toBeCloseTo(-(minV + maxV) / 2);
    expect(labelK2?.y).toBeCloseTo((shellK2?.volumeTop ?? 0) + LABEL_LIFT_M);
  });

  it('одна опора без поставленных групп: опора на месте, остальные - блоком «не поставлен»', () => {
    const only = [group('k1', 'К1'), group('p', 'Паркинг', 1, 'reference')];
    const plan = buildAllGroupsPlan([floors[1], floors[0]] as CadBuilding3dFloorRead[], only);
    expect(plan?.labels.map((label) => [label.key, label.note])).toEqual([
      ['p', undefined],
      ['k1', NOT_PLACED_NOTE],
    ]);
    expect(plan?.floors.find((spec) => spec.key === 'k1:0:0')?.ghost).toBe(true);
    expect(plan?.size.width).toBeCloseTo(40);
  });

  it('ответ без постановки (ни одной поставленной группы) - все группы в ряд, без пометок', () => {
    const plan = buildAllGroupsPlan(floors, groups.map((item) => ({ ...item, placement: 'none' as const })));
    expect(plan?.labels.every((label) => label.note === undefined)).toBe(true);
    expect(plan?.floors.every((spec) => spec.ghost === undefined)).toBe(true);
  });
});
