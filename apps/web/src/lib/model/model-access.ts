/**
 * Доступ к модели здания (ADR-0053): пилотный флаг `model.import`, включается на пространство.
 * Пока мета не пришла, решения нет.
 */

export const MODEL_FEATURE = 'model.import';

export type ModelAccess = 'pending' | 'open' | 'hidden';

export const modelAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): ModelAccess => {
  if (!metaLoaded) {
    return 'pending';
  }
  return features[MODEL_FEATURE] === true ? 'open' : 'hidden';
};
