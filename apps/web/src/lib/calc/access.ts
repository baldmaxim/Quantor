/**
 * Доступ к расчётному контуру.
 *
 * Флаг `calc.portal` закрыт на сервере и из админки не включается до инженерного гейта
 * (ADR-0030). Пока мета не пришла, решения нет: страница не должна ни показаться, ни
 * ответить «не найдено» раньше времени.
 */

export const CALC_FEATURE = 'calc.portal';

export type CalcAccess = 'pending' | 'open' | 'hidden';

export const calcAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): CalcAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[CALC_FEATURE] === true ? 'open' : 'hidden';
};
