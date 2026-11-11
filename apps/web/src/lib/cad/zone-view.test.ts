import { describe, expect, it } from 'vitest';

import { apartmentColorIndex, DEFAULT_ZONE_VIEW, parseZoneView } from './zone-view';

describe('parseZoneView', () => {
  it('пусто и мусор - умолчание', () => {
    expect(parseZoneView(null)).toBe(DEFAULT_ZONE_VIEW);
    expect(parseZoneView('{не json')).toBe(DEFAULT_ZONE_VIEW);
    expect(parseZoneView('42')).toBe(DEFAULT_ZONE_VIEW);
  });

  it('читает сохранённое, лишние категории отбрасывает', () => {
    const view = parseZoneView(
      JSON.stringify({
        colorMode: 'apartment',
        hidden: ['wet', 'ерунда'],
        labelsOn: false,
        labels: { name: true },
      }),
    );
    expect(view.colorMode).toBe('apartment');
    expect([...view.hidden]).toEqual(['wet']);
    expect(view.labelsOn).toBe(false);
    expect(view.labels).toEqual({ apartment: false, mark: true, name: true, area: true });
  });
});

describe('apartmentColorIndex', () => {
  const apt = (apartment_no: string | null) => ({ kind: 'room_apartment' as const, apartment_no });

  it('естественная сортировка и цикл по палитре', () => {
    const map = apartmentColorIndex([apt('10'), apt('2'), apt('2'), apt(null)]);
    expect(map.get('2')).toBe(0);
    expect(map.get('10')).toBe(1);
    expect(map.size).toBe(2);
    const many = apartmentColorIndex(Array.from({ length: 9 }, (_, i) => apt(String(i + 1))));
    expect(many.get('9')).toBe(0);
  });
});
