/**
 * Подписи значений диагностики. Отсутствующее значение - «—», а не 0 и не «нет»:
 * «не определено» и «ноль» для инженера разные вещи.
 */

export const NO_VALUE = '—';

export const formatNumber = (
  value: number | null | undefined,
  digits = 2,
  unit?: string,
): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE;
  const text = value.toLocaleString('ru-RU', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
  return unit ? `${text} ${unit}` : text;
};

export const formatInt = (value: number | null | undefined): string => formatNumber(value, 0);

export const formatBool = (value: boolean | null | undefined): string =>
  value === null || value === undefined ? NO_VALUE : value ? 'да' : 'нет';

/** «1:100» из знаменателя масштаба; без знаменателя - «—». */
export const formatScaleDenominator = (value: number | null | undefined): string =>
  value === null || value === undefined || !Number.isFinite(value) || value <= 0
    ? NO_VALUE
    : `1:${formatNumber(value, 1)}`;
