import { describe, expect, it } from 'vitest';

import { CALC_FEATURE, calcAccess } from './access';

describe('доступ к расчётному контуру', () => {
  it('пока мета не пришла, решения нет', () => {
    expect(calcAccess(false, { [CALC_FEATURE]: true })).toBe('pending');
  });

  it('открыт только флагом calc.portal', () => {
    expect(calcAccess(true, { [CALC_FEATURE]: true })).toBe('open');
  });

  it('выключенный или отсутствующий флаг прячет контур', () => {
    expect(calcAccess(true, { [CALC_FEATURE]: false })).toBe('hidden');
    expect(calcAccess(true, {})).toBe('hidden');
  });

  it('чужие флаги контур не открывают', () => {
    expect(calcAccess(true, { 'takeoff.manual': true, mep_rd_hypothesis_v1: true })).toBe('hidden');
  });
});
