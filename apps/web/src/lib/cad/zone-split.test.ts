import { describe, expect, it } from 'vitest';

import { SPLIT_OUTSIDE_TEXT, locateOnRing, ringArea, splitRing, type ZoneRing } from './zone-split';

const RECT: ZoneRing = [
  [0.1, 0.1],
  [0.5, 0.1],
  [0.5, 0.3],
  [0.1, 0.3],
];

/** Г-образная зона: прямоугольник 0.4 x 0.4 без правого верхнего квадрата 0.2 x 0.2. */
const L_SHAPE: ZoneRing = [
  [0.1, 0.1],
  [0.3, 0.1],
  [0.3, 0.3],
  [0.5, 0.3],
  [0.5, 0.5],
  [0.1, 0.5],
];

const on = (ring: ZoneRing, x: number, y: number) => {
  const located = locateOnRing(ring, { x, y });
  if (!located) throw new Error(`точка (${x}, ${y}) не на границе`);
  return located;
};

describe('locateOnRing', () => {
  it('находит ребро, на котором лежит точка; точка вне границы - null', () => {
    expect(locateOnRing(RECT, { x: 0.3, y: 0.1 })?.edge).toBe(0);
    expect(locateOnRing(RECT, { x: 0.5, y: 0.2 })?.edge).toBe(1);
    expect(locateOnRing(RECT, { x: 0.3, y: 0.2 })).toBeNull();
    expect(locateOnRing(RECT, { x: 0.9, y: 0.9 })).toBeNull();
  });
});

describe('splitRing', () => {
  it('прямоугольник пополам: две части по 4 вершины, площади в сумме равны исходной', () => {
    const result = splitRing(RECT, on(RECT, 0.3, 0.1), on(RECT, 0.3, 0.3));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const [one, two] = result.rings;
    expect(one).toEqual([
      [0.3, 0.1],
      [0.5, 0.1],
      [0.5, 0.3],
      [0.3, 0.3],
    ]);
    expect(two).toEqual([
      [0.3, 0.3],
      [0.1, 0.3],
      [0.1, 0.1],
      [0.3, 0.1],
    ]);
    expect(ringArea(one) + ringArea(two)).toBeCloseTo(ringArea(RECT), 12);
    expect(ringArea(one)).toBeCloseTo(0.04, 12);
  });

  it('Г-образная зона: горизонтальная линия от левого ребра к ребру выступа делит на две части', () => {
    const result = splitRing(L_SHAPE, on(L_SHAPE, 0.1, 0.2), on(L_SHAPE, 0.3, 0.2));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const areas = result.rings.map(ringArea).sort((first, second) => first - second);
    expect(areas[0]).toBeCloseTo(0.2 * 0.1, 12);
    expect(areas[1]).toBeCloseTo(0.12 - 0.02, 12);
    expect((areas[0] ?? 0) + (areas[1] ?? 0)).toBeCloseTo(ringArea(L_SHAPE), 12);
  });

  it('Г-образная зона: вертикальная линия от верхнего ребра до нижнего', () => {
    const result = splitRing(L_SHAPE, on(L_SHAPE, 0.2, 0.1), on(L_SHAPE, 0.2, 0.5));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.rings.map(ringArea).sort((first, second) => first - second)[0]).toBeCloseTo(
      0.04,
      12,
    );
  });

  it('Г-образная зона: отрезок через вырез (середина снаружи) - отказ', () => {
    const result = splitRing(L_SHAPE, on(L_SHAPE, 0.3, 0.2), on(L_SHAPE, 0.4, 0.3));
    expect(result).toEqual({ ok: false, reason: SPLIT_OUTSIDE_TEXT });
  });

  it('отрезок пересекает чужое ребро - отказ', () => {
    // Диагональ из (0.2, 0.1) в (0.5, 0.4) пересекает ребро (0.3,0.1)-(0.3,0.3) выступа.
    const result = splitRing(L_SHAPE, on(L_SHAPE, 0.2, 0.1), on(L_SHAPE, 0.5, 0.4));
    expect(result).toEqual({ ok: false, reason: SPLIT_OUTSIDE_TEXT });
  });

  it('точка вне границы - отказ', () => {
    const result = splitRing(
      RECT,
      { edge: 0, point: { x: 0.3, y: 0.1 } },
      { edge: 2, point: { x: 0.3, y: 0.25 } },
    );
    expect(result).toEqual({ ok: false, reason: SPLIT_OUTSIDE_TEXT });
  });

  it('точка на вершине не дублирует её: диагональ квадрата даёт два треугольника', () => {
    const square: ZoneRing = [
      [0.1, 0.1],
      [0.3, 0.1],
      [0.3, 0.3],
      [0.1, 0.3],
    ];
    const result = splitRing(square, on(square, 0.1, 0.1), on(square, 0.3, 0.3));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.rings.map((ring) => ring.length)).toEqual([3, 3]);
    expect(result.rings[0]).toEqual([
      [0.1, 0.1],
      [0.3, 0.1],
      [0.3, 0.3],
    ]);
    expect(ringArea(result.rings[0])).toBeCloseTo(0.02, 12);
  });

  it('вершина и точка на ребре: треугольник и четырёхугольник', () => {
    const result = splitRing(RECT, on(RECT, 0.1, 0.1), on(RECT, 0.5, 0.2));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.rings.map((ring) => ring.length).sort()).toEqual([3, 4]);
  });

  it('обе точки на одном ребре или в одной точке - отказ (часть без площади)', () => {
    expect(splitRing(RECT, on(RECT, 0.2, 0.1), on(RECT, 0.4, 0.1))).toEqual({
      ok: false,
      reason: SPLIT_OUTSIDE_TEXT,
    });
    expect(splitRing(RECT, on(RECT, 0.3, 0.1), on(RECT, 0.3, 0.1)).ok).toBe(false);
  });

  it('смежные вершины - отрезок по границе, отказ', () => {
    expect(splitRing(RECT, on(RECT, 0.1, 0.1), on(RECT, 0.5, 0.1)).ok).toBe(false);
  });

  it('части сохраняют направление обхода исходного кольца', () => {
    const result = splitRing(RECT, on(RECT, 0.3, 0.1), on(RECT, 0.3, 0.3));
    if (!result.ok) throw new Error('ожидался успешный разрез');
    const signed = (ring: ZoneRing) =>
      ring.reduce((sum, [x0, y0], at) => {
        const [x1, y1] = ring[(at + 1) % ring.length] as readonly [number, number];
        return sum + (x0 * y1 - x1 * y0);
      }, 0);
    expect(Math.sign(signed(result.rings[0]))).toBe(Math.sign(signed(RECT)));
    expect(Math.sign(signed(result.rings[1]))).toBe(Math.sign(signed(RECT)));
  });
});
