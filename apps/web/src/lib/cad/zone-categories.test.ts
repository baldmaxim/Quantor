import { describe, expect, it } from 'vitest';

import type { RoomType } from './room-types';
import {
  presentZoneCategories,
  zoneCategory,
  zoneCategoryColorVar,
  zoneCategoryToken,
  type ZoneCategory,
} from './zone-categories';

const room = (name: string | null) => ({ kind: 'room_apartment' as const, name, room_type: null });

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
    expect(zoneCategory({ kind: 'room_mop', name: 'Кухня', room_type: null })).toBe('mop');
    expect(zoneCategory({ kind: 'door', name: null, room_type: null })).toBe('door');
  });
});

describe('МОП по подтипу', () => {
  const mop = (room_type: RoomType | null, name: string | null = null) => ({
    kind: 'room_mop' as const,
    name,
    room_type,
  });
  const byType: readonly (readonly [RoomType, ZoneCategory])[] = [
    ['lift_hall', 'mop_lift'],
    ['vestibule', 'mop_vestibule'],
    ['airlock', 'mop_vestibule'],
    ['corridor', 'mop_corridor'],
    ['stair', 'mop_stair'],
    ['tech', 'mop'],
    ['mop_other', 'mop'],
  ];
  it.each(byType)('room_type %s -> %s', (type, expected) => {
    expect(zoneCategory(mop(type, 'Кухня'))).toBe(expected);
  });

  const byName: readonly (readonly [string | null, ZoneCategory])[] = [
    ['Лифтовой холл', 'mop_lift'],
    ['Тамбур-шлюз', 'mop_vestibule'],
    ['Тамбур', 'mop_vestibule'],
    ['Лестничная клетка', 'mop_stair'],
    ['Коридор', 'mop_corridor'],
    ['Холл', 'mop_corridor'],
    ['Мусорокамера', 'mop'],
    ['Что-то', 'mop'],
    [null, 'mop'],
  ];
  it.each(byName)('room_type=null, «%s» -> %s', (name, expected) => {
    expect(zoneCategory(mop(null, name))).toBe(expected);
  });

  it('панель: раздельные строки в порядке, МОП после «Прочих» и до дверей', () => {
    expect(
      presentZoneCategories([
        { kind: 'door', name: null, room_type: null },
        mop('stair'),
        mop('lift_hall'),
        mop('lift_hall'),
        mop('pui'),
        room('Кухня'),
      ]),
    ).toEqual([
      { category: 'kitchen', count: 1 },
      { category: 'mop_lift', count: 2 },
      { category: 'mop_stair', count: 1 },
      { category: 'mop', count: 1 },
      { category: 'door', count: 1 },
    ]);
  });

  it('токен цвета: подчёркивание -> дефис', () => {
    expect(zoneCategoryToken('mop_lift')).toBe('--cad-zone-mop-lift');
    expect(zoneCategoryToken('mop')).toBe('--cad-zone-mop');
    expect(zoneCategoryColorVar('mop_corridor')).toBe('var(--cad-zone-mop-corridor)');
  });
});

describe('presentZoneCategories', () => {
  it('считает зоны и держит порядок панели', () => {
    const result = presentZoneCategories([
      { kind: 'door', name: null, room_type: null },
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
    expect(zoneCategory({ kind: 'parking_space', name: 'Кухня', room_type: null })).toBe('parking');
    expect(
      presentZoneCategories([
        { kind: 'parking_space', name: null, room_type: null },
        { kind: 'parking_space', name: null, room_type: null },
      ]),
    ).toEqual([{ category: 'parking', count: 2 }]);
  });
});
