import type { CadFinishLayerRead, CadFinishWarningRead, CadZoneRead } from '@quantor/api-client';

import type { ZoneKind } from './zones';

/**
 * Типы помещений зоны CAD и подписи отделки (ADR-0042). Коды берутся из типов клиента: новый
 * код на сервере ломает сборку здесь, пока для него нет подписи. Чистая логика без DOM и сети.
 */

export type RoomType = NonNullable<CadZoneRead['room_type']>;
export type RoomTypeSource = NonNullable<CadZoneRead['room_type_source']>;
export type FinishSurface = CadFinishLayerRead['surface'];
export type FinishWarningCode = CadFinishWarningRead['code'];
export type FinishBase = NonNullable<CadFinishLayerRead['bases']>[number];

export const ROOM_TYPE_LABELS: Readonly<Record<RoomType, string>> = {
  lift_hall: 'Лифтовой холл',
  vestibule: 'Тамбур',
  airlock: 'Тамбур-шлюз',
  corridor: 'Коридор',
  stair: 'Лестничная клетка',
  entrance_hall: 'Вестибюль',
  pui: 'ПУИ',
  garbage: 'Мусорокамера',
  tech: 'Техпомещение',
  mop_other: 'Прочее МОП',
  living: 'Жилая комната',
  kitchen: 'Кухня',
  bath: 'Санузел/ванная',
  wc: 'Туалет',
  hall: 'Прихожая/коридор',
  storage: 'Кладовая/гардероб',
  balcony: 'Балкон/лоджия',
  apt_other: 'Прочее',
};

export interface IRoomTypeGroup {
  readonly id: 'mop' | 'apartment';
  readonly title: string;
  /** Вид зоны, которому принадлежат коды группы. */
  readonly kind: ZoneKind;
  readonly types: readonly RoomType[];
}

/** Группы по виду зоны: МОП и помещение квартиры. */
export const ROOM_TYPE_GROUPS: readonly IRoomTypeGroup[] = [
  {
    id: 'mop',
    title: 'МОП',
    kind: 'room_mop',
    types: [
      'lift_hall',
      'vestibule',
      'airlock',
      'corridor',
      'stair',
      'entrance_hall',
      'pui',
      'garbage',
      'tech',
      'mop_other',
    ],
  },
  {
    id: 'apartment',
    title: 'Квартира',
    kind: 'room_apartment',
    types: ['living', 'kitchen', 'bath', 'wc', 'hall', 'storage', 'balcony', 'apt_other'],
  },
];

/** Коды, допустимые зоне данного вида; у двери и машино-места типа нет. */
export const roomTypesForKind = (kind: ZoneKind): readonly RoomType[] =>
  ROOM_TYPE_GROUPS.find((group) => group.kind === kind)?.types ?? [];

/** Подпись типа; нет типа - «—». */
export const roomTypeLabel = (type: RoomType | null): string =>
  type === null ? '—' : ROOM_TYPE_LABELS[type];

export const ROOM_TYPE_SOURCE_LABELS: Readonly<Record<RoomTypeSource, string>> = {
  manual: 'вручную',
  derived: 'авто',
};

export const SURFACE_LABELS: Readonly<Record<FinishSurface, string>> = {
  floor: 'Пол',
  walls: 'Стены',
  ceiling: 'Потолок',
};

/** Порядок поверхностей в шаблоне и ведомости. */
export const SURFACES: readonly FinishSurface[] = ['floor', 'walls', 'ceiling'];

/** Основания стен в каноническом порядке (ADR-0042, п. 6). */
export const FINISH_BASES: readonly FinishBase[] = ['monolith', 'masonry', 'gkl'];

export const FINISH_BASE_LABELS: Readonly<Record<FinishBase, string>> = {
  monolith: 'Монолит',
  masonry: 'Кладка',
  gkl: 'ГКЛ',
};

/** Основания слоя стен текстом: «Монолит, Кладка»; `null` - все основания, текста нет. */
export const basesText = (bases: readonly FinishBase[] | null): string =>
  bases === null
    ? ''
    : FINISH_BASES.filter((base) => bases.includes(base))
        .map((base) => FINISH_BASE_LABELS[base])
        .join(', ');

export const FINISH_WARNING_LABELS: Readonly<Record<FinishWarningCode, string>> = {
  calibration_missing: 'Нет калибровки масштаба: площади не определены',
  geometry_issue: 'Контур зоны недействителен: площади не определены',
  wall_height_missing:
    'Не определена высота стен: задайте её в шаблоне или в высотах листа (раздел «Конструкции»)',
  no_template: 'Не назначен шаблон отделки',
  gap_unknown_height: 'Проёмы без двери: высота неизвестна, участок не отделывается',
  door_height_missing: 'Высота двери не задана: дверной участок не отделывается',
  windows_not_detected:
    'Окна не распознаны: оконные участки наружных стен не отделываются целиком, подоконная часть не учтена',
  edges_unlinked: 'Стены не привязаны к конструкциям: площадь по периметру зоны',
};
