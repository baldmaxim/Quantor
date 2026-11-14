import type { CadBuilding3dFloorRead, CadBuilding3dWallRead } from '@quantor/api-client';
import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import {
  buildViewerPlan,
  countWalls,
  explodeOffsets,
  extrudeLevels,
  extrudeShell,
  fitDistance,
  mergeShells,
  mergeWalls,
  viewerBounds,
  wallHeightMm,
  wallIdAtFace,
  wallMaterialOf,
} from './building-viewer-geometry';

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

let wallSeq = 0;
const wall = (kind: CadBuilding3dWallRead['kind'], shell: number[][]): CadBuilding3dWallRead => ({
  id: `w${(wallSeq += 1)}`,
  kind,
  shell,
});

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

  it('грани смотрят наружу при любом обходе контура: верх +Y, низ -Y, бока от центра', () => {
    const clockwise: [number, number][] = [[0, 0], [0, 2], [4, 2], [4, 0]];
    for (const shell of [clockwise, [...clockwise].reverse()]) {
      const geometry = extrudeShell(shell, 1, 3);
      if (geometry === null) throw new Error('геометрия не построена');
      const position = geometry.getAttribute('position');
      const normal = geometry.getAttribute('normal');
      expect(normal.count).toBe(position.count);
      for (let t = 0; t < position.count; t += 3) {
        const v = [0, 1, 2].map((k) => new THREE.Vector3().fromBufferAttribute(position, t + k));
        const [a, b, c] = v as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
        // Нормаль по обходу треугольника (лицевая сторона three) совпадает с записанной.
        const face = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a)).normalize();
        const stored = new THREE.Vector3().fromBufferAttribute(normal, t);
        expect(face.dot(stored)).toBeCloseTo(1);
        // И смотрит от центра призмы (2, 2, -1).
        const centroid = new THREE.Vector3().add(a).add(b).add(c).divideScalar(3);
        expect(centroid.sub(new THREE.Vector3(2, 2, -1)).dot(stored)).toBeGreaterThan(0);
      }
      geometry.dispose();
    }
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

describe('конструкция по номеру треугольника', () => {
  const square = (x: number): [number, number][] => [[x, 0], [x + 1, 0], [x + 1, 1], [x, 1]];

  it('диапазоны идут по порядку слияния и покрывают все треугольники', () => {
    const merged = mergeWalls(
      [
        { id: 'a', shell: [[0, 0], [1, 0], [1, 1], [0, 1]] },
        { id: 'skip', shell: [[0, 0], [1, 1]] },
        { id: 'b', shell: [[5, 0], [6, 0], [6, 1], [5, 1]] },
      ],
      0,
      1,
    );
    if (merged === null) throw new Error('геометрия не построена');
    expect(merged.ranges.map((range) => range.id)).toEqual(['a', 'b']);
    const [first, second] = merged.ranges;
    expect(first?.start).toBe(0);
    expect(second?.start).toBe(first?.end);
    // Не индексированная геометрия: по три вершины на треугольник.
    expect(second?.end).toBe(merged.geometry.getAttribute('position').count / 3);
    merged.geometry.dispose();
  });

  it('faceIndex находит свою конструкцию; вне диапазонов и мусор - null', () => {
    const ranges = [
      { id: 'a', start: 0, end: 12 },
      { id: 'b', start: 12, end: 20 },
      { id: 'c', start: 20, end: 32 },
    ];
    expect(wallIdAtFace(ranges, 0)).toBe('a');
    expect(wallIdAtFace(ranges, 11)).toBe('a');
    expect(wallIdAtFace(ranges, 12)).toBe('b');
    expect(wallIdAtFace(ranges, 31)).toBe('c');
    expect(wallIdAtFace(ranges, 32)).toBeNull();
    expect(wallIdAtFace(ranges, -1)).toBeNull();
    expect(wallIdAtFace(ranges, undefined)).toBeNull();
    expect(wallIdAtFace(ranges, 1.5)).toBeNull();
    expect(wallIdAtFace([], 0)).toBeNull();
  });

  it('по настоящей слитой геометрии: треугольник второй стены - вторая конструкция', () => {
    const merged = mergeWalls(
      [
        { id: 'a', shell: square(0) },
        { id: 'b', shell: square(5) },
      ],
      0,
      1,
    );
    if (merged === null) throw new Error('геометрия не построена');
    const last = merged.geometry.getAttribute('position').count / 3 - 1;
    expect(wallIdAtFace(merged.ranges, 0)).toBe('a');
    expect(wallIdAtFace(merged.ranges, last)).toBe('b');
    merged.geometry.dispose();
  });
});

describe('уровни плиты (кровля, ступенчатый этаж)', () => {
  const square = (u0: number, v0: number, u1: number, v1: number): [number, number][] => [
    [u0, v0],
    [u1, v0],
    [u1, v1],
    [u0, v1],
  ];
  const roof = floor({
    base_z_mm: 99300,
    outline: rect(0, 0, 6000, 4000),
    levels: [
      {
        shell: rect(0, 0, 6000, 4000),
        holes: [rect(1000, 1000, 2000, 2000)],
        top_mm: 99050,
        mark_mm: 99050,
        max_mm: 99300,
        source: 'marks',
      },
      { shell: rect(1000, 1000, 2000, 2000), holes: [], top_mm: 91750, mark_mm: 91750, max_mm: 91750, source: 'marks' },
    ],
    walls: [{ ...wall('masonry', rect(0, 0, 6000, 200)), top_mm: 100750 }, wall('masonry', rect(0, 3800, 6000, 4000))],
  });

  it('участки и верх парапета переводятся в метры от центра плана', () => {
    const plan = buildViewerPlan([roof]);
    expect(plan).not.toBeNull();
    const spec = plan?.floors[0];
    const center = plan?.zCenterMm ?? 0;
    expect(spec?.levels.map((level) => level.top)).toEqual([(99050 - center) / 1000, (91750 - center) / 1000]);
    expect(spec?.levels[0]?.holes).toHaveLength(1);
    expect(spec?.walls[0]?.top).toBeCloseTo((100750 - center) / 1000);
    expect(spec?.walls[1]?.top).toBeUndefined();
  });

  it('плита из участков: каждый под своим верхом, с отверстием', () => {
    const geometry = extrudeLevels(
      [
        { shell: square(0, 0, 6, 4), holes: [square(1, 1, 2, 2)], top: 0 },
        { shell: square(1, 1, 2, 2), holes: [], top: -7.3 },
      ],
      0.2,
    );
    expect(geometry).not.toBeNull();
    geometry?.computeBoundingBox();
    const box = geometry?.boundingBox;
    expect(box?.max.y).toBeCloseTo(0);
    expect(box?.min.y).toBeCloseTo(-7.5);
    expect(box?.max.x).toBeCloseTo(6);
    expect(box?.min.z).toBeCloseTo(-4);
    expect(extrudeLevels([], 0.2)).toBeNull();
    expect(extrudeLevels([{ shell: square(0, 0, 1, 1), holes: [], top: 0 }], 0)).toBeNull();
  });

  it('стена со своим верхом строится до него, ниже низа - не строится', () => {
    const merged = mergeWalls(
      [
        { id: 'a', shell: square(0, 0, 1, 1), top: 5 },
        { id: 'b', shell: square(2, 0, 3, 1) },
        { id: 'c', shell: square(4, 0, 5, 1), top: -1 },
      ],
      0,
      3,
    );
    expect(merged?.ranges.map((range) => range.id)).toEqual(['a', 'b']);
    merged?.geometry.computeBoundingBox();
    expect(merged?.geometry.boundingBox?.max.y).toBeCloseTo(5);
  });
});
