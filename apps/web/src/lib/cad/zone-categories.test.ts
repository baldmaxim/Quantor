import { describe, expect, it } from 'vitest';

import { presentZoneCategories, zoneCategory, type ZoneCategory } from './zone-categories';

const room = (name: string | null) => ({ kind: 'room_apartment' as const, name });

describe('zoneCategory', () => {
  const cases: readonly (readonly [string, ZoneCategory])[] = [
    ['Санузел', 'wet'],
    ['С/У', 'wet'],
    ['Ванная', 'wet'],
    ['Кухня', 'kitchen'],
    ['Кухня-гостиная', 'kitchen'],
    ['Столовая', 'kitchen'],
    ['Жилая комната', 'living'],
    ['Спальня', 'living'],
    ['Прихожая', 'hall'],
    ['Коридор', 'hall'],
    ['Гардеробная', 'storage'],
    ['Кладовая', 'storage'],
    ['Лоджия', 'outdoor'],
    ['Балкон', 'outdoor'],
    ['Что-то иное', 'other'],
  ];
  it.each(cases)('«%s» -> %s', (name, expected) => {
    expect(zoneCategory(room(name))).toBe(expected);
  });

  it('ё приравнена к е, регистр не важен', () => {
    expect(zoneCategory(room('ТАМБУР'))).toBe('hall');
    expect(zoneCategory(room('Ёмкость'))).toBe('other');
  });

  it('без названия - прочие', () => {
    expect(zoneCategory(room(null))).toBe('other');
  });

  it('МОП и дверь - свои категории независимо от названия', () => {
    expect(zoneCategory({ kind: 'room_mop', name: 'Кухня' })).toBe('mop');
    expect(zoneCategory({ kind: 'door', name: null })).toBe('door');
  });
});

describe('presentZoneCategories', () => {
  it('считает зоны и держит порядок панели', () => {
    const result = presentZoneCategories([
      { kind: 'door', name: null },
      room('Кухня'),
      room('Санузел'),
      room('Кухня'),
    ]);
    expect(result).toEqual([
      { category: 'wet', count: 1 },
      { category: 'kitchen', count: 2 },
      { category: 'door', count: 1 },
    ]);
  });
});

describe('машино-место', () => {
  it('своя категория «parking»', () => {
    expect(zoneCategory({ kind: 'parking_space', name: 'Кухня' })).toBe('parking');
    expect(
      presentZoneCategories([
        { kind: 'parking_space', name: null },
        { kind: 'parking_space', name: null },
      ]),
    ).toEqual([{ category: 'parking', count: 2 }]);
  });
});
