import { describe, expect, it } from 'vitest';

import { resolveLeftTab, tabFromQuery } from './left-tab';

describe('левая вкладка рабочей области', () => {
  it('закрытая флагом вкладка уступает место листам', () => {
    expect(resolveLeftTab('cad', { takeoff: true, cad: false })).toBe('documents');
    expect(resolveLeftTab('takeoff', { takeoff: false, cad: true })).toBe('documents');
  });

  it('открытая флагом вкладка остаётся', () => {
    expect(resolveLeftTab('cad', { takeoff: false, cad: true })).toBe('cad');
    expect(resolveLeftTab('recognition', { takeoff: false, cad: false })).toBe('recognition');
  });

  it('tab=cad из адреса читается, остальное - нет', () => {
    expect(tabFromQuery('cad')).toBe('cad');
    expect(tabFromQuery('takeoff')).toBeNull();
    expect(tabFromQuery('')).toBeNull();
    expect(tabFromQuery(null)).toBeNull();
  });
});
