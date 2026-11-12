import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  alignmentNote,
  buildBuildingPlan,
  cleanOutline,
  describeFloor,
  filterFloorsByGroup,
  floorKey,
  formatElevation,
  resolveGroupKey,
  splitFloors,
} from './building3d-geometry';

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
  bbox: [0, 0, 10000, 6000],
  corps: null,
  section: null,
  group_key: 'none',
  group_label: 'Корпус не указан',
  offset_mm: [0, 0],
  alignment: 'reference',
  alignment_axes: [],
  alignment_message: null,
  ...patch,
});

describe('отметка и подпись этажа', () => {
  it('форматирует отметку в метрах со знаком', () => {
    expect(formatElevation(3000)).toBe('+3.000');
    expect(formatElevation(-3200)).toBe('-3.200');
    expect(formatElevation(0)).toBe('0.000');
  });

  it('помечает типовую высоту и неизвестную отметку', () => {
    expect(describeFloor(floor({ base_z_mm: 3000 }))).toBe('1 этаж, +3.000');
    expect(describeFloor(floor({ base_z_mm: 3000, floor_height_known: false }))).toBe(
      '1 этаж, +3.000, высота типовая',
    );
    expect(describeFloor(floor({ elevation_known: false }))).toBe('1 этаж, отметка не определена');
  });
});

describe('контур', () => {
  it('убирает замыкающую точку и мусор', () => {
    const closed = [...rect(0, 0, 1, 1), [0, 0]];
    expect(cleanOutline(closed)).toHaveLength(4);
    expect(cleanOutline([[0, 0], [1, Number.NaN], [2, 2]])).toBeNull();
    expect(cleanOutline([[0, 0], [1, 1]])).toBeNull();
  });
});

describe('список этажей', () => {
  it('сверху вниз по отметке, без отметки - отдельно', () => {
    const list = splitFloors([
      floor({ job_id: 'a', label: '1', base_z_mm: 0 }),
      floor({ job_id: 'b', label: '2', base_z_mm: 3000 }),
      floor({ job_id: 'c', label: 'Кровля', elevation_known: false }),
    ]);
    expect(list.known.map((item) => item.job_id)).toEqual(['b', 'a']);
    expect(list.unknown.map((item) => item.job_id)).toEqual(['c']);
  });
});

describe('план здания', () => {
  it('строит призмы: плита под отметкой, объём над ней, общий центр', () => {
    const plan = buildBuildingPlan([
      floor({ job_id: 'a', base_z_mm: 0, outline: rect(0, 0, 10000, 6000) }),
      floor({ job_id: 'b', base_z_mm: 3000, outline: rect(0, 0, 10000, 6000) }),
    ]);
    expect(plan).not.toBeNull();
    if (plan === null) return;
    // Габарит по высоте: низ плиты нижнего (-200) .. верх объёма верхнего (6000).
    expect(plan.size).toEqual({ width: 10, depth: 6, height: 6.2 });
    expect(plan.center).toEqual({ x: 5000, y: 3000, z: 2900 });
    const [top, bottom] = plan.floors;
    expect(top?.floor.job_id).toBe('b');
    expect(top?.slabTop).toBeCloseTo(0.1);
    expect(top?.slabBottom).toBeCloseTo(-0.1);
    expect(top?.volumeTop).toBeCloseTo(3.1);
    expect(bottom?.slabTop).toBeCloseTo(-2.9);
    expect(top?.shell[0]).toEqual([-5, -3]);
  });

  it('не строит этажи без отметки и без контура', () => {
    const plan = buildBuildingPlan([
      floor({ job_id: 'a' }),
      floor({ job_id: 'b', elevation_known: false }),
      floor({ job_id: 'c', outline: [] }),
    ]);
    expect(plan?.floors.map((item) => item.floor.job_id)).toEqual(['a']);
  });

  it('пусто, если строить нечего', () => {
    expect(buildBuildingPlan([])).toBeNull();
    expect(buildBuildingPlan([floor({ elevation_known: false })])).toBeNull();
  });

  it('ключ этажа - задание, страница и вид', () => {
    expect(floorKey(floor({ job_id: 'x', page_index: 3, view: 2 }))).toBe('x:3:2');
  });
});

describe('здания и совмещение', () => {
  const a1 = floor({ job_id: 'a1', group_key: 'k2' });
  const a2 = floor({ job_id: 'a2', group_key: 'k2', base_z_mm: 3000 });
  const b1 = floor({
    job_id: 'b1',
    group_key: 'k10',
    outline: rect(50000, 50000, 60000, 56000),
    bbox: [50000, 50000, 60000, 56000],
  });

  it('фильтрует этажи по зданию; без ключа - все', () => {
    expect(filterFloorsByGroup([a1, b1, a2], 'k2').map((f) => f.job_id)).toEqual(['a1', 'a2']);
    expect(filterFloorsByGroup([a1, b1], 'k10').map((f) => f.job_id)).toEqual(['b1']);
    expect(filterFloorsByGroup([a1, b1], null)).toHaveLength(2);
    expect(filterFloorsByGroup([a1], 'нет')).toEqual([]);
  });

  it('центр и габарит считаются по выбранному зданию, а не по всем', () => {
    const own = buildBuildingPlan(filterFloorsByGroup([a1, a2, b1], 'k2'));
    expect(own?.center.x).toBe(5000);
    expect(own?.size.width).toBe(10);
    expect(buildBuildingPlan([a1, a2, b1])?.size.width).toBe(60);
  });

  it('действующее здание: выбранное, иначе первое, групп нет - null', () => {
    const groups = [
      { key: 'k2', label: 'Корп. 2', floor_count: 2, aligned_count: 2 },
      { key: 'k10', label: 'Корп. 10', floor_count: 1, aligned_count: 0 },
    ];
    expect(resolveGroupKey(groups, null)).toBe('k2');
    expect(resolveGroupKey(groups, 'k10')).toBe('k10');
    expect(resolveGroupKey(groups, 'исчезло')).toBe('k2');
    expect(resolveGroupKey([], 'k2')).toBeNull();
  });

  it('действующее здание: группа открытого листа вместо первой, ручной выбор главнее', () => {
    const groups = [
      { key: 'k2', label: 'Корп. 2', floor_count: 2, aligned_count: 2 },
      { key: 'k10', label: 'Корп. 10', floor_count: 1, aligned_count: 0 },
    ];
    expect(resolveGroupKey(groups, null, 'k10')).toBe('k10');
    expect(resolveGroupKey(groups, 'k2', 'k10')).toBe('k2');
    expect(resolveGroupKey(groups, 'исчезло', 'k10')).toBe('k10');
    expect(resolveGroupKey(groups, null, 'нет')).toBe('k2');
  });

  it('пометка совмещения: «не совмещён» только в здании из нескольких этажей', () => {
    const none = floor({ alignment: 'none', alignment_message: 'оси не распознаны' });
    expect(alignmentNote(none, 2)).toEqual({
      text: 'не совмещён по осям',
      title: 'оси не распознаны',
      warn: true,
    });
    expect(alignmentNote(none, 1)).toBeNull();
    expect(alignmentNote(floor({ alignment: 'reference' }), 3)).toBeNull();
  });

  it('пометка совмещения по осям сокращает длинный список', () => {
    const axes = floor({ alignment: 'axes', alignment_axes: ['1', '2', '3', '4', '5', '6'] });
    expect(alignmentNote(axes, 2)).toEqual({
      text: 'по осям 1, 2, 3, 4 +2',
      title: 'Совмещён по осям: 1, 2, 3, 4, 5, 6',
      warn: false,
    });
  });
});
