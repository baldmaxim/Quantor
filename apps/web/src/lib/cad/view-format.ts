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

/** Поля проверки масштаба движком (`CadScaleRead`), нужные подписи «1:N». */
interface ICadScaleValues {
  readonly source?: string | null;
  readonly operator_mm_per_pt?: number | null;
  readonly mm_per_pdf_point: number | null;
  readonly scale_denominator: number | null;
}

/** «1:N» вида CAD: при калибровке человека - из неё, иначе - масштаб, подобранный движком. */
export const formatCadScale = (scale: ICadScaleValues): string => {
  const fromCalibration = formatScaleFromMmPerPt(scale.operator_mm_per_pt ?? scale.mm_per_pdf_point);
  const fromEngine = formatScaleDenominator(scale.scale_denominator);
  const text = scale.source ? fromCalibration : fromEngine;
  if (text !== NO_VALUE) return text;
  return fromCalibration !== NO_VALUE ? fromCalibration : fromEngine;
};

/** Отклонение от размерных цепочек: движок отдаёт долю (0,023), показываем проценты. */
export const formatDeviationPercent = (deviation: number | null | undefined): string =>
  deviation === null || deviation === undefined || !Number.isFinite(deviation)
    ? NO_VALUE
    : formatNumber(deviation * 100, 1, '%');
