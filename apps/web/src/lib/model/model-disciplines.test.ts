import { describe, expect, it } from 'vitest';

import { disciplineLabel } from './model-disciplines';

describe('названия дисциплин модели', () => {
  it('коды выгрузчика - словами', () => {
    expect(disciplineLabel('UNK')).toBe('Не определена');
    expect(disciplineLabel('ARCH')).toBe('Архитектура');
    expect(disciplineLabel('STR')).toBe('Конструкции');
  });

  it('незнакомый код - как есть', () => {
    expect(disciplineLabel('XYZ')).toBe('XYZ');
  });
});
