import { describe, expect, it } from 'vitest';

import { floorTitleFileName, floorsText, formatFloorTitle, formatFloorTitleFull } from './floor-title';

describe('formatFloorTitle', () => {
  it('полная подпись: корпус, секция, этаж', () => {
    expect(formatFloorTitle({ corps: '9', section: '3', floors: ['14'] }, 'Лист 82')).toBe(
      'К9 · С3 · 14 эт.',
    );
  });

  it('несколько этажей подряд - диапазон, иначе перечисление', () => {
    expect(formatFloorTitle({ floors: ['2', '3', '4', '5'] }, 'x')).toBe('2–5 эт.');
    expect(formatFloorTitle({ floors: ['2', '4'] }, 'x')).toBe('2, 4 эт.');
    expect(floorsText(['5', '3', '4'])).toBe('3–5');
  });

  it('только этаж', () => {
    expect(formatFloorTitle({ floors: ['14'] }, 'Лист 82')).toBe('14 эт.');
  });

  it('пусто - прежняя подпись листа', () => {
    expect(formatFloorTitle(null, 'Лист 82')).toBe('Лист 82');
    expect(formatFloorTitle(undefined, 'Лист 82')).toBe('Лист 82');
    expect(formatFloorTitle({ corps: null, section: null, floors: [], text: null }, 'Лист 82')).toBe(
      'Лист 82',
    );
  });
});

describe('formatFloorTitleFull', () => {
  it('полная форма для подсказки', () => {
    expect(formatFloorTitleFull({ corps: '9', section: '3', floors: ['14'] })).toBe(
      'Корпус 9, секция 3, 14 этаж',
    );
    expect(formatFloorTitleFull({ floors: ['2', '3'] })).toBe('2–3 этажи');
    expect(formatFloorTitleFull(null)).toBeNull();
    expect(formatFloorTitleFull({ floors: [] })).toBeNull();
  });
});

describe('floorTitleFileName', () => {
  it('латиница без пробелов', () => {
    expect(floorTitleFileName({ corps: '9', section: '3', floors: ['14'] })).toBe('floor3d_K9_S3_14.dxf');
    expect(floorTitleFileName({ corps: '9А', section: '3', floors: ['2', '3', '4'] })).toBe(
      'floor3d_K9A_S3_2-4.dxf',
    );
    expect(floorTitleFileName({ floors: ['2', '4'] })).toBe('floor3d_2_4.dxf');
  });

  it('нет заголовка - null: имя остаётся прежним', () => {
    expect(floorTitleFileName(null)).toBeNull();
    expect(floorTitleFileName({ floors: [] })).toBeNull();
  });
});
