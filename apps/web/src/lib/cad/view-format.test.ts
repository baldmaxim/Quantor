import { describe, expect, it } from 'vitest';

import {
  formatDeviationPercent,
  formatInt,
  formatNumber,
  formatScaleDenominator,
  formatScaleFromMmPerPt,
  NO_VALUE,
  scaleDenominatorFromMmPerPt,
} from './view-format';

describe('view-format', () => {
  it('отсутствующее значение - прочерк, а не ноль', () => {
    expect(formatNumber(null)).toBe(NO_VALUE);
    expect(formatNumber(undefined)).toBe(NO_VALUE);
    expect(formatNumber(Number.NaN)).toBe(NO_VALUE);
    expect(formatInt(null)).toBe(NO_VALUE);
  });

  it('ноль остаётся нулём', () => {
    expect(formatNumber(0)).toBe('0');
    expect(formatInt(0)).toBe('0');
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

describe('view-format: масштаб из мм/pt', () => {
  it('1:N = мм/pt * 72 / 25,4, целым', () => {
    expect(formatScaleFromMmPerPt(35.28)).toBe('1:100');
    expect(formatScaleFromMmPerPt(70.5556)).toBe('1:200');
    expect(scaleDenominatorFromMmPerPt(17.64)).toBe(50);
    expect(scaleDenominatorFromMmPerPt(28.22)).toBe(80);
  });

  it('нет значения - прочерк', () => {
    expect(formatScaleFromMmPerPt(null)).toBe(NO_VALUE);
    expect(formatScaleFromMmPerPt(0)).toBe(NO_VALUE);
    expect(scaleDenominatorFromMmPerPt(undefined)).toBeNull();
  });

  it('отклонение - доля в процентах', () => {
    expect(formatDeviationPercent(0.023)).toMatch(/^2[.,]3\s*%$/);
    expect(formatDeviationPercent(null)).toBe(NO_VALUE);
  });
});
