import type { CadZoneRead } from '@quantor/api-client';

import type { RoomType } from './room-types';

/**
 * Категория зоны для цвета и скрытия на листе: по названию помещения квартиры (эвристика по
 * подстрокам), МОП и двери - свои категории, машино-места - категория «parking». Чистая логика без DOM.
 */

export type ZoneCategory =
  | 'wet'
  | 'kitchen'
  | 'living'
  | 'hall'
  | 'storage'
  | 'outdoor'
  | 'other'
  | 'mop_lift'
  | 'mop_vestibule'
  | 'mop_corridor'
  | 'mop_stair'
  | 'mop'
  | 'door'
  | 'parking';

/** Порядок категорий в панели «Слои». */
export const ZONE_CATEGORIES: readonly ZoneCategory[] = [
  'wet',
  'kitchen',
  'living',
  'hall',
  'storage',
  'outdoor',
  'other',
  'mop_lift',
  'mop_vestibule',
  'mop_corridor',
  'mop_stair',
  'mop',
  'door',
  'parking',
];

export const ZONE_CATEGORY_LABELS: Readonly<Record<ZoneCategory, string>> = {
  wet: 'Санузлы и ванные',
  kitchen: 'Кухни',
  living: 'Комнаты',
  hall: 'Прихожие и коридоры',
  storage: 'Гардеробы и кладовые',
  outdoor: 'Балконы и лоджии',
  other: 'Прочие помещения',
  mop_lift: 'Лифтовые холлы',
  mop_vestibule: 'Тамбуры',
  mop_corridor: 'Коридоры МОП',
  mop_stair: 'Лестничные клетки',
  mop: 'Прочие МОП',
  door: 'Двери',
  parking: 'Машино-места',
};

/** Имя токена цвета категории: `--cad-zone-<категория>`, подчёркивание -> дефис (`mop_lift` -> `mop-lift`). */
export const zoneCategoryToken = (category: ZoneCategory): string =>
  `--cad-zone-${category.replaceAll('_', '-')}`;

export const zoneCategoryColorVar = (category: ZoneCategory): string =>
  `var(${zoneCategoryToken(category)})`;

type ZoneLike = Pick<CadZoneRead, 'kind' | 'name' | 'room_type'>;

/** Категория МОП по коду типа помещения; прочие коды (вестибюль, ПУИ, мусорокамера, тех.) - «mop». */
const MOP_CATEGORY_BY_TYPE: Readonly<Partial<Record<RoomType, ZoneCategory>>> = {
  lift_hall: 'mop_lift',
  vestibule: 'mop_vestibule',
  airlock: 'mop_vestibule',
  corridor: 'mop_corridor',
  stair: 'mop_stair',
};

/** Вывод по названию, как на сервере (`_MOP_RULES`): порядок важен, первое совпадение побеждает. */
const MOP_NAME_RULES: readonly (readonly [ZoneCategory, readonly string[]])[] = [
  ['mop_vestibule', ['шлюз']],
  ['mop_lift', ['лифт']],
  ['mop_vestibule', ['тамбур']],
  ['mop_stair', ['лестн']],
  [
    'mop',
    [
      'вестибюл',
      'входн',
      'пуи',
      'уборочн',
      'мусор',
      'электрощит',
      'щитов',
      'венткам',
      'итп',
      'насосн',
      'тех',
    ],
  ],
  ['mop_corridor', ['коридор', 'холл']],
];

const mopCategory = (zone: ZoneLike): ZoneCategory => {
  if (zone.room_type !== null && zone.room_type !== undefined) {
    return MOP_CATEGORY_BY_TYPE[zone.room_type] ?? 'mop';
  }
  if (zone.name === null) return 'mop';
  const name = zone.name.toLowerCase().replaceAll('ё', 'е');
  for (const [category, patterns] of MOP_NAME_RULES) {
    if (patterns.some((pattern) => name.includes(pattern))) return category;
  }
  return 'mop';
};

/** Правила по порядку: первое совпадение побеждает («кухня-гостиная» - кухня). */
const NAME_RULES: readonly (readonly [ZoneCategory, readonly string[]])[] = [
  ['kitchen', ['кухн', 'столов']],
  ['wet', ['сануз', 'с/у', 'с.у', 'ванн', 'туалет', 'уборн', 'душ', 'wc']],
  ['storage', ['гардероб', 'кладов', 'постироч', 'хоз']],
  ['hall', ['прихож', 'коридор', 'холл', 'тамбур']],
  ['outdoor', ['балкон', 'лодж', 'террас']],
  ['living', ['комнат', 'спальн', 'гостин', 'кабинет', 'детск']],
];

export const zoneCategory = (zone: ZoneLike): ZoneCategory => {
  if (zone.kind === 'door') return 'door';
  if (zone.kind === 'room_mop') return mopCategory(zone);
  if (zone.kind === 'parking_space') return 'parking';
  if (zone.name === null) return 'other';
  const name = zone.name.toLowerCase().replaceAll('ё', 'е');
  for (const [category, patterns] of NAME_RULES) {
    if (patterns.some((pattern) => name.includes(pattern))) return category;
  }
  return 'other';
};

/** Категории, которые есть на листе, с числом зон; в порядке панели. */
export const presentZoneCategories = (
  zones: readonly ZoneLike[],
): readonly { readonly category: ZoneCategory; readonly count: number }[] => {
  const counts = new Map<ZoneCategory, number>();
  for (const zone of zones) {
    const category = zoneCategory(zone);
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }
  return ZONE_CATEGORIES.filter((category) => counts.has(category)).map((category) => ({
    category,
    count: counts.get(category) ?? 0,
  }));
};
