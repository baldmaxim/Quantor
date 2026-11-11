import type {
  CadFinishTemplateRead,
  CadFinishWarningRead,
  CadFinishZoneRead,
} from '@quantor/api-client';

import { ZONE_KIND_LABELS } from './zones';

/**
 * Подписи и форматирование ведомости отделки листа. Величины приходят с сервера; здесь их только
 * показывают: `null` - «—», не 0. Чистая логика без DOM и сети.
 */

export const DASH = '—';

const AREA_FORMAT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const QTY_FORMAT = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const MM_FORMAT = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

/** Площадь, м²: два знака; не определена - «—». */
export const formatFinishArea = (value: number | null): string =>
  value === null ? DASH : AREA_FORMAT.format(value);

/** Длина, м: два знака; не определена - «—». */
export const formatFinishMeters = (value: number | null): string =>
  value === null ? DASH : AREA_FORMAT.format(value);

/** Высота, мм: целые; не определена - «—». */
export const formatFinishMm = (value: number | null): string =>
  value === null ? DASH : MM_FORMAT.format(Math.round(value));

/** Количество материала с единицей; не определено - «—». */
export const formatMaterialQty = (qty: number | null, unit: string | null): string =>
  qty === null ? DASH : `${QTY_FORMAT.format(qty)}${unit === null ? '' : ` ${unit}`}`;

export const WALLS_UNLINKED_LABEL = 'по периметру (не привязано)';

export const TEMPLATE_SOURCE_LABELS: Readonly<
  Record<NonNullable<CadFinishZoneRead['template_source']>, string>
> = {
  explicit: 'явно',
  by_type: 'по типу',
};

export const HEIGHT_SOURCE_LABELS: Readonly<
  Record<NonNullable<CadFinishZoneRead['wall_height_source']>, string>
> = {
  template: 'шаблон',
  levels: 'уровни листа',
};

/** Название строки ведомости: квартира, марка, имя; без них - вид зоны. */
export const finishZoneTitle = (
  zone: Pick<CadFinishZoneRead, 'apartment_no' | 'room_mark' | 'name' | 'kind'>,
): string => {
  const parts = [
    zone.apartment_no !== null ? `кв. ${zone.apartment_no}` : null,
    zone.room_mark,
    zone.name,
  ].filter((part): part is string => part !== null && part !== '');
  return parts.length > 0 ? parts.join(' · ') : ZONE_KIND_LABELS[zone.kind];
};

export const templateNameOf = (
  templates: readonly CadFinishTemplateRead[],
  id: string | null,
): string => (id === null ? DASH : (templates.find((item) => item.id === id)?.name ?? DASH));

/** Сколько зон показывать у предупреждения, пока список не раскрыт. */
export const WARNING_ZONES_PREVIEW = 8;

export const warningZoneIds = (
  warning: CadFinishWarningRead,
  expanded: boolean,
): readonly string[] =>
  expanded ? warning.zone_ids : warning.zone_ids.slice(0, WARNING_ZONES_PREVIEW);
