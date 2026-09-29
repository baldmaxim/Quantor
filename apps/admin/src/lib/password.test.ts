import { describe, expect, it } from 'vitest';

import { TEMPORARY_PASSWORD_LENGTH, generatePassword } from './password';

describe('временный пароль', () => {
  it('проходит серверное требование длины', () => {
    expect(generatePassword().length).toBe(TEMPORARY_PASSWORD_LENGTH);
    expect(TEMPORARY_PASSWORD_LENGTH).toBeGreaterThanOrEqual(10);
  });

  it('без похожих символов', () => {
    for (let attempt = 0; attempt < 50; attempt += 1) {
      expect(generatePassword()).not.toMatch(/[0O1lI]/);
    }
  });

  it('каждый раз новый', () => {
    expect(generatePassword()).not.toBe(generatePassword());
  });
});
