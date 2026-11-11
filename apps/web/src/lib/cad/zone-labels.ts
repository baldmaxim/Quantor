import type { CadZoneRead } from '@quantor/api-client';

import { PARKING_TYPE_SHORT, formatZoneArea } from './zones';

/**
 * Подписи зон на холсте: какие строки показать и помещаются ли они в экранный охват помещения.
 * Чистая логика: ширину текста передаёт вызывающий (в рисовальщике - `measureText`).
 */

export interface IZoneLabelOptions {
  readonly apartment: boolean;
  readonly mark: boolean;
  readonly name: boolean;
  readonly area: boolean;
}

export const LABEL_LINE_HEIGHT = 13;
/** Доля экранного охвата помещения, которую может занять подпись. */
const FIT = 0.9;

type ZoneLabelSource = Pick<
  CadZoneRead,
  | 'kind'
  | 'apartment_no'
  | 'room_mark'
  | 'name'
  | 'area_m2'
  | 'width_m'
  | 'door_height_mm'
  | 'parking_type'
>;

/** Строки подписи помещения: «кв. N · марка · название» и площадь; пустые не возвращаются. */
export const roomLabelLines = (
  zone: ZoneLabelSource,
  options: IZoneLabelOptions,
): { readonly head: string; readonly area: string } => {
  if (zone.kind === 'parking_space') {
    // Место подписывается кратким типом; название (подпись легенды) на плане не помещается.
    return {
      head: PARKING_TYPE_SHORT[zone.parking_type ?? 'unknown'],
      area: options.area && zone.area_m2 !== null ? formatZoneArea(zone.area_m2) : '',
    };
  }
  const parts: string[] = [];
  if (options.apartment && zone.kind === 'room_apartment' && zone.apartment_no !== null) {
    parts.push(`кв. ${zone.apartment_no}`);
  }
  if (options.mark) {
    // Нет марки - вместо неё название (если оно ещё не включено отдельно).
    if (zone.room_mark !== null) parts.push(zone.room_mark);
    else if (!options.name && zone.name !== null) parts.push(zone.name);
  }
  if (options.name && zone.name !== null) parts.push(zone.name);
  return {
    head: parts.join(' · '),
    area: options.area && zone.area_m2 !== null ? formatZoneArea(zone.area_m2) : '',
  };
};

export interface IScreenBox {
  readonly width: number;
  readonly height: number;
}

/**
 * Что рисовать в помещении: обе строки, только площадь или ничего. Подпись должна уместиться в
 * 0,9 ширины и высоты экранного охвата помещения.
 */
export const fitRoomLabel = (
  lines: { readonly head: string; readonly area: string },
  box: IScreenBox,
  measure: (text: string) => number,
): readonly string[] => {
  const attempts: readonly (readonly string[])[] = [
    [lines.head, lines.area].filter((line) => line !== ''),
    [lines.area].filter((line) => line !== ''),
  ];
  for (const attempt of attempts) {
    if (attempt.length === 0) continue;
    const width = Math.max(...attempt.map(measure));
    if (width <= box.width * FIT && attempt.length * LABEL_LINE_HEIGHT <= box.height * FIT) {
      return attempt;
    }
  }
  return [];
};

/** Подпись двери («ширина × высота», мм): только если проём на экране не короче текста. */
export const doorLabelFits = (
  text: string,
  screenLength: number,
  measure: (text: string) => number,
): boolean => text !== '' && measure(text) <= screenLength;
