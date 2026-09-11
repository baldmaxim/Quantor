import { describe, expect, it, vi } from 'vitest';

import { beginLayerPaint, boundsIntersectAny } from './layer-paint';

/**
 * Подготовка холста слоя: весь холст или полосы панорамы (ADR-0025).
 *
 * Ошибка здесь выглядит как «после панорамы на слое остались старые фигуры» или «фигура у края
 * полосы обрезана» — поэтому проверяется, что именно чистится, чем ограничено рисование и какие
 * прямоугольники получает рисовальщик.
 */

const fakeContext = (width: number, height: number) => {
  const calls: string[] = [];
  const context = {
    canvas: { width, height },
    setTransform: vi.fn(() => calls.push('setTransform')),
    save: vi.fn(() => calls.push('save')),
    clearRect: vi.fn(() => calls.push('clearRect')),
    beginPath: vi.fn(() => calls.push('beginPath')),
    rect: vi.fn(() => calls.push('rect')),
    clip: vi.fn(() => calls.push('clip')),
    scale: vi.fn(() => calls.push('scale')),
  } as unknown as CanvasRenderingContext2D;
  return { context, calls };
};

describe('подготовка холста слоя', () => {
  it('без полос чистит весь холст и отдаёт его в CSS-пикселях с запасом', () => {
    const { context, calls } = fakeContext(2400, 1500);

    const visible = beginLayerPaint(context, 1.5, null, 8);

    expect(context.clearRect).toHaveBeenCalledWith(0, 0, 2400, 1500);
    expect(context.clip).not.toHaveBeenCalled();
    expect(context.scale).toHaveBeenCalledWith(1.5, 1.5);
    expect(visible).toEqual([{ x: -8, y: -8, width: 1616, height: 1016 }]);
    // Сброс преобразования до сохранения: иначе restore вернул бы чужой масштаб.
    expect(calls.indexOf('setTransform')).toBeLessThan(calls.indexOf('save'));
  });

  it('с полосами чистит и ограничивает рисование только ими', () => {
    const { context, calls } = fakeContext(2400, 1500);
    const strips = [
      { x: 2250, y: 0, width: 150, height: 1500 },
      { x: 0, y: 0, width: 2400, height: 30 },
    ];

    const visible = beginLayerPaint(context, 1.5, strips, 0);

    expect(context.clearRect).toHaveBeenCalledTimes(2);
    expect(context.clearRect).toHaveBeenCalledWith(2250, 0, 150, 1500);
    expect(context.clearRect).toHaveBeenCalledWith(0, 0, 2400, 30);
    expect(context.rect).toHaveBeenCalledTimes(2);
    expect(context.clip).toHaveBeenCalledTimes(1);
    // Полосы режутся в физических пикселях — до перехода к CSS-пикселям.
    expect(calls.indexOf('clip')).toBeLessThan(calls.indexOf('scale'));
    expect(visible).toEqual([
      { x: 1500, y: 0, width: 100, height: 1000 },
      { x: 0, y: 0, width: 1600, height: 20 },
    ]);
  });

  it('нулевая плотность не ломает перевод в CSS-пиксели', () => {
    const { context } = fakeContext(100, 100);

    expect(beginLayerPaint(context, 0, null, 0)).toEqual([{ x: 0, y: 0, width: 100, height: 100 }]);
  });
});

describe('пересечение охвата с полосами', () => {
  const rects = [
    { x: 0, y: 0, width: 100, height: 1000 },
    { x: 0, y: 900, width: 1600, height: 100 },
  ];

  it('охват, касающийся полосы краем, видим', () => {
    expect(boundsIntersectAny(100, 500, 200, 600, rects)).toBe(true);
  });

  it('охват между полосами не виден', () => {
    expect(boundsIntersectAny(101, 100, 800, 899, rects)).toBe(false);
  });

  it('достаточно одной полосы из нескольких', () => {
    expect(boundsIntersectAny(700, 950, 800, 960, rects)).toBe(true);
  });

  it('без полос не видно ничего', () => {
    expect(boundsIntersectAny(0, 0, 10, 10, [])).toBe(false);
  });
});
