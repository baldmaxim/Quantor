/**
 * Доступ к обмену расчётами с TENDER (ADR-0051).
 *
 * Флаг `tender.exchange` включается на пространство; сервер закрывает маршруты сам. Пока мета не
 * пришла, решения нет: страница не должна ни показаться, ни ответить «не найдено» раньше времени.
 */

export const TENDER_EXCHANGE_FEATURE = 'tender.exchange';

/** Права из сеанса; значения совпадают с `Permission` в `apps/api/app/auth/permissions.py`. */
export const TENDER_CALC_READ = 'tender.calc.read';
export const TENDER_BASE_RELEASE = 'tender.base.release';
export const TENDER_CALC_WITHDRAW = 'tender.calc.withdraw';

export type TenderAccess = 'pending' | 'open' | 'hidden';

export const tenderAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): TenderAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[TENDER_EXCHANGE_FEATURE] === true ? 'open' : 'hidden';
};
