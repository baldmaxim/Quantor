import type { CadZoneRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  CLOSE_RADIUS_PX,
  clickClosesPolygon,
  doorSizeText,
  formatZoneArea,
  groupZones,
  parseDoorHeight,
  pointsToPairs,
  sumAreas,
  zoneCanvasLabel,
  zoneCentroid,
  zoneInputProblem,
  zoneToolMode,
} from './zones';
import {
  applyToolEvent,
  initialToolState,
  type ToolEvent,
  type ToolState,
} from '@/lib/viewer/tool-machine';

const zone = (patch: Partial<CadZoneRead>): CadZoneRead => ({
  id: 'z',
  revision_id: 'r',
  page_index: 0,
  kind: 'room_apartment',
  apartment_no: '10',
  room_mark: null,
  name: null,
  points: [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ],
  door_height_mm: null,
  area_m2: 10,
  perimeter_m: 12,
  width_m: null,
  calibration_missing: false,
  geometry_issue: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  ...patch,
});

describe('сумма и группировка', () => {
  it('складывает определённые площади и помечает неполную сумму', () => {
    const sum = sumAreas([zone({ area_m2: 10 }), zone({ area_m2: 2.5 }), zone({ area_m2: null })]);
    expect(sum).toEqual({ areaM2: 12.5, partial: true });
  });

  it('без единой определённой площади сумма не определена, а не 0', () => {
    const sum = sumAreas([zone({ area_m2: null, calibration_missing: true })]);
    expect(sum.areaM2).toBeNull();
    expect(formatZoneArea(sum.areaM2)).toBe('нет калибровки');
    expect(sumAreas([]).areaM2).toBeNull();
  });

  it('группирует квартиры по номеру в естественном порядке, МОП и двери отдельно', () => {
    const groups = groupZones([
      zone({ id: 'a', apartment_no: '10', area_m2: 5 }),
      zone({ id: 'b', apartment_no: '9', area_m2: 7 }),
      zone({ id: 'c', apartment_no: '10', area_m2: 3 }),
      zone({ id: 'd', kind: 'room_mop', apartment_no: null, area_m2: 20 }),
      zone({
        id: 'e',
        kind: 'door',
        apartment_no: null,
        area_m2: null,
        width_m: 0.9,
        door_height_mm: 2100,
      }),
    ]);
    expect(groups.apartments.map((group) => group.apartmentNo)).toEqual(['9', '10']);
    expect(groups.apartments[1]?.areaM2).toBe(8);
    expect(groups.apartments[1]?.zones.map((item) => item.id)).toEqual(['a', 'c']);
    expect(groups.mop.areaM2).toBe(20);
    expect(groups.doors.map((item) => item.id)).toEqual(['e']);
  });
});

describe('подписи', () => {
  it('подпись помещения: № квартиры, марка, площадь', () => {
    const text = zoneCanvasLabel(zone({ room_mark: '3-1/6', area_m2: 12.345 }));
    expect(text).toContain('кв. 10');
    expect(text).toContain('3-1/6');
    expect(text).toContain('м²');
  });

  it('у помещения без площади подписи величины нет', () => {
    expect(zoneCanvasLabel(zone({ area_m2: null }))).toBe('кв. 10');
  });

  it('размер двери: ширина в мм × высота; без калибровки ширина не определена', () => {
    expect(doorSizeText(zone({ kind: 'door', width_m: 0.9, door_height_mm: 2100 }))).toBe(
      '900 × 2100 мм',
    );
    expect(doorSizeText(zone({ kind: 'door', width_m: null, door_height_mm: 2100 }))).toContain(
      'нет калибровки',
    );
  });
});

describe('геометрия', () => {
  it('центр тяжести прямоугольника - его центр', () => {
    const center = zoneCentroid([
      [0.2, 0.2],
      [0.6, 0.2],
      [0.6, 0.4],
      [0.2, 0.4],
    ]);
    expect(center.x).toBeCloseTo(0.4);
    expect(center.y).toBeCloseTo(0.3);
  });

  it('у вырожденного контура берётся среднее вершин', () => {
    const center = zoneCentroid([
      [0, 0],
      [0.5, 0.5],
      [1, 1],
    ]);
    expect(center).toEqual({ x: 0.5, y: 0.5 });
  });
});

describe('ввод', () => {
  it('квартира требует номер, дверь - высоту из допустимого диапазона', () => {
    expect(
      zoneInputProblem({ kind: 'room_apartment', apartmentNo: ' ', doorHeight: '2100' }),
    ).not.toBeNull();
    expect(
      zoneInputProblem({ kind: 'room_apartment', apartmentNo: '12', doorHeight: '' }),
    ).toBeNull();
    expect(zoneInputProblem({ kind: 'room_mop', apartmentNo: '', doorHeight: '' })).toBeNull();
    expect(zoneInputProblem({ kind: 'door', apartmentNo: '', doorHeight: '1000' })).not.toBeNull();
    expect(zoneInputProblem({ kind: 'door', apartmentNo: '', doorHeight: '4000' })).not.toBeNull();
    expect(zoneInputProblem({ kind: 'door', apartmentNo: '', doorHeight: 'abc' })).not.toBeNull();
    expect(zoneInputProblem({ kind: 'door', apartmentNo: '', doorHeight: '2100' })).toBeNull();
  });

  it('высота: только целое число', () => {
    expect(parseDoorHeight(' 2100 ')).toBe(2100);
    expect(parseDoorHeight('21.5')).toBeNull();
    expect(parseDoorHeight('')).toBeNull();
  });
});

const run = (state: ToolState, events: readonly ToolEvent[]) => {
  let current = state;
  const completed: (readonly { x: number; y: number }[])[] = [];
  for (const event of events) {
    const transition = applyToolEvent(current, event);
    current = transition.state;
    if (transition.completed) completed.push(transition.completed.points);
  }
  return { state: current, completed };
};

const click = (x: number, y: number): ToolEvent => ({ type: 'pointerDown', point: { x, y } });

describe('машина рисования зоны', () => {
  it('режим по виду: помещение - многоугольник, дверь - линия', () => {
    expect(zoneToolMode('room_apartment')).toBe('polygon');
    expect(zoneToolMode('room_mop')).toBe('polygon');
    expect(zoneToolMode('door')).toBe('line');
  });

  it('помещение: Enter с менее чем тремя вершинами не завершает, с тремя - отдаёт контур', () => {
    const start = initialToolState('polygon');
    const two = run(start, [click(0.1, 0.1), click(0.4, 0.1), { type: 'finish' }]);
    expect(two.completed).toEqual([]);
    expect(two.state.points).toHaveLength(2);

    const three = run(start, [
      click(0.1, 0.1),
      click(0.4, 0.1),
      click(0.4, 0.4),
      { type: 'finish' },
    ]);
    expect(three.completed).toHaveLength(1);
    expect(pointsToPairs(three.completed[0] ?? [])).toEqual([
      [0.1, 0.1],
      [0.4, 0.1],
      [0.4, 0.4],
    ]);
    expect(three.state.points).toEqual([]);
  });

  it('дверь завершается второй точкой', () => {
    const result = run(initialToolState('line'), [click(0.1, 0.5), click(0.2, 0.5)]);
    expect(result.completed).toHaveLength(1);
    expect(result.completed[0]).toHaveLength(2);
  });

  it('Backspace убирает последнюю вершину, Esc - весь черновик', () => {
    const start = initialToolState('polygon');
    const back = run(start, [click(0.1, 0.1), click(0.4, 0.1), { type: 'backspace' }]);
    expect(back.state.points).toHaveLength(1);
    const cancelled = run(start, [click(0.1, 0.1), click(0.4, 0.1), { type: 'cancel' }]);
    expect(cancelled.state.points).toEqual([]);
    expect(cancelled.completed).toEqual([]);
  });

  it('точка за пределами листа вершиной не становится', () => {
    const result = run(initialToolState('polygon'), [click(1.2, 0.5)]);
    expect(result.state.points).toEqual([]);
  });
});

describe('замыкание щелчком', () => {
  const vertices = [
    { x: 100, y: 100 },
    { x: 200, y: 100 },
    { x: 200, y: 200 },
  ];

  it('щелчок у первой вершины замыкает, если вершин хотя бы три', () => {
    expect(clickClosesPolygon('polygon', vertices, { x: 104, y: 103 })).toBe(true);
    expect(clickClosesPolygon('polygon', vertices.slice(0, 2), { x: 100, y: 100 })).toBe(false);
  });

  it('щелчок у последней вершины (вторая половина двойного щелчка) замыкает', () => {
    expect(clickClosesPolygon('polygon', vertices, { x: 201, y: 199 })).toBe(true);
  });

  it('щелчок вдали от вершин и любой щелчок у двери не замыкает', () => {
    expect(clickClosesPolygon('polygon', vertices, { x: 150, y: 150 })).toBe(false);
    expect(clickClosesPolygon('polygon', vertices, { x: 100 + CLOSE_RADIUS_PX + 1, y: 100 })).toBe(
      false,
    );
    expect(clickClosesPolygon('line', vertices, { x: 100, y: 100 })).toBe(false);
  });
});
