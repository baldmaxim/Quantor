/**
 * Доступ к CAD-инструменту (PDF -> DXF, QA-контур).
 *
 * Флаг `cad.export` из админки не включается; маршруты API существуют только при
 * `CAD_QA_ENABLED` в local/test. Пока мета не пришла, решения нет.
 */

export const CAD_FEATURE = 'cad.export';

export type CadAccess = 'pending' | 'open' | 'hidden';

export const cadAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): CadAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[CAD_FEATURE] === true ? 'open' : 'hidden';
};

/** Флаг включён: для мест, где мета уже учтена через `useFeatures` (рабочая область). */
export const cadEnabled = (features: Readonly<Record<string, boolean>>): boolean =>
  features[CAD_FEATURE] === true;
