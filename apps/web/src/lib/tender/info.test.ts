import { describe, expect, it } from 'vitest';

import { element, layer, polyline } from './fixtures';
import { sourceOf } from './geometry';
import { tenderInfo, versionTitle } from './info';

const SOURCE = sourceOf(layer());

describe('плашка объекта расчёта', () => {
  it('трасса: расчёт, версия, система, id, Ø, марка, квартира, примечание, длина', () => {
    const info = tenderInfo({
      source: SOURCE,
      object: {
        kind: 'polyline',
        data: polyline({ mark: 'Ст Т1', apt: '15.1', note: 'луч к конвектору КВ-2' }),
      },
    });
    expect(info.title).toBe('Трасса');
    const rows = Object.fromEntries(info.rows.map((row) => [row.label, row.value]));
    expect(rows['Расчёт']).toBe('Отопление жилой части');
    expect(rows['Версия']).toBe('№3 v3');
    expect(rows['Система']).toBe('Отопление');
    expect(rows['Объект']).toBe('T1-a');
    expect(rows['Диаметр']).toBe('Ø 20 мм');
    expect(rows['Марка']).toBe('Ст Т1');
    expect(rows['Квартира']).toBe('15.1');
    expect(rows['Примечание']).toBe('луч к конвектору КВ-2');
    expect(rows['Длина']).toBe('4 м');
  });

  it('короб: сечение, а не Ø', () => {
    const info = tenderInfo({
      source: SOURCE,
      object: {
        kind: 'polyline',
        data: polyline({ kind: 'duct', shape: 'rect', dn_mm: null, w_mm: 400, h_mm: 200 }),
      },
    });
    expect(info.title).toBe('Воздуховод');
    expect(info.rows).toContainEqual({ label: 'Сечение', value: '400×200 мм' });
  });

  it('прибор: размеры коробки и марка; устаревшая база помечена', () => {
    const info = tenderInfo({
      source: { ...SOURCE, baseStale: true },
      object: { kind: 'element', data: element() },
    });
    expect(info.title).toBe('Прибор');
    expect(info.rows).toContainEqual({ label: 'Размеры', value: '1500×300×110 мм' });
    expect(info.rows).toContainEqual({ label: 'Марка', value: 'КВ-2' });
    expect(info.rows.some((row) => row.label === 'База')).toBe(true);
  });

  it('подпись версии', () => {
    expect(versionTitle({ number: 3, label: 'v3' })).toBe('№3 v3');
  });
});
