import type { CadZoneRead } from '@quantor/api-client';

/**
 * Категория зоны для цвета и скрытия на листе: по названию помещения квартиры (эвристика по
 * подстрокам), МОП и двери - свои категории. Чистая логика без DOM.
 */

export type ZoneCategory =
  'wet' | 'kitchen' | 'living' | 'hall' | 'storage' | 'outdoor' | 'other' | 'mop' | 'door';

/** Порядок категорий в панели «Слои». */
export const ZONE_CATEGORIES: readonly ZoneCategory[] = [
  'wet',
  'kitchen',
  'living',
  'hall',
  'storage',
  'outdoor',
  'other',
  'mop',
  'door',
];

export const ZONE_CATEGORY_LABELS: Readonly<Record<ZoneCategory, string>> = {
  wet: 'Санузлы и ванные',
  kitchen: 'Кухни',
  living: 'Комнаты',
  hall: 'Прихожие и коридоры',
  storage: 'Гардеробы и кладовые',
  outdoor: 'Балконы и лоджии',
  other: 'Прочие помещения',
  mop: 'МОП',
  door: 'Двери',
};

/** Токен цвета категории (`--cad-zone-<категория>`). */
export const zoneCategoryColorVar = (category: ZoneCategory): string =>
  `var(--cad-zone-${category})`;

/** Правила по порядку: первое совпадение побеждает («кухня-гостиная» - кухня). */
const NAME_RULES: readonly (readonly [ZoneCategory, readonly string[]])[] = [
  ['kitchen', ['кухн', 'столов']],
  ['wet', ['сануз', 'с/у', 'с.у', 'ванн', 'туалет', 'уборн', 'душ', 'wc']],
  ['storage', ['гардероб', 'кладов', 'постироч', 'хоз']],
  ['hall', ['прихож', 'коридор', 'холл', 'тамбур']],
  ['outdoor', ['балкон', 'лодж', 'террас']],
  ['living', ['комнат', 'спальн', 'гостин', 'кабинет', 'детск']],
];

export const zoneCategory = (zone: Pick<CadZoneRead, 'kind' | 'name'>): ZoneCategory => {
  if (zone.kind === 'door') return 'door';
  if (zone.kind === 'room_mop') return 'mop';
  if (zone.name === null) return 'other';
  const name = zone.name.toLowerCase().replaceAll('ё', 'е');
  for (const [category, patterns] of NAME_RULES) {
    if (patterns.some((pattern) => name.includes(pattern))) return category;
  }
  return 'other';
};

/** Категории, которые есть на листе, с числом зон; в порядке панели. */
export const presentZoneCategories = (
  zones: readonly Pick<CadZoneRead, 'kind' | 'name'>[],
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
