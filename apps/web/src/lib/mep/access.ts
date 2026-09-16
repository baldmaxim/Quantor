/**
 * Доступ к странице MEP-эксперимента.
 *
 * Флаг пилотный и закрыт на сервере (ADR-0023). Пока мета не пришла, решения нет: выключенным
 * считается всё, и страница не должна ни показаться, ни ответить «не найдено» раньше времени.
 */

export const MEP_FEATURE = 'mep_rd_hypothesis_v1';

export type MepAccess = 'pending' | 'open' | 'hidden';

export const mepAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): MepAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[MEP_FEATURE] === true ? 'open' : 'hidden';
};
