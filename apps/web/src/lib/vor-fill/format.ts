import type { VorFillItemRead, VorObjectRead } from '@quantor/api-client';

import { formatNumber, NO_VALUE } from '@/lib/cad/view-format';

/**
 * Заполнение ВОР (ADR-0055, п. 7): подписи и форматирование без сети и React.
 * Количества Quantor - только от движка; количества Заказчика стоят рядом и ни во что не подставляются.
 */

export const STATUS_LABELS: Readonly<Record<VorFillItemRead['status'], string>> = {
  match: 'Совпало',
  differs: 'Расходится',
  no_quantor: 'Нет у Quantor',
  unit_mismatch: 'Единицы не совпали',
  no_customer: 'Нет у Заказчика',
};

/** Цвет статуса - только токены темы. */
export const STATUS_CLASSES: Readonly<Record<VorFillItemRead['status'], string>> = {
  match: 'text-success',
  differs: 'text-warning',
  no_quantor: 'text-danger',
  unit_mismatch: 'text-danger',
  no_customer: 'text-muted',
};

export const UNIT_LABELS: Readonly<Record<VorObjectRead['quantities'][number]['unit'], string>> = {
  m3: 'м³',
  m2: 'м²',
  m: 'м',
  pcs: 'шт',
};

export const OBJECT_KIND_LABELS: Readonly<Record<VorObjectRead['kind'], string>> = {
  construction: 'Конструкции',
  door: 'Двери',
  finish: 'Отделка МОП',
};

/** «12,5 м³ · 40 м²»; величин нет - прочерк, не 0. */
export const objectQuantitiesText = (
  object: Pick<VorObjectRead, 'quantities' | 'incomplete'>,
): string => {
  if (object.quantities.length === 0) return NO_VALUE;
  const text = object.quantities
    .map((quantity) => `${formatNumber(quantity.value, 2)} ${UNIT_LABELS[quantity.unit]}`)
    .join(' · ');
  return object.incomplete ? `${text} (неполно)` : text;
};

export const quantityText = (value: number | null, unit: VorFillItemRead['unit']): string =>
  value === null
    ? NO_VALUE
    : unit === null
      ? formatNumber(value, 2)
      : `${formatNumber(value, 2)} ${UNIT_LABELS[unit]}`;

export const differenceText = (
  item: Pick<VorFillItemRead, 'difference' | 'difference_percent'>,
): string => {
  if (item.difference === null) return NO_VALUE;
  const sign = item.difference > 0 ? '+' : '';
  const percent =
    item.difference_percent === null
      ? ''
      : ` (${sign}${formatNumber(item.difference_percent, 1)} %)`;
  return `${sign}${formatNumber(item.difference, 2)}${percent}`;
};
