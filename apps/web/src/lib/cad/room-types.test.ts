import { describe, expect, it } from 'vitest';

import {
  FINISH_BASES,
  FINISH_BASE_LABELS,
  FINISH_WARNING_LABELS,
  ROOM_TYPE_GROUPS,
  ROOM_TYPE_LABELS,
  SURFACE_LABELS,
  SURFACES,
  roomTypeLabel,
  roomTypesForKind,
} from './room-types';

describe('типы помещений', () => {
  it('МОП и квартира: коды по группам, без пересечений', () => {
    const mop = roomTypesForKind('room_mop');
    const apartment = roomTypesForKind('room_apartment');
    expect(mop).toHaveLength(10);
    expect(apartment).toHaveLength(8);
    expect(mop).toContain('lift_hall');
    expect(apartment).toContain('kitchen');
    expect(mop.filter((code) => apartment.includes(code))).toEqual([]);
  });

  it('у двери и машино-места типа нет', () => {
    expect(roomTypesForKind('door')).toEqual([]);
    expect(roomTypesForKind('parking_space')).toEqual([]);
  });

  it('группы покрывают все подписанные коды', () => {
    const grouped = ROOM_TYPE_GROUPS.flatMap((group) => group.types).sort();
    expect(grouped).toEqual(Object.keys(ROOM_TYPE_LABELS).sort());
  });

  it('подписи по ТЗ', () => {
    expect(ROOM_TYPE_LABELS.airlock).toBe('Тамбур-шлюз');
    expect(ROOM_TYPE_LABELS.bath).toBe('Санузел/ванная');
    expect(ROOM_TYPE_LABELS.hall).toBe('Прихожая/коридор');
    expect(roomTypeLabel(null)).toBe('—');
    expect(roomTypeLabel('pui')).toBe('ПУИ');
  });

  it('поверхности и предупреждения подписаны', () => {
    expect(SURFACES.map((surface) => SURFACE_LABELS[surface])).toEqual(['Пол', 'Стены', 'Потолок']);
    expect('openings_not_subtracted' in FINISH_WARNING_LABELS).toBe(false);
    expect(FINISH_WARNING_LABELS.gap_unknown_height).toBe(
      'Проёмы без двери: высота неизвестна, участок не отделывается',
    );
    expect(FINISH_WARNING_LABELS.door_height_missing).toBe(
      'Высота двери не задана: дверной участок не отделывается',
    );
    expect(FINISH_WARNING_LABELS.windows_not_detected).toBe(
      'Окна не распознаны: оконные участки наружных стен не отделываются целиком, подоконная часть не учтена',
    );
    expect(FINISH_WARNING_LABELS.edges_unlinked).toBe(
      'Стены не привязаны к конструкциям: площадь по периметру зоны',
    );
    expect(Object.keys(FINISH_WARNING_LABELS)).toHaveLength(9);
  });

  it('основания стен подписаны', () => {
    expect(FINISH_BASES.map((base) => FINISH_BASE_LABELS[base])).toEqual([
      'Монолит',
      'Кладка',
      'ГКЛ',
    ]);
  });
});
