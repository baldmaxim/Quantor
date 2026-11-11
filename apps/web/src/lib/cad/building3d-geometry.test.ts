import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  buildBuildingPlan,
  cleanOutline,
  describeFloor,
  floorKey,
  formatElevation,
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
