import { describe, expect, it } from 'vitest';

import { formatElapsed, stateLabel, stateTone } from './stages';

describe('formatElapsed', () => {
  it('округляет общее число секунд до деления на минуты', () => {
    expect(formatElapsed(59.6)).toBe('1 мин 0 с');
    expect(formatElapsed(119.6)).toBe('2 мин 0 с');
    expect(formatElapsed(114.4)).toBe('1 мин 54 с');
    expect(formatElapsed(3600)).toBe('60 мин 0 с');
  });

  it('до минуты: десятые до 10 с, дальше целые', () => {
    expect(formatElapsed(0)).toBe('0.0 с');
    expect(formatElapsed(9.96)).toBe('10 с');
    expect(formatElapsed(42.4)).toBe('42 с');
    expect(formatElapsed(59.4)).toBe('59 с');
  });

  it('нет значения - прочерк', () => {
    expect(formatElapsed(null)).toBe('—');
    expect(formatElapsed(Number.NaN)).toBe('—');
  });
});

describe('статусы этапов', () => {
  it('отказ показывается как отказ', () => {
    expect(stateLabel('failed')).toBe('Отказ');
    expect(stateTone('failed')).toBe('danger');
  });
});
