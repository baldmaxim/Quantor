import { describe, expect, it } from 'vitest';

import { element, layer, polyline } from './fixtures';
import { elementOf, placementOf, polylineOf, tenderFloor3dInput, type ITenderPlacement } from './floor3d';
import { sourceOf } from './geometry';
import { tenderInfo } from './info';

const SOURCE = sourceOf(layer());
const MOVED: ITenderPlacement = { offsetMm: [5000, 7000], rotationDeg: 0 };
const TURNED: ITenderPlacement = { offsetMm: [0, 0], rotationDeg: 90 };

describe('геометрия расчёта -> вход построителей 3D этажа', () => {
  it('на этаже вне здания вершины не меняются, слой - tender:<calc_id>', () => {
    const converted = polylineOf(polyline(), SOURCE, { offsetMm: [0, 0], rotationDeg: 0 });
    expect(converted.layer).toBe('tender:c1');
    expect(converted.pts).toEqual([
      [1000, 2000, 300],
      [5000, 2000, 300],
    ]);
    expect(converted.shape).toBe('round');
    expect(converted.dn_mm).toBe(20);
  });

  it('сдвиг этажа здания прибавляется к x и y, z (от чистого пола) не меняется', () => {
    const converted = polylineOf(polyline(), SOURCE, MOVED);
    expect(converted.pts[0]).toEqual([6000, 9000, 300]);
    expect(converted.pts[1]).toEqual([10000, 9000, 300]);
  });

  it('поворот этажа поворачивает вершины и ось, а у коробки меняет w и length', () => {
    const point = polylineOf(polyline({ pts: [[1000, 0, 50], [2000, 0, 50]] }), SOURCE, TURNED);
    expect(point.pts[0]?.[0]).toBeCloseTo(0);
    expect(point.pts[0]?.[1]).toBeCloseTo(1000);
    const box = elementOf(element({ axis: [1000, 0, 0] }), SOURCE, TURNED);
    expect(box.axis[0]).toBeCloseTo(0);
    expect(box.axis[1]).toBeCloseTo(1000);
    expect(box.w_mm).toBe(300);
    expect(box.length_mm).toBe(1500);
  });

  it('поворот идёт до сдвига: p = R(rotation_deg) · p_вида + offset_mm, z не меняется', () => {
    const placement: ITenderPlacement = { offsetMm: [5000, 7000], rotationDeg: 90 };
    const converted = polylineOf(polyline({ pts: [[1000, 2000, 300], [3000, 0, 50]] }), SOURCE, placement);
    // R(90): (x, y) -> (-y, x); потом + (5000, 7000).
    expect(converted.pts[0]?.[0]).toBeCloseTo(3000);
    expect(converted.pts[0]?.[1]).toBeCloseTo(8000);
    expect(converted.pts[0]?.[2]).toBe(300);
    expect(converted.pts[1]?.[0]).toBeCloseTo(5000);
    expect(converted.pts[1]?.[1]).toBeCloseTo(10000);
  });

  it('элемент без оси получает ось по умолчанию, без подтипа - пустой подтип', () => {
    const converted = elementOf(element({ axis: null, subtype: null }), SOURCE, MOVED);
    expect(converted.axis).toEqual([1000, 0, 0]);
    expect(converted.subtype).toBe('');
    expect(converted.pos).toEqual([10000, 9000, 100]);
  });

  it('объект хранит источник: плашка 3D - та же, что на плане', () => {
    const converted = polylineOf(polyline({ note: 'луч к конвектору' }), SOURCE, MOVED);
    expect(converted.tender).toBeDefined();
    const info = tenderInfo(converted.tender!);
    expect(info.rows).toContainEqual({ label: 'Версия', value: '№3 v3' });
    expect(info.rows).toContainEqual({ label: 'Примечание', value: 'луч к конвектору' });
  });

  it('вход собирается по нескольким расчётам: слой и токен цвета на расчёт', () => {
    const input = tenderFloor3dInput([
      layer(),
      layer({ calc_id: 'c2', version_id: 'v2', system: 'ventilation', polylines: [polyline({ id: 'V' })], elements: [] }),
    ]);
    expect(input.polylines.map((line) => line.layer)).toEqual(['tender:c1', 'tender:c2']);
    expect(input.elements).toHaveLength(1);
    expect(input.layerTokens).toEqual({
      'tender:c1': '--tender-sys-heating',
      'tender:c2': '--tender-sys-ventilation',
    });
  });

  it('постановка этажа читается из ответа здания', () => {
    expect(placementOf({ offset_mm: [10, 20], rotation_deg: 90 })).toEqual({
      offsetMm: [10, 20],
      rotationDeg: 90,
    });
    expect(placementOf({ offset_mm: [0, 0] }).rotationDeg).toBe(0);
  });
});
