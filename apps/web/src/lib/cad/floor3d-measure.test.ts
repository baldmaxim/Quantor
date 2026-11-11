import { describe, expect, it } from 'vitest';

import { toScenePoint } from './floor3d-geometry';
import {
  buildFeatureEdges,
  closestPointOnEdge,
  formatMm,
  measureBetween,
  measureLabel,
  measureText,
  midpoint,
  sceneToMm,
  snapPoint,
  snapToNearestVertex,
  type SceneVec3,
  type Triangle3,
} from './floor3d-measure';

const center = { x: 5000, y: 3000, z: 4000 };

describe('сцена -> мм DXF', () => {
  it('обратна к toScenePoint (центрирование, /1000, Z сцены = -Y DXF)', () => {
    const scene = toScenePoint(1234, 5678, 3210, center);
    const back = sceneToMm(scene, center);
    expect(back.x).toBeCloseTo(1234, 6);
    expect(back.y).toBeCloseTo(5678, 6);
    expect(back.z).toBeCloseTo(3210, 6);
  });

  it('начало сцены - центр модели', () => {
    expect(sceneToMm([0, 0, 0], center)).toEqual({ x: 5000, y: 3000, z: 4000 });
  });
});

describe('замер', () => {
  it('расстояние и приращения; dz - по высоте', () => {
    const result = measureBetween({ x: 0, y: 0, z: 0 }, { x: 3000, y: 4000, z: 0 });
    expect(result).toEqual({ distanceMm: 5000, dx: 3000, dy: 4000, dz: 0 });
    expect(measureBetween({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: -2800 }).dz).toBe(-2800);
  });

  it('формат: целые мм, пробелы тысяч, знак у приращений', () => {
    expect(formatMm(1234567.4)).toBe('1 234 567');
    expect(formatMm(-0.3, true)).toBe('0');
    expect(formatMm(-1500, true)).toBe('−1 500');
    expect(formatMm(2800, true)).toBe('+2 800');
  });

  it('подпись из двух точек сцены', () => {
    const a = toScenePoint(0, 0, 0, center);
    const b = toScenePoint(3000, 4000, 2800, center);
    const text = measureLabel(a, b, center);
    expect(text.distance).toBe('5 731 мм');
    expect(text.deltas).toBe('Δx +3 000 · Δy +4 000 · Δz +2 800 мм');
    expect(measureText(measureBetween({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 })).distance).toBe('0 мм');
  });

  it('середина отрезка', () => {
    expect(midpoint([0, 0, 0], [2, 4, -6])).toEqual([1, 2, -3]);
  });
});

describe('привязка к вершине', () => {
  // Ортографическая «камера»: экран = (x, y) * 100.
  const project = (p: SceneVec3) => ({ x: p[0] * 100, y: p[1] * 100 });
  const hit: SceneVec3 = [0.5, 0.5, 0];
  const vertices: SceneVec3[] = [
    [0, 0, 0],
    [1, 0, 0],
    [0, 1, 0],
  ];

  it('вершина ближе порога - берётся она', () => {
    const result = snapToNearestVertex(hit, vertices, { x: 5, y: 8 }, project);
    expect(result).toEqual({ point: [0, 0, 0], snapped: true });
  });

  it('все вершины дальше 12 px - остаётся точка попадания', () => {
    expect(snapToNearestVertex(hit, vertices, { x: 50, y: 50 }, project)).toEqual({ point: hit, snapped: false });
  });

  it('из нескольких выбирается ближайшая; невидимая вершина пропускается', () => {
    const near = snapToNearestVertex(hit, vertices, { x: 96, y: 4 }, project);
    expect(near.point).toEqual([1, 0, 0]);
    const hidden = snapToNearestVertex(hit, vertices, { x: 0, y: 0 }, (p) => (p[0] === 0 && p[1] === 0 ? null : project(p)));
    expect(hidden.snapped).toBe(false);
  });
});

describe('привязка при наведении: угол -> ребро -> грань', () => {
  // Ортографическая «камера»: экран = (x, y) * 100.
  const project = (p: SceneVec3) => ({ x: p[0] * 100, y: p[1] * 100 });
  const triangle: Triangle3 = [
    [0, 0, 0],
    [1, 0, 0],
    [0, 1, 0],
  ];
  // Ребра 0 (0->1) и 2 (2->0) - настоящие, ребро 1 (1->2) - диагональ.
  const flags = [true, false, true] as const;
  const hit: SceneVec3 = [0.5, 0.2, 0];

  it('угол в 12 px важнее ребра', () => {
    const result = snapPoint(hit, triangle, flags, { x: 6, y: 5 }, project);
    expect(result).toEqual({ kind: 'vertex', point: [0, 0, 0] });
  });

  it('ребро в 8 px: точка лежит на ребре', () => {
    const result = snapPoint(hit, triangle, flags, { x: 50, y: 6 }, project);
    expect(result.kind).toBe('edge');
    expect(result.point[0]).toBeCloseTo(0.5, 3);
    expect(result.point[1]).toBeCloseTo(0, 3);
  });

  it('дальше 8 px от ребра - точка попадания на грани', () => {
    expect(snapPoint(hit, triangle, flags, { x: 50, y: 20 }, project)).toEqual({ kind: 'face', point: hit });
  });

  it('диагональ не считается ребром', () => {
    // Курсор у середины диагонали (0.5, 0.5).
    const result = snapPoint([0.45, 0.45, 0], triangle, flags, { x: 50, y: 50 }, project);
    expect(result.kind).toBe('face');
  });

  it('ребро ближе другого выбирается по расстоянию на экране', () => {
    const near = snapPoint(hit, triangle, [true, false, true], { x: 4, y: 40 }, project);
    expect(near.kind).toBe('edge');
    expect(near.point[0]).toBeCloseTo(0, 3);
    expect(near.point[1]).toBeCloseTo(0.4, 3);
  });

  it('точка ребра зажата концами отрезка', () => {
    const found = closestPointOnEdge([0, 0, 0], [1, 0, 0], { x: 300, y: 0 }, project);
    expect(found?.point[0]).toBeCloseTo(1, 3);
  });

  it('ребро с концом за камерой пропускается', () => {
    expect(closestPointOnEdge([0, 0, 0], [1, 0, 0], { x: 50, y: 0 }, (p) => (p[0] === 1 ? null : project(p)))).toBeNull();
  });
});

describe('рёбра сетки', () => {
  // Куб 1x1x1: 6 граней по 2 треугольника без индекса.
  const quad = (a: number[], b: number[], c: number[], d: number[]): number[] => [
    ...a, ...b, ...c, ...a, ...c, ...d,
  ];
  const cube = new Float32Array([
    ...quad([0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]),
    ...quad([0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]),
    ...quad([0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]),
    ...quad([0, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]),
    ...quad([0, 0, 0], [0, 1, 0], [0, 1, 1], [0, 0, 1]),
    ...quad([1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1]),
  ]);

  it('рёбра куба настоящие, диагонали граней - нет', () => {
    const edges = buildFeatureEdges(cube, null);
    // Грань 0: треугольники 0 (a,b,c) и 1 (a,c,d); диагональ a-c: ребро 2 первого и ребро 0 второго.
    expect(edges.isFeature(0, 2)).toBe(false);
    expect(edges.isFeature(1, 0)).toBe(false);
    // Внешние рёбра грани: a-b, b-c у первого, c-d, d-a у второго.
    expect(edges.isFeature(0, 0)).toBe(true);
    expect(edges.isFeature(0, 1)).toBe(true);
    expect(edges.isFeature(1, 1)).toBe(true);
    expect(edges.isFeature(1, 2)).toBe(true);
  });

  it('индексированная сетка даёт тот же результат; открытая граница - настоящее ребро', () => {
    // Квадрат из двух треугольников по индексам: диагональ 0-2 внутри, остальное - граница.
    const positions = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0];
    const edges = buildFeatureEdges(positions, [0, 1, 2, 0, 2, 3]);
    expect(edges.isFeature(0, 2)).toBe(false);
    expect(edges.isFeature(1, 0)).toBe(false);
    expect(edges.isFeature(0, 0)).toBe(true);
    expect(edges.isFeature(1, 2)).toBe(true);
  });
});
