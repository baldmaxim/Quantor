import type { CadFrameRead, CadPreviewPathRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  bboxOfPaths,
  cadBboxToPageRect,
  cadToNormalized,
  cadToPagePt,
  cropToNormalized,
  frameOf,
  overlayPaths,
  standaloneSheet,
} from './frame';

const CONFIRMED: CadFrameRead = {
  confirmed: true,
  reason: null,
  units: 'mm',
  origin_pt: [100, 700],
  mm_per_pdf_point: 10,
};

const path = (points: number[], extra: Partial<CadPreviewPathRead> = {}): CadPreviewPathRead => ({
  layer: 0,
  closed: false,
  fill: false,
  points,
  ...extra,
});

describe('frameOf', () => {
  it('подтверждённый кадр превращается в числа', () => {
    expect(frameOf(CONFIRMED)).toEqual({ originX: 100, originY: 700, mmPerPt: 10 });
  });

  it.each([
    ['не подтверждён', { confirmed: false }],
    ['нет начала координат', { origin_pt: null }],
    ['нет коэффициента', { mm_per_pdf_point: null }],
    ['нулевой коэффициент', { mm_per_pdf_point: 0 }],
    ['отрицательный коэффициент', { mm_per_pdf_point: -1 }],
    ['единицы не мм', { units: 'm' }],
    ['единицы не указаны', { units: null }],
  ])('кадр отвергается: %s', (_name, patch) => {
    expect(frameOf({ ...CONFIRMED, ...patch })).toBeNull();
  });
});

describe('cadToPagePt', () => {
  const frame = { originX: 100, originY: 700, mmPerPt: 10 };

  it('начало DXF попадает в origin_pt', () => {
    expect(cadToPagePt(frame, 0, 0)).toEqual([100, 700]);
  });

  it('ось Y переворачивается: вверх в DXF - вверх на странице, то есть к меньшему y', () => {
    expect(cadToPagePt(frame, 0, 1000)).toEqual([100, 600]);
    expect(cadToPagePt(frame, 0, -500)).toEqual([100, 750]);
  });

  it('x растёт вправо и делится на мм в точке', () => {
    expect(cadToPagePt(frame, 250, 0)).toEqual([125, 700]);
  });

  it('единичный кадр: масштаб 1 мм на точку, начало в нуле', () => {
    expect(cadToPagePt({ originX: 0, originY: 0, mmPerPt: 1 }, 3, 4)).toEqual([3, -4]);
  });
});

describe('cadToNormalized', () => {
  it('делит на размер страницы без поворота', () => {
    const frame = { originX: 100, originY: 700, mmPerPt: 10 };
    const [nx, ny] = cadToNormalized(frame, { width: 1000, height: 800 }, 0, 0);
    expect(nx).toBeCloseTo(0.1, 12);
    expect(ny).toBeCloseTo(0.875, 12);
  });

  it('начало в левом верхнем углу и мм = pt даёт точку (x/w, -y/h)', () => {
    const frame = { originX: 0, originY: 0, mmPerPt: 1 };
    const [nx, ny] = cadToNormalized(frame, { width: 200, height: 100 }, 50, -25);
    expect(nx).toBeCloseTo(0.25, 12);
    expect(ny).toBeCloseTo(0.25, 12);
  });
});

describe('cadBboxToPageRect', () => {
  it('левый верхний угол первым, верх страницы - максимум Y DXF', () => {
    const frame = { originX: 100, originY: 700, mmPerPt: 10 };
    expect(cadBboxToPageRect(frame, [0, 0, 1000, 2000])).toEqual([100, 500, 200, 700]);
  });
});

describe('overlayPaths', () => {
  it('переводит точки и считает охват пути', () => {
    const frame = { originX: 0, originY: 100, mmPerPt: 1 };
    const [first] = overlayPaths(
      [path([0, 0, 100, 50], { layer: 2, closed: true, fill: true })],
      frame,
      { width: 200, height: 100 },
    );
    expect(first).toBeDefined();
    expect(first?.layer).toBe(2);
    expect(first?.closed).toBe(true);
    expect(first?.fill).toBe(true);
    expect(Array.from(first?.points ?? [])).toEqual([0, 1, 0.5, 0.5]);
    expect(first?.bounds).toEqual([0, 0.5, 0.5, 1]);
  });

  it('путь короче двух точек пропускается', () => {
    const frame = { originX: 0, originY: 0, mmPerPt: 1 };
    expect(overlayPaths([path([1, 2])], frame, { width: 1, height: 1 })).toEqual([]);
  });
});

describe('bboxOfPaths', () => {
  it('охват по всем путям', () => {
    expect(bboxOfPaths([path([0, 5, 10, -3]), path([20, 1, 4, 8])])).toEqual([0, -3, 20, 8]);
  });

  it('без точек охвата нет', () => {
    expect(bboxOfPaths([])).toBeNull();
  });
});

describe('standaloneSheet', () => {
  it('переворачивает Y: верх DXF - верх листа, длинная сторона 1000', () => {
    const sheet = standaloneSheet([path([0, 0, 2000, 1000])], [0, 0, 2000, 1000]);
    expect(sheet?.width).toBe(1000);
    expect(sheet?.height).toBe(500);
    // (0, 0) - низ DXF, значит нижний левый угол листа; (2000, 1000) - верхний правый.
    expect(Array.from(sheet?.paths[0]?.points ?? [])).toEqual([0, 1, 1, 0]);
  });

  it('охват берётся по путям, если сервер его не прислал', () => {
    const sheet = standaloneSheet([path([10, 10, 30, 20])], null);
    expect(sheet?.width).toBe(1000);
    expect(sheet?.height).toBe(500);
  });

  it('вырожденный охват не даёт нулевой лист', () => {
    const sheet = standaloneSheet([path([5, 0, 5, 100])], [5, 0, 5, 100]);
    expect(sheet?.width).toBeGreaterThan(0);
    expect(sheet?.height).toBe(1000);
  });

  it('точка вместо геометрии - листа нет', () => {
    expect(standaloneSheet([path([1, 1, 1, 1])], [1, 1, 1, 1])).toBeNull();
  });
});

describe('cropToNormalized', () => {
  it('делит на размер страницы', () => {
    expect(cropToNormalized([0, 0, 500, 400], { width: 1000, height: 800 })).toEqual([
      0, 0, 0.5, 0.5,
    ]);
  });

  it('перепутанные углы упорядочиваются', () => {
    expect(cropToNormalized([500, 400, 0, 0], { width: 1000, height: 800 })).toEqual([
      0, 0, 0.5, 0.5,
    ]);
  });

  it('не прямоугольник - null', () => {
    expect(cropToNormalized([1, 2, 3], { width: 10, height: 10 })).toBeNull();
    expect(cropToNormalized(null, { width: 10, height: 10 })).toBeNull();
    expect(cropToNormalized([0, 0, 1, 1], { width: 0, height: 10 })).toBeNull();
  });
});
