import type { CadBuilding3dFloorRead, CadBuilding3dWallRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  buildViewerPlan,
  countWalls,
  explodeOffsets,
  extrudeShell,
  fitDistance,
  mergeShells,
  viewerBounds,
  wallHeightMm,
  wallMaterialOf,
} from './building-viewer-geometry';

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

const wall = (kind: CadBuilding3dWallRead['kind'], shell: number[][]): CadBuilding3dWallRead => ({ kind, shell });

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

describe('высота и материал стен', () => {
  it('высота стены - этаж без плиты, не ниже 100 мм', () => {
    expect(wallHeightMm({ floor_height_mm: 3000, slab_thickness_mm: 200 })).toBe(2800);
    expect(wallHeightMm({ floor_height_mm: 250, slab_thickness_mm: 200 })).toBe(100);
    expect(wallHeightMm({ floor_height_mm: Number.NaN, slab_thickness_mm: 200 })).toBe(100);
  });

  it('монолит отдельно, кладка и перегородки вместе, плита перекрытия не стена', () => {
    expect(wallMaterialOf('monolith_wall')).toBe('monolith');
    expect(wallMaterialOf('monolith_pylon')).toBe('monolith');
    expect(wallMaterialOf('monolith_column')).toBe('monolith');
    expect(wallMaterialOf('masonry')).toBe('masonry');
    expect(wallMaterialOf('frame_partition')).toBe('masonry');
    expect(wallMaterialOf('floor_slab')).toBeNull();
  });

  it('счёт по видам; контуров нет - null', () => {
    const walls = [
      wall('masonry', rect(0, 0, 1, 1)),
      wall('monolith_wall', rect(0, 0, 1, 1)),
      wall('monolith_pylon', rect(0, 0, 1, 1)),
      wall('frame_partition', rect(0, 0, 1, 1)),
      wall('floor_slab', rect(0, 0, 1, 1)),
    ];
    expect(countWalls(walls)).toEqual({ monolith: 2, masonry: 1, partition: 1 });
    expect(countWalls(null)).toBeNull();
    expect(countWalls(undefined)).toBeNull();
  });
});

describe('план просмотрщика', () => {
  it('стены сдвинуты на тот же центр, что и контур; верх стен над плитой', () => {
    const plan = buildViewerPlan([
      floor({ walls: [wall('masonry', rect(0, 0, 10000, 200)), wall('floor_slab', rect(0, 0, 10, 10))] }),
    ]);
    const spec = plan?.floors[0];
    expect(spec?.walls).toHaveLength(1);
    expect(spec?.walls[0]?.material).toBe('masonry');
    // Центр контура (5000; 3000) -> контур стены от (-5; -3) до (5; -2.8) м.
    expect(spec?.walls[0]?.shell[0]).toEqual([-5, -3]);
    // Высоты тоже от центра здания (-0.2..3.0 м -> центр 1.4 м): верх плиты -1.4, верх стен выше на 2.8.
    expect(spec?.slabTop).toBeCloseTo(-1.4);
    expect((spec?.wallTop ?? 0) - (spec?.slabTop ?? 0)).toBeCloseTo(2.8);
  });

  it('вырожденные контуры отбрасываются, этаж без отметки не строится', () => {
    const plan = buildViewerPlan([
      floor({ walls: [wall('masonry', [[0, 0], [1, 1]]), wall('monolith_wall', rect(0, 0, 0, 0))] }),
      floor({ job_id: 'j2', elevation_known: false }),
    ]);
    expect(plan?.floors).toHaveLength(1);
    expect(plan?.floors[0]?.walls).toHaveLength(0);
  });

  it('нет этажей с отметкой - плана нет; walls = null - стен нет', () => {
    expect(buildViewerPlan([floor({ elevation_known: false })])).toBeNull();
    expect(buildViewerPlan([floor({ walls: null })])?.floors[0]?.walls).toEqual([]);
  });
});

describe('разнесение этажей и вписывание', () => {
  const stack = (): ReturnType<typeof buildViewerPlan> =>
    buildViewerPlan([
      floor({ job_id: 'a', base_z_mm: 0 }),
      floor({ job_id: 'b', base_z_mm: 3000 }),
      floor({ job_id: 'c', base_z_mm: 6000 }),
      floor({ job_id: 'd', base_z_mm: 6000, page_index: 1 }),
    ]);

  it('уровни снизу вверх раздвигаются на 1.5 высоты этажа, этажи одной отметки - вместе', () => {
    const plan = stack();
    if (plan === null) throw new Error('план не построен');
    const offsets = explodeOffsets(plan);
    const byJob = (job: string, page = 0): number | undefined => offsets.get(`${job}:${page}:0`);
    expect(byJob('a')).toBe(0);
    expect(byJob('b')).toBeCloseTo(4.5);
    expect(byJob('c')).toBeCloseTo(9);
    expect(byJob('d', 1)).toBeCloseTo(9);
  });

  it('сфера разнесённого здания больше сжатого', () => {
    const plan = stack();
    if (plan === null) throw new Error('план не построен');
    const packed = viewerBounds(plan, false);
    const exploded = viewerBounds(plan, true);
    expect(exploded.radius).toBeGreaterThan(packed.radius);
    expect(exploded.center[1]).toBeGreaterThan(packed.center[1]);
  });

  it('расстояние вписывания растёт с радиусом и для узкого экрана больше', () => {
    const wide = fitDistance(10, 40, 2);
    expect(fitDistance(20, 40, 2)).toBeGreaterThan(wide);
    expect(fitDistance(10, 40, 0.5)).toBeGreaterThan(wide);
    // Сфера радиуса r при расстоянии d видна под углом asin(r / d) - не больше половины угла обзора.
    const half = (40 / 2) * (Math.PI / 180);
    expect(Math.asin(10 / fitDistance(10, 40, 1.5))).toBeLessThan(half);
  });
});

describe('экструзия и слияние', () => {
  it('призма из контура: высота и позиция по Y', () => {
    const geometry = extrudeShell([[0, 0], [4, 0], [4, 2], [0, 2]], 1, 3);
    expect(geometry).not.toBeNull();
    geometry?.computeBoundingBox();
    const box = geometry?.boundingBox;
    expect(box?.min.y).toBeCloseTo(1);
    expect(box?.max.y).toBeCloseTo(3);
    // Ось v плана идёт в -Z сцены.
    expect(box?.min.z).toBeCloseTo(-2);
    expect(box?.max.x).toBeCloseTo(4);
    geometry?.dispose();
  });

  it('нулевая высота и вырожденный контур - без геометрии', () => {
    expect(extrudeShell([[0, 0], [4, 0], [4, 2]], 1, 1)).toBeNull();
    expect(extrudeShell([[0, 0], [0, 0], [1, 1]], 0, 1)).toBeNull();
  });

  it('несколько контуров сливаются в одну геометрию', () => {
    const a = extrudeShell([[0, 0], [1, 0], [1, 1], [0, 1]], 0, 1);
    const b = extrudeShell([[5, 0], [6, 0], [6, 1], [5, 1]], 0, 1);
    const merged = mergeShells(
      [
        [[0, 0], [1, 0], [1, 1], [0, 1]],
        [[5, 0], [6, 0], [6, 1], [5, 1]],
        [[0, 0], [1, 1]],
      ],
      0,
      1,
    );
    expect(merged).not.toBeNull();
    expect(merged?.getAttribute('position').count).toBe(
      (a?.getAttribute('position').count ?? 0) + (b?.getAttribute('position').count ?? 0),
    );
    expect(mergeShells([], 0, 1)).toBeNull();
    expect(mergeShells([[[0, 0], [1, 1]]], 0, 1)).toBeNull();
  });
});
