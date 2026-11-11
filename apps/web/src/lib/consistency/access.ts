/**
 * Доступ к контуру согласованности чертежей (ADR-0043).
 *
 * Флаг `project.consistency` включается на пространство; сервер закрывает маршруты сам. Пока мета
 * не пришла, решения нет: страница не должна ни показаться, ни ответить «не найдено» раньше времени.
 */

export const CONSISTENCY_FEATURE = 'project.consistency';

export type ConsistencyAccess = 'pending' | 'open' | 'hidden';

export const consistencyAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): ConsistencyAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[CONSISTENCY_FEATURE] === true ? 'open' : 'hidden';
};
