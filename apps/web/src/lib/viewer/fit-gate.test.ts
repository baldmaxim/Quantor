import { describe, expect, it } from 'vitest';
import { decideFit, isMeasurable } from './fit-gate';

describe('isMeasurable', () => {
  it('нулевая ширина или высота - не измеряется', () => {
    expect(isMeasurable({ width: 0, height: 600 })).toBe(false);
    expect(isMeasurable({ width: 800, height: 0 })).toBe(false);
    expect(isMeasurable({ width: 0, height: 0 })).toBe(false);
  });

  it('положительные стороны - измеряется', () => {
    expect(isMeasurable({ width: 800, height: 600 })).toBe(true);
  });
});

describe('decideFit', () => {
  it('ждёт вписки и размер нулевой - откладывает', () => {
    expect(decideFit({ width: 0, height: 0 }, true)).toBe('defer');
    expect(decideFit({ width: 0, height: 500 }, true)).toBe('defer');
    expect(decideFit({ width: 500, height: 0 }, true)).toBe('defer');
  });

  it('ждёт вписки и появился первый ненулевой размер - вписывает', () => {
    expect(decideFit({ width: 1024, height: 700 }, true)).toBe('fit');
  });

  it('вписка не ждётся - обычный ресайз только сдвигает, не вписывает', () => {
    expect(decideFit({ width: 1024, height: 700 }, false)).toBe('keep');
    expect(decideFit({ width: 0, height: 0 }, false)).toBe('keep');
  });
});
