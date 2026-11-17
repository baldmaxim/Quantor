import type { ModelVersionRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { newestVersion, pickVersion } from './model-versions';

const version = (id: string, status: string): ModelVersionRead =>
  ({ id, status, number: 1 }) as unknown as ModelVersionRead;

describe('выбор версии модели', () => {
  it('живой вид берёт новейшую законченную выгрузку, даже если утверждена старая', () => {
    const items = [version('new', 'candidate'), version('old', 'approved')];
    expect(newestVersion(items)).toBe('new');
    expect(pickVersion(items)).toBe('old');
  });

  it('выгрузка в процессе пропускается', () => {
    expect(newestVersion([version('u', 'uploading'), version('c', 'candidate')])).toBe('c');
  });

  it('без законченных версий - null', () => {
    expect(newestVersion([])).toBeNull();
    expect(newestVersion([version('u', 'uploading')])).toBeNull();
  });
});
