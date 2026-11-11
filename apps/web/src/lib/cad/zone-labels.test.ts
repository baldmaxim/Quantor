import { describe, expect, it } from 'vitest';

import { doorLabelFits, fitRoomLabel, roomLabelLines, type IZoneLabelOptions } from './zone-labels';

// Ширина текста - 6 px на символ.
const measure = (text: string) => text.length * 6;

const zone = {
  kind: 'room_apartment' as const,
  apartment_no: '12',
  room_mark: '3',
  name: 'Кухня',
  area_m2: 10.5,
  width_m: null,
  door_height_mm: null,
};
const DEFAULTS: IZoneLabelOptions = { apartment: false, mark: true, name: false, area: true };

describe('roomLabelLines', () => {
  it('по умолчанию: марка и площадь', () => {
    expect(roomLabelLines(zone, DEFAULTS)).toEqual({ head: '3', area: '10,50 м²' });
  });

  it('все части через « · »', () => {
    expect(roomLabelLines(zone, { apartment: true, mark: true, name: true, area: true }).head).toBe(
      'кв. 12 · 3 · Кухня',
    );
  });

  it('нет марки - подставляется название', () => {
    expect(roomLabelLines({ ...zone, room_mark: null }, DEFAULTS).head).toBe('Кухня');
  });

  it('пустые строки пусты', () => {
    const lines = roomLabelLines({ ...zone, room_mark: null, name: null, area_m2: null }, DEFAULTS);
    expect(lines).toEqual({ head: '', area: '' });
  });
});

describe('fitRoomLabel', () => {
  const lines = { head: '3 · Кухня', area: '10,50 м²' };

  it('влезает - обе строки', () => {
    expect(fitRoomLabel(lines, { width: 200, height: 100 }, measure)).toEqual([
      lines.head,
      lines.area,
    ]);
  });

  it('строка 1 не влезает - только площадь', () => {
    // «3 · Кухня» = 54 px, «10,50 м²» = 48 px: охват 55 px даёт предел 49,5.
    expect(fitRoomLabel(lines, { width: 55, height: 100 }, measure)).toEqual([lines.area]);
  });

  it('не влезает по высоте две строки - только площадь', () => {
    expect(fitRoomLabel(lines, { width: 200, height: 20 }, measure)).toEqual([lines.area]);
  });

  it('не влезает ничего - без подписи', () => {
    expect(fitRoomLabel(lines, { width: 20, height: 10 }, measure)).toEqual([]);
  });

  it('пустая первая строка - только площадь', () => {
    expect(
      fitRoomLabel({ head: '', area: lines.area }, { width: 200, height: 100 }, measure),
    ).toEqual([lines.area]);
  });

  it('обе пусты - ничего', () => {
    expect(fitRoomLabel({ head: '', area: '' }, { width: 200, height: 100 }, measure)).toEqual([]);
  });
});

describe('doorLabelFits', () => {
  it('влезает в длину проёма', () => {
    expect(doorLabelFits('900 × 2100', 80, measure)).toBe(true);
    expect(doorLabelFits('900 × 2100', 40, measure)).toBe(false);
  });
});
