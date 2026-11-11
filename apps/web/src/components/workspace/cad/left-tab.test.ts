import { describe, expect, it } from 'vitest';

import { resolveLeftTab, tabFromQuery } from './left-tab';

describe('левая вкладка рабочей области', () => {
  it('закрытая флагом вкладка уступает место листам', () => {
    expect(resolveLeftTab('cad', { takeoff: true, cad: false, recognition: true })).toBe(
      'documents',
    );
    expect(resolveLeftTab('takeoff', { takeoff: false, cad: true, recognition: true })).toBe(
      'documents',
    );
  });

  it('открытая флагом вкладка остаётся', () => {
    expect(resolveLeftTab('cad', { takeoff: false, cad: true, recognition: true })).toBe('cad');
    expect(resolveLeftTab('recognition', { takeoff: false, cad: false, recognition: true })).toBe(
      'recognition',
    );
  });

  it('вкладка распознавания закрыта, пока показ блоков выключен', () => {
    expect(resolveLeftTab('recognition', { takeoff: true, cad: true, recognition: false })).toBe(
      'documents',
    );
    expect(resolveLeftTab('documents', { takeoff: true, cad: true, recognition: false })).toBe(
      'documents',
    );
  });

  it('tab=cad из адреса читается, остальное - нет', () => {
    expect(tabFromQuery('cad')).toBe('cad');
    expect(tabFromQuery('takeoff')).toBeNull();
    expect(tabFromQuery('')).toBeNull();
    expect(tabFromQuery(null)).toBeNull();
  });
});
