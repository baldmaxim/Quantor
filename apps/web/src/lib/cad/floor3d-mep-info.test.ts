import { describe, expect, it } from 'vitest';

import { elementInfo, mepInfoOf, polylineLengthM, routeInfo } from './floor3d-mep-info';
import { mepElementTitle } from './floor3d-mep-labels';
import type { IFloor3dRoutePolyline } from './floor3d-routes';

const value = (info: { rows: readonly { label: string; value: string }[] }, label: string): string | undefined =>
  info.rows.find((row) => row.label === label)?.value;

const riser: IFloor3dRoutePolyline = {
  layer: 'M-VK-K1',
  pts: [
    [0, 0, 0],
    [0, 0, 2000],
    [3000, 0, 2000],
  ],
  shape: 'round',
  dn_mm: 110,
  dn_source: 'registry',
  mark: 'Ст К1-3',
  kind: 'riser',
  insulation_mm: 0,
  slope: 0.02,
  apt: '12',
};

describe('плашка трассы', () => {
  it('система, вид, марка, Ø с источником, изоляция, уклон, квартира, длина и отметки', () => {
    const info = routeInfo(riser);
    expect(info.title).toBe('Стояк');
    expect(value(info, 'Система')).toBe('Канализация К1');
    expect(value(info, 'Вид')).toBe('Стояк');
    expect(value(info, 'Марка')).toBe('Ст К1-3');
    expect(value(info, 'Диаметр')).toBe('Ø 110 мм');
    expect(value(info, 'Источник Ø')).toBe('по реестру');
    expect(value(info, 'Изоляция')).toBe('нет');
    expect(value(info, 'Уклон')).toContain('0,02');
    expect(value(info, 'Квартира')).toBe('12');
    expect(value(info, 'Длина')).toBe('5 м');
    // Низ и верх - по крайним точкам плюс половина Ø.
    expect(value(info, 'Низ от чистого пола, м')).toBe('-0,06');
    expect(value(info, 'Верх от чистого пола, м')).toBe('2,06');
  });

  it('источники Ø: по линии, по умолчанию, неизвестный и null', () => {
    const source = (dn_source: IFloor3dRoutePolyline['dn_source']) =>
      value(routeInfo({ ...riser, dn_source }), 'Источник Ø');
    expect(source('line')).toBe('по линии');
    expect(source('rule')).toBe('по умолчанию');
    expect(source(null)).toBe('не определён');
    expect(source(undefined)).toBe('не определён');
  });

  it('круглая без Ø - «Ø не определён», условный Ø для отрисовки не показывается', () => {
    const info = routeInfo({ ...riser, dn_mm: null, dn_source: 'rule' });
    expect(value(info, 'Диаметр')).toBe('Ø не определён');
    expect(value(info, 'Источник Ø')).toBe('не определён');
    expect(info.rows.some((row) => row.value.includes('20 мм'))).toBe(false);
  });

  it('воздуховод: сечение w×h и изоляция', () => {
    const info = routeInfo({
      layer: 'M-OV-VMOP',
      pts: [[0, 0, 2500], [1000, 0, 2500]],
      shape: 'rect',
      w_mm: 400,
      h_mm: 200,
      dn_source: 'rule',
      insulation_mm: 20,
      kind: 'route',
    });
    expect(value(info, 'Сечение')).toBe('400×200 мм');
    expect(value(info, 'Источник сечения')).toBe('по умолчанию');
    expect(value(info, 'Изоляция')).toBe('20 мм');
    expect(info.title).toBe('Трасса');
  });

  it('файл v1 без новых полей: без вида, марки, квартиры и сечения', () => {
    const info = routeInfo({ layer: 'M-OV-T1', pts: [[0, 0, 0], [1000, 0, 0]] });
    expect(info.title).toBe('Трасса');
    expect(value(info, 'Вид')).toBeUndefined();
    expect(value(info, 'Марка')).toBeUndefined();
    expect(value(info, 'Диаметр')).toBeUndefined();
    expect(value(info, 'Длина')).toBe('1 м');
  });

  it('длина - сумма 3D-сегментов', () => {
    expect(polylineLengthM([[0, 0, 0], [3000, 4000, 0], [3000, 4000, 12000]])).toBeCloseTo(17, 9);
    expect(polylineLengthM([[0, 0, 0]])).toBe(0);
  });
});

describe('плашка элемента', () => {
  it('названия по-русски для фасонины, арматуры, гильз и приборов', () => {
    expect(mepElementTitle('fitting', 'tee')).toBe('Тройник');
    expect(mepElementTitle('fitting', 'cleanout')).toBe('Ревизия');
    expect(mepElementTitle('valve', 'ball_valve')).toBe('Кран шаровой');
    expect(mepElementTitle('valve', 'fire_damper')).toBe('ОЗК');
    expect(mepElementTitle('valve', 'smoke_damper')).toBe('Клапан дымоудаления');
    expect(mepElementTitle('sleeve', 'wall')).toBe('Гильза в стене');
    expect(mepElementTitle('sleeve', 'slab')).toBe('Гильза в перекрытии');
    expect(mepElementTitle('terminal', 'ac_unit')).toBe('Внутренний блок кондиционера');
    expect(mepElementTitle('terminal', 'ac_inlet')).toBe('Ввод фреона');
    // Незнакомый подтип не выдумывается.
    expect(mepElementTitle('terminal', 'bidet')).toBe('Прибор (bidet)');
  });

  it('прибор: система, размеры корпуса, квартира, марка', () => {
    const info = elementInfo({
      type: 'terminal',
      subtype: 'wc',
      layer: 'M-SAN-WC',
      pos: [0, 0, 0],
      axis: [0, 0, 1000],
      w_mm: 360,
      length_mm: 600,
      h_mm: 800,
      apt: '5',
      mark: 'У-1',
    });
    expect(info.title).toBe('Унитаз');
    expect(value(info, 'Система')).toBe('Унитаз');
    expect(value(info, 'Размеры')).toBe('360×600×800 мм');
    expect(value(info, 'Квартира')).toBe('5');
    expect(value(info, 'Марка')).toBe('У-1');
  });

  it('ороситель: Ø и высота; арматура: Ø; ОЗК: сечение', () => {
    const sprinkler = elementInfo({
      type: 'terminal', subtype: 'sprinkler', layer: 'M-PT-AUP', pos: [0, 0, 0], axis: [0, 0, 1000], dn_mm: 15, h_mm: 50,
    });
    expect(value(sprinkler, 'Диаметр')).toBe('Ø 15 мм');
    expect(value(sprinkler, 'Высота')).toBe('50 мм');
    const valve = elementInfo({ type: 'valve', subtype: 'ball_valve', layer: 'M-VK-V1', pos: [0, 0, 0], axis: [1000, 0, 0], dn_mm: 25 });
    expect(valve.title).toBe('Кран шаровой');
    expect(value(valve, 'Диаметр')).toBe('Ø 25 мм');
    const damper = elementInfo({ type: 'valve', subtype: 'fire_damper', layer: 'M-OV-VMOP', pos: [0, 0, 0], axis: [1000, 0, 0], w_mm: 400, h_mm: 200 });
    expect(value(damper, 'Сечение')).toBe('400×200 мм');
  });

  it('ЭОМ и СС: прибор - по названию генератора и размеру короба, линия - по изделию', () => {
    const panel = elementInfo({
      type: 'device', subtype: 'panel_floor', layer: 'E-EO-DEV', pos: [0, 0, 0], axis: [0, 1000, 0],
      w_mm: 800, h_mm: 1400, d_mm: 160, name: 'ЩЭ 1400×800',
    });
    expect(panel.title).toBe('ЩЭ 1400×800');
    expect(value(panel, 'Система')).toBe('Щиты и приборы ЭОМ');
    expect(value(panel, 'Размеры')).toBe('800×1400×160 мм');
    const unnamed = elementInfo({ type: 'box', subtype: 'junction', layer: 'E-EO-DEV', pos: [0, 0, 0], axis: [0, 0, -1000] });
    expect(unnamed.title).toBe('junction');
    const tray = routeInfo({
      layer: 'E-SS-TRAY', pts: [[0, 0, 2800], [1000, 0, 2800]], shape: 'rect', w_mm: 100, h_mm: 50, item: 'Лоток СБ 100×50',
    });
    expect(tray.title).toBe('Лоток СБ 100×50');
    expect(value(tray, 'Система')).toBe('Лоток СБ');
    expect(value(tray, 'Сечение')).toBe('100×50 мм');
    expect(value(tray, 'Источник сечения')).toBeUndefined();
    expect(value(tray, 'Изоляция')).toBeUndefined();
  });

  it('mepInfoOf: по индексу; нет в данных - null', () => {
    const data = { polylines: [riser], elements: [] };
    expect(mepInfoOf({ kind: 'route', index: 0 }, data)?.title).toBe('Стояк');
    expect(mepInfoOf({ kind: 'route', index: 1 }, data)).toBeNull();
    expect(mepInfoOf({ kind: 'element', index: 0 }, data)).toBeNull();
  });
});
