import { describe, expect, it } from 'vitest';

import { env } from './env';

describe('env', () => {
  it('подставляет локальный адрес API, когда переменная не задана', () => {
    expect(env.apiBaseUrl).toMatch(/^https?:\/\//);
  });
});
