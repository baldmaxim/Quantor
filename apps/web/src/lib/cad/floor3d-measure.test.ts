import { describe, expect, it } from 'vitest';

import { toScenePoint } from './floor3d-geometry';
import {
  formatMm,
  measureBetween,
  measureLabel,
  measureText,
  midpoint,
  sceneToMm,
  snapToNearestVertex,
  type SceneVec3,
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
