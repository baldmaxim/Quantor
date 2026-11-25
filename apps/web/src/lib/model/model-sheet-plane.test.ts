import { describe, expect, it } from 'vitest';

import { SHEET_LIFT_MM, sheetGeometryArrays, toWorld } from './model-sheet-plane';

describe('model-sheet-plane', () => {
  it('Speckle: Z вверх, метры', () => {
    expect(toWorld([12000, -3400], 18000, 'z')).toEqual([12, -3.4, 18]);
  });

  it('простой просмотр: оси glTF (Y вверх), как части QMP', () => {
    expect(toWorld([12000, -3400], 18000, 'y')).toEqual([12, 18, 3.4]);
  });

  it('четыре угла - два треугольника, верх растра у первых двух углов', () => {
    const corners = [
      [0, 1000],
      [2000, 1000],
      [2000, 0],
      [0, 0],
    ] as const;
    const { positions, uvs, index } = sheetGeometryArrays(corners, 3000 + SHEET_LIFT_MM, 'z');
    expect(positions.length).toBe(12);
    const [x, y, z] = Array.from(positions.slice(0, 3));
    expect(x).toBe(0);
    expect(y).toBeCloseTo(1, 6);
    expect(z).toBeCloseTo(3.03, 5);
    expect(Array.from(uvs)).toEqual([0, 1, 1, 1, 1, 0, 0, 0]);
    expect(index).toEqual([0, 1, 2, 0, 2, 3]);
  });

  it('не четыре угла - ошибка', () => {
    expect(() => sheetGeometryArrays([[0, 0]], 0, 'z')).toThrow();
  });
});
