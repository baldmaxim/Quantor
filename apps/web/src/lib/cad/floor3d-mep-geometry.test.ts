import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import {
  axisBasis,
  boxBetween,
  cylinderBetween,
  mergeSolids,
  normalizeAxis,
  polylineSolids,
  DISPLAY_DN_UNKNOWN_MM,
  routeSection,
} from './floor3d-mep-geometry';

const sizeOf = (geometry: THREE.BufferGeometry): THREE.Vector3 => {
  geometry.computeBoundingBox();
  return (geometry.boundingBox as THREE.Box3).getSize(new THREE.Vector3());
};

const close = (value: number, expected: number): void => expect(value).toBeCloseTo(expected, 6);

/** Габарит многогранной трубы отличается от Ø не больше чем на грань. */
const near = (value: number, expected: number): void =>
  expect(Math.abs(value - expected)).toBeLessThan(0.006);

const v = (x: number, y: number, z: number): THREE.Vector3 => new THREE.Vector3(x, y, z);

describe('сечение полилинии', () => {
  it('round без Ø или с нулём - труба условного Ø 20 мм, а не линия', () => {
    expect(DISPLAY_DN_UNKNOWN_MM).toBe(20);
    expect(routeSection({ shape: 'round', dn_mm: null })).toEqual({ shape: 'round', dnMm: 20 });
    expect(routeSection({ shape: 'round', dn_mm: 0 })).toEqual({ shape: 'round', dnMm: 20 });
    expect(routeSection({ shape: 'round' })).toEqual({ shape: 'round', dnMm: 20 });
  });

  it('round с DN и rect с размерами - сечение; остальное - линия', () => {
    expect(routeSection({ shape: 'round', dn_mm: 110 })).toEqual({ shape: 'round', dnMm: 110 });
    expect(routeSection({ shape: 'rect', w_mm: 400, h_mm: 200 })).toEqual({
      shape: 'rect',
      wMm: 400,
      hMm: 200,
    });
    expect(routeSection({})).toBeNull();
    expect(routeSection({ shape: 'rect', w_mm: 400, h_mm: null })).toBeNull();
  });
});

describe('ось элемента', () => {
  it('целые x1000 нормализуются и переводятся в сцену (DXF Z вверх, DXF Y -> -Z сцены)', () => {
    const same = (axis: number[], expected: THREE.Vector3): void =>
      close((normalizeAxis(axis) as THREE.Vector3).distanceTo(expected), 0);
    same([1000, 0, 0], v(1, 0, 0));
    same([0, 0, 1000], v(0, 1, 0));
    same([0, 1000, 0], v(0, 0, -1));
    const diagonal = normalizeAxis([707, 707, 0]) as THREE.Vector3;
    close(diagonal.length(), 1);
    expect(normalizeAxis([0, 0, 0])).toBeNull();
    expect(normalizeAxis([1, Number.NaN, 0])).toBeNull();
    expect(normalizeAxis([1, 0])).toBeNull();
  });

  it('базис правый и ось - локальный +Z, в том числе у вертикали', () => {
    for (const dir of [v(1, 0, 0), v(0, 1, 0), v(0, -1, 0), v(0.6, 0.8, 0)]) {
      const basis = axisBasis(dir);
      close(basis.determinant(), 1);
      const z = new THREE.Vector3(0, 0, 1).transformDirection(basis);
      close(z.distanceTo(dir.clone().normalize()), 0);
    }
  });
});

describe('цилиндр и короб участка', () => {
  it('цилиндр ориентирован по участку: вдоль X, вдоль Y и по диагонали', () => {
    const alongX = sizeOf(cylinderBetween(v(0, 0, 0), v(2, 0, 0), 0.05) as THREE.BufferGeometry);
    close(alongX.x, 2);
    near(alongX.y, 0.1);
    const alongY = sizeOf(cylinderBetween(v(1, 0, 1), v(1, 3, 1), 0.05) as THREE.BufferGeometry);
    close(alongY.y, 3);
    near(alongY.x, 0.1);
    const diagonal = cylinderBetween(v(0, 0, 0), v(3, 4, 0), 0.05) as THREE.BufferGeometry;
    const box = new THREE.Box3().setFromBufferAttribute(
      diagonal.getAttribute('position') as THREE.BufferAttribute,
    );
    close(box.getCenter(new THREE.Vector3()).distanceTo(v(1.5, 2, 0)), 0);
    expect(cylinderBetween(v(1, 1, 1), v(1, 1, 1), 0.05)).toBeNull();
  });

  it('короб вертикального участка: w по X сцены, h по Z сцены (Y DXF)', () => {
    const size = sizeOf(boxBetween(v(0, 0, 0), v(0, 3, 0), 0.4, 0.2) as THREE.BufferGeometry);
    close(size.x, 0.4);
    close(size.y, 3);
    close(size.z, 0.2);
  });

  it('короб горизонтального участка: h по вертикали, w поперёк в плане', () => {
    const size = sizeOf(boxBetween(v(0, 2, 0), v(5, 2, 0), 0.4, 0.2) as THREE.BufferGeometry);
    close(size.x, 5);
    close(size.y, 0.2);
    close(size.z, 0.4);
    const across = sizeOf(boxBetween(v(0, 2, 0), v(0, 2, 5), 0.4, 0.2) as THREE.BufferGeometry);
    close(across.x, 0.4);
    close(across.y, 0.2);
    close(across.z, 5);
  });
});

describe('детали полилинии', () => {
  const bent = [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1)];
  const round = { shape: 'round', dnMm: 50 } as const;

  it('труба: цилиндр на участок и сфера в изломе', () => {
    expect(polylineSolids(bent, round)).toHaveLength(3);
  });

  it('нет сферы на прямом продолжении, у фасонины и на концах', () => {
    expect(polylineSolids([v(0, 0, 0), v(1, 0, 0), v(2, 0, 0)], round)).toHaveLength(2);
    expect(polylineSolids(bent, round, { hasFittingAt: (i) => i === 1 })).toHaveLength(2);
    expect(polylineSolids([v(0, 0, 0), v(1, 0, 0)], round)).toHaveLength(1);
  });

  it('воздуховод: только короба, без сфер', () => {
    expect(polylineSolids(bent, { shape: 'rect', wMm: 400, hMm: 200 })).toHaveLength(2);
  });

  it('утолщение изоляции увеличивает радиус', () => {
    const [plain] = polylineSolids([v(0, 0, 0), v(2, 0, 0)], round);
    const [shell] = polylineSolids([v(0, 0, 0), v(2, 0, 0)], round, { inflateM: 0.02 });
    near(sizeOf(plain as THREE.BufferGeometry).y, 0.05);
    near(sizeOf(shell as THREE.BufferGeometry).y, 0.09);
  });

  it('слияние даёт одну геометрию', () => {
    const parts = polylineSolids(bent, round);
    const merged = mergeSolids(parts) as THREE.BufferGeometry;
    expect(merged.getAttribute('position').count).toBeGreaterThan(0);
    expect(mergeSolids([])).toBeNull();
  });
});
