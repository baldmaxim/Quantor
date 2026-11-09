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

/** Знаменатель масштаба из мм на точку PDF: N = mm_per_pt * 72 / 25.4, целым. */
export const scaleDenominatorFromMmPerPt = (mmPerPt: number | null | undefined): number | null =>
  mmPerPt === null || mmPerPt === undefined || !Number.isFinite(mmPerPt) || mmPerPt <= 0
    ? null
    : Math.round((mmPerPt * 72) / 25.4);

/** «1:100» из мм на точку PDF; без значения - «—». */
export const formatScaleFromMmPerPt = (mmPerPt: number | null | undefined): string =>
  formatScaleDenominator(scaleDenominatorFromMmPerPt(mmPerPt));

export type ScaleStatusTone = 'success' | 'warning' | 'danger' | 'neutral';

/** Статус масштаба вида словами: passed / needs_review / failed; незнакомый - как есть. */
export const scaleStatusInfo = (
  status: string | null | undefined,
): { label: string; tone: ScaleStatusTone } => {
  if (status === 'passed') return { label: 'подтверждена', tone: 'success' };
  if (status === 'needs_review') return { label: 'требует проверки', tone: 'warning' };
  if (status === 'failed') return { label: 'отклонена', tone: 'danger' };
  return { label: status ?? NO_VALUE, tone: 'neutral' };
};

/** Источник масштаба вида: калибровка человека или подбор по размерным цепочкам. */
export const scaleSourceLabel = (source: string | null | undefined): string => {
  if (source === 'operator_calibration') return 'Калибровка человека';
  if (source === 'dimension_chains') return 'Размерные цепочки';
  return source ?? NO_VALUE;
};

/** Отклонение от размерных цепочек: движок отдаёт долю (0,023), показываем проценты. */
export const formatDeviationPercent = (deviation: number | null | undefined): string =>
  deviation === null || deviation === undefined || !Number.isFinite(deviation)
    ? NO_VALUE
    : formatNumber(deviation * 100, 1, '%');
