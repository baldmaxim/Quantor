import type { CadZoneRead } from '@quantor/api-client';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import type { ToolMode } from '@/lib/viewer/tool-machine';

/**
 * Зоны листа во вкладке CAD: помещения квартир, помещения МОП, двери, машино-места паркинга.
 *
 * Чистая логика без DOM и сети: подписи, группировка с суммами, правила ввода и решения
 * машины рисования. Площадь, периметр и ширину считает сервер; здесь они только складываются
 * и показываются. Не определено (нет калибровки) - не ноль.
 */

export type ZoneKind = CadZoneRead['kind'];

export const ZONE_KINDS: readonly ZoneKind[] = [
  'room_apartment',
  'room_mop',
  'door',
  'parking_space',
];

export const ZONE_KIND_LABELS: Readonly<Record<ZoneKind, string>> = {
  room_apartment: 'Помещение квартиры',
  room_mop: 'МОП',
  door: 'Дверь',
  parking_space: 'Машино-место',
};

/** Тип машино-места по легенде листа. */
export type ParkingType = NonNullable<CadZoneRead['parking_type']>;

export const PARKING_TYPES: readonly ParkingType[] = [
  'permanent',
  'temporary',
  'guest',
  'medium',
  'medium_guest',
  'large',
  'large_guest',
  'mgn_m1_3',
  'mgn_m4',
  'unknown',
];

export const PARKING_TYPE_LABELS: Readonly<Record<ParkingType, string>> = {
  permanent: 'Постоянное хранение',
  temporary: 'Временное хранение',
  guest: 'Гостевое',
  medium: 'Medium',
  medium_guest: 'Medium гостевое',
  large: 'Large',
  large_guest: 'Large гостевое',
  mgn_m1_3: 'МГН М1–3',
  mgn_m4: 'МГН М4',
  unknown: 'Тип не определён',
};

/** Краткий тип для подписи на плане: места мелкие, полное название не поместится. */
export const PARKING_TYPE_SHORT: Readonly<Record<ParkingType, string>> = {
  permanent: 'Пост.',
  temporary: 'Врем.',
  guest: 'Гост.',
  medium: 'M',
  medium_guest: 'M гост.',
  large: 'L',
  large_guest: 'L гост.',
  mgn_m1_3: 'МГН 1–3',
  mgn_m4: 'МГН 4',
  unknown: '?',
};

export const DEFAULT_PARKING_TYPE: ParkingType = 'permanent';

/** Пределы высоты проёма на сервере. */
export const DOOR_HEIGHT_MIN_MM = 1500;
export const DOOR_HEIGHT_MAX_MM = 3500;
export const DEFAULT_DOOR_HEIGHT_MM = 2100;

export const NO_CALIBRATION_TEXT = 'нет калибровки';

export const isRoomKind = (kind: ZoneKind): boolean => kind !== 'door';

/** Марка помещения есть у квартир и МОП; у машино-места её нет. */
export const hasRoomMark = (kind: ZoneKind): boolean =>
  kind === 'room_apartment' || kind === 'room_mop';

// --- форматирование ---

const AREA_FORMAT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const WIDTH_FORMAT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Площадь в м²; `null` - не определено. */
export const formatZoneArea = (value: number | null): string =>
  value === null ? NO_CALIBRATION_TEXT : `${AREA_FORMAT.format(value)} м²`;

/** Длина в м; `null` - не определено. */
export const formatZoneLength = (value: number | null): string =>
  value === null ? NO_CALIBRATION_TEXT : `${WIDTH_FORMAT.format(value)} м`;

/** Почему у зоны нет величины: нет калибровки или контур недействителен. */
export const zoneUndefinedReason = (zone: CadZoneRead): string | null => {
  if (zone.geometry_issue !== null) return 'контур недействителен';
  if (zone.calibration_missing) return NO_CALIBRATION_TEXT;
  return null;
};

// --- геометрия ---

/** Центр тяжести многоугольника; для вырожденного контура - среднее вершин. */
export const zoneCentroid = (points: readonly (readonly [number, number])[]): NormalizedPoint => {
  const count = points.length;
  if (count === 0) return { x: 0, y: 0 };
  let twiceArea = 0;
  let cx = 0;
  let cy = 0;
  for (let index = 0; index < count; index += 1) {
    const [x0, y0] = points[index] as readonly [number, number];
    const [x1, y1] = points[(index + 1) % count] as readonly [number, number];
    const cross = x0 * y1 - x1 * y0;
    twiceArea += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  if (Math.abs(twiceArea) < 1e-12) {
    const sum = points.reduce((acc, [x, y]) => ({ x: acc.x + x, y: acc.y + y }), { x: 0, y: 0 });
    return { x: sum.x / count, y: sum.y / count };
  }
  return { x: cx / (3 * twiceArea), y: cy / (3 * twiceArea) };
};

/** Подпись зоны на холсте: № квартиры, марка, площадь (двери - ширина × высота). */
export const zoneCanvasLabel = (zone: CadZoneRead): string => {
  if (zone.kind === 'door') {
    const width = zone.width_m === null ? '?' : String(Math.round(zone.width_m * 1000));
    return `${width} × ${zone.door_height_mm ?? '?'}`;
  }
  if (zone.kind === 'parking_space') {
    const type = PARKING_TYPE_SHORT[zone.parking_type ?? 'unknown'];
    return zone.area_m2 !== null ? `${type} · ${formatZoneArea(zone.area_m2)}` : type;
  }
  const parts: string[] = [];
  if (zone.kind === 'room_apartment' && zone.apartment_no !== null)
    parts.push(`кв. ${zone.apartment_no}`);
  if (zone.kind === 'room_mop') parts.push('МОП');
  if (zone.room_mark !== null) parts.push(zone.room_mark);
  if (zone.name !== null) parts.push(zone.name);
  if (zone.area_m2 !== null) parts.push(formatZoneArea(zone.area_m2));
  return parts.join(' · ');
};

// --- группировка и суммы ---

export interface IZoneSum {
  /** Сумма определённых площадей; `null` - ни у одной зоны площадь не определена. */
  readonly areaM2: number | null;
  /** У части зон площадь не определена: сумма неполная. */
  readonly partial: boolean;
}

export interface IApartmentGroup extends IZoneSum {
  readonly apartmentNo: string;
  readonly zones: readonly CadZoneRead[];
}

export interface IZoneGroups {
  readonly apartments: readonly IApartmentGroup[];
  readonly mop: IZoneSum & { readonly zones: readonly CadZoneRead[] };
  readonly doors: readonly CadZoneRead[];
  readonly parking: IZoneSum & { readonly zones: readonly CadZoneRead[] };
}

/** Строка сводки машино-мест: тип, число и сумма площади. */
export interface IParkingTypeSum extends IZoneSum {
  readonly type: ParkingType;
  readonly count: number;
}

/** Сумма площадей: неопределённая площадь в сумму не идёт и не превращается в 0. */
export const sumAreas = (zones: readonly CadZoneRead[]): IZoneSum => {
  let total = 0;
  let known = 0;
  for (const zone of zones) {
    if (zone.area_m2 !== null) {
      total += zone.area_m2;
      known += 1;
    }
  }
  return {
    areaM2: known === 0 ? null : total,
    partial: known > 0 && known < zones.length,
  };
};

const compareApartment = (first: string, second: string): number =>
  first.localeCompare(second, 'ru', { numeric: true });

/** Группы панели: квартиры по номеру, МОП, двери. */
export const groupZones = (zones: readonly CadZoneRead[]): IZoneGroups => {
  const byApartment = new Map<string, CadZoneRead[]>();
  const mop: CadZoneRead[] = [];
  const doors: CadZoneRead[] = [];
  const parking: CadZoneRead[] = [];
  for (const zone of zones) {
    if (zone.kind === 'door') doors.push(zone);
    else if (zone.kind === 'parking_space') parking.push(zone);
    else if (zone.kind === 'room_mop') mop.push(zone);
    else {
      const key = zone.apartment_no ?? '';
      byApartment.set(key, [...(byApartment.get(key) ?? []), zone]);
    }
  }
  const apartments = [...byApartment.entries()]
    .sort(([first], [second]) => compareApartment(first, second))
    .map(([apartmentNo, items]) => ({ apartmentNo, zones: items, ...sumAreas(items) }));
  return {
    apartments,
    mop: { zones: mop, ...sumAreas(mop) },
    doors,
    parking: { zones: parking, ...sumAreas(parking) },
  };
};

/** Сводка машино-мест по типам (в порядке легенды): число и площадь; пустые типы не выводятся. */
export const parkingSummary = (zones: readonly CadZoneRead[]): readonly IParkingTypeSum[] => {
  const byType = new Map<ParkingType, CadZoneRead[]>();
  for (const zone of zones) {
    if (zone.kind !== 'parking_space') continue;
    const type = zone.parking_type ?? 'unknown';
    byType.set(type, [...(byType.get(type) ?? []), zone]);
  }
  return PARKING_TYPES.filter((type) => byType.has(type)).map((type) => {
    const items = byType.get(type) ?? [];
    return { type, count: items.length, ...sumAreas(items) };
  });
};

/** Размер двери: ширина × высота в мм; нет калибровки - ширина не определена. */
export const doorSizeText = (zone: CadZoneRead): string => {
  const height = zone.door_height_mm === null ? '?' : String(zone.door_height_mm);
  if (zone.width_m === null) return `ширина: ${NO_CALIBRATION_TEXT} × ${height} мм`;
  return `${Math.round(zone.width_m * 1000)} × ${height} мм`;
};

// --- ввод ---

export interface IZoneInput {
  readonly kind: ZoneKind;
  readonly apartmentNo: string;
  readonly doorHeight: string;
}

/** Целое число из поля; пусто или не число - `null`. */
export const parseDoorHeight = (raw: string): number | null => {
  const text = raw.trim();
  if (!/^\d{1,5}$/.test(text)) return null;
  return Number(text);
};

/** Что мешает начать рисование; `null` - можно. */
export const zoneInputProblem = ({ kind, apartmentNo, doorHeight }: IZoneInput): string | null => {
  if (kind === 'room_apartment' && apartmentNo.trim() === '') return 'Укажите № квартиры.';
  if (kind === 'door') {
    const height = parseDoorHeight(doorHeight);
    if (height === null || height < DOOR_HEIGHT_MIN_MM || height > DOOR_HEIGHT_MAX_MM) {
      return `Высота проёма: ${DOOR_HEIGHT_MIN_MM}–${DOOR_HEIGHT_MAX_MM} мм.`;
    }
  }
  return null;
};

// --- машина рисования ---

/** Режим машины точек для вида зоны: помещение - многоугольник, дверь - линия поперёк проёма. */
export const zoneToolMode = (kind: ZoneKind): ToolMode => (kind === 'door' ? 'line' : 'polygon');

/** Минимум вершин помещения. */
export const MIN_ROOM_POINTS = 3;

/** Радиус щелчка по вершине, пикселей: попадание замыкает контур. */
export const CLOSE_RADIUS_PX = 10;

interface IScreenPoint {
  readonly x: number;
  readonly y: number;
}

const distance = (first: IScreenPoint, second: IScreenPoint): number =>
  Math.hypot(first.x - second.x, first.y - second.y);

/**
 * Замыкает ли щелчок многоугольник: рядом с первой вершиной (контур готов) или рядом с
 * последней (вторая половина двойного щелчка). Вершин меньше трёх - нет.
 */
export const clickClosesPolygon = (
  mode: ToolMode,
  vertices: readonly IScreenPoint[],
  click: IScreenPoint,
  radius: number = CLOSE_RADIUS_PX,
): boolean => {
  if (mode !== 'polygon' || vertices.length < MIN_ROOM_POINTS) return false;
  const first = vertices[0] as IScreenPoint;
  const last = vertices[vertices.length - 1] as IScreenPoint;
  return distance(first, click) <= radius || distance(last, click) <= radius;
};

/** Точки машины рисования -> пары для API. */
export const pointsToPairs = (points: readonly NormalizedPoint[]): [number, number][] =>
  points.map((point) => [point.x, point.y]);
