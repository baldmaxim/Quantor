import { describe, expect, it } from 'vitest';

import { cadToNormalized } from '@/lib/cad/frame';

import { element, layer, polyline } from './fixtures';
import { buildTenderPaintData, layerTitle } from './geometry';
import { hitTender } from './painter';

// Кадр вида: pt = origin + (x, -y) / mm_per_pt; лист 1000 x 800 pt.
const FRAME = { originX: 100, originY: 700, mmPerPt: 10 };
const PAGE = { width: 1000, height: 800 };

const data = (patch: Partial<Parameters<typeof buildTenderPaintData>[0]> = {}) =>
  buildTenderPaintData({
    layers: [layer()],
    frame: FRAME,
    page: PAGE,
    colorOf: () => 'red',
    accent: 'blue',
    halo: 'white',
    selected: null,
    ...patch,
  });

describe('перевод геометрии расчёта в кадр листа', () => {
  it('вершина (x, y) мм вида переводится по кадру в нормализованные координаты', () => {
    const paint = data();
    const path = paint?.paths[0];
    // (1000, 2000) мм -> pt (100 + 100, 700 - 200) = (200, 500) -> (0.2, 0.625)
    expect(path?.points[0]).toBeCloseTo(0.2);
    expect(path?.points[1]).toBeCloseTo(0.625);
    const [nx, ny] = cadToNormalized(FRAME, PAGE, 5000, 2000);
    expect(path?.points[2]).toBeCloseTo(nx);
    expect(path?.points[3]).toBeCloseTo(ny);
  });

  it('ось Y вида смотрит вверх: больший y - выше на листе', () => {
    const paint = data({
      layers: [layer({ polylines: [polyline({ pts: [[0, 0, 0], [0, 1000, 0]] })], elements: [] })],
    });
    const points = paint?.paths[0]?.points;
    expect(points?.[3]).toBeLessThan(points?.[1] ?? 0);
  });

  it('прибор получает положение, подпись марки и направление оси на экране', () => {
    const paint = data({
      layers: [layer({ polylines: [], elements: [element({ axis: [0, 1000, 0] })] })],
    });
    const mark = paint?.marks[0];
    expect(mark?.x).toBeCloseTo(0.6);
    expect(mark?.label).toBe('КВ-2');
    // Ось +Y вида на экране смотрит вверх.
    expect(mark?.dy).toBeCloseTo(-1);
  });

  it('вершины с нечисловыми координатами пропускаются, линия без вершин не рисуется', () => {
    const paint = data({
      layers: [
        layer({
          polylines: [
            polyline({ id: 'bad', pts: [[Number.NaN, 0, 0]] }),
            polyline({ id: 'ok' }),
          ],
          elements: [],
        }),
      ],
    });
    expect(paint?.paths.map((path) => path.ref.object.data.id)).toEqual(['ok']);
  });

  it('нечего рисовать или лист нулевой - данных нет', () => {
    expect(data({ layers: [] })).toBeNull();
    expect(data({ page: { width: 0, height: 0 } })).toBeNull();
  });

  it('подпись строки слоя: название, номер и версия', () => {
    expect(layerTitle(layer())).toBe('Отопление жилой части · №3 v3');
  });
});

describe('выбор объекта щелчком', () => {
  const tolerance = 0.01;

  it('щелчок по линии находит её, мимо - ничего', () => {
    const paint = data({ layers: [layer({ elements: [] })] });
    if (paint === null) throw new Error('нет данных');
    const hit = hitTender(paint, { x: 0.3, y: 0.625 }, tolerance);
    expect(hit?.object.data.id).toBe('T1-a');
    expect(hitTender(paint, { x: 0.3, y: 0.9 }, tolerance)).toBeNull();
  });

  it('значок прибора главнее линии под ним', () => {
    const paint = data();
    if (paint === null) throw new Error('нет данных');
    // Прибор стоит на конце линии: (5000, 2000) мм -> (0.6, 0.625).
    const hit = hitTender(paint, { x: 0.6, y: 0.625 }, tolerance);
    expect(hit?.object.kind).toBe('element');
    expect(hit?.source.calcId).toBe('c1');
  });

  it('допуск по Y пересчитан в доли ширины листа', () => {
    const paint = data({ layers: [layer({ elements: [] })] });
    if (paint === null) throw new Error('нет данных');
    // Лист 1000 x 800: 0,01 ширины = 10 pt = 0,0125 высоты.
    expect(hitTender(paint, { x: 0.3, y: 0.625 + 0.011 }, tolerance)).not.toBeNull();
    expect(hitTender(paint, { x: 0.3, y: 0.625 + 0.02 }, tolerance)).toBeNull();
  });
});
