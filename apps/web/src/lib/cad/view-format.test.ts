import { describe, expect, it } from 'vitest';

import { formatBool, formatInt, formatNumber, formatScaleDenominator, NO_VALUE } from './view-format';

describe('view-format', () => {
  it('отсутствующее значение - прочерк, а не ноль', () => {
    expect(formatNumber(null)).toBe(NO_VALUE);
    expect(formatNumber(undefined)).toBe(NO_VALUE);
    expect(formatNumber(Number.NaN)).toBe(NO_VALUE);
    expect(formatInt(null)).toBe(NO_VALUE);
    expect(formatBool(null)).toBe(NO_VALUE);
  });

  it('ноль остаётся нулём', () => {
    expect(formatNumber(0)).toBe('0');
    expect(formatInt(0)).toBe('0');
    expect(formatBool(false)).toBe('нет');
  });

  it('единицы приклеиваются только к числу', () => {
    expect(formatNumber(null, 2, 'мм')).toBe(NO_VALUE);
    expect(formatNumber(1.5, 2, 'мм')).toMatch(/^1[.,]5\s+мм$/);
  });

  it('масштаб - знаменатель после «1:»', () => {
    expect(formatScaleDenominator(100)).toBe('1:100');
    expect(formatScaleDenominator(null)).toBe(NO_VALUE);
    expect(formatScaleDenominator(0)).toBe(NO_VALUE);
  });
});
