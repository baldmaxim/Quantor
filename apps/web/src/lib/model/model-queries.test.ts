import { describe, expect, it } from 'vitest';

import { isModelMetaQuery, modelKeys } from './model-queries';

describe('что сбрасывать после сборки и утверждения', () => {
  it('версии, описание версии и задание - да, части пакета по sha256 - нет', () => {
    expect(isModelMetaQuery(modelKeys.versions('p'))).toBe(true);
    expect(isModelMetaQuery(modelKeys.version('p', 'v'))).toBe(true);
    expect(isModelMetaQuery(modelKeys.import('p'))).toBe(true);
    expect(isModelMetaQuery(modelKeys.part('p', 'v', 'sha'))).toBe(false);
    expect(isModelMetaQuery(modelKeys.elements('p', 'v', 'sha'))).toBe(false);
  });
});
