import { describe, expect, it } from 'vitest';

import { resolveLeftTab, resolveMode, tabFromQuery } from './left-tab';

describe('левая вкладка рабочей области', () => {
  it('закрытая флагом вкладка уступает место листам', () => {
    expect(resolveLeftTab('takeoff', { takeoff: false, recognition: true })).toBe('documents');
  });

  it('открытая флагом вкладка остаётся', () => {
    expect(resolveLeftTab('takeoff', { takeoff: true, recognition: false })).toBe('takeoff');
    expect(resolveLeftTab('recognition', { takeoff: false, recognition: true })).toBe(
      'recognition',
    );
  });

  it('вкладка распознавания закрыта, пока показ блоков выключен', () => {
    expect(resolveLeftTab('recognition', { takeoff: true, recognition: false })).toBe(
      'documents',
    );
    expect(resolveLeftTab('documents', { takeoff: true, recognition: false })).toBe('documents');
  });

  it('режим CAD закрыт флагом cad.export, режим «Листы» - никогда', () => {
    expect(resolveMode('cad', false)).toBe('sheets');
    expect(resolveMode('cad', true)).toBe('cad');
    expect(resolveMode('sheets', false)).toBe('sheets');
  });

  it('tab=cad из адреса читается, остальное - нет', () => {
    expect(tabFromQuery('cad')).toBe('cad');
    expect(tabFromQuery('takeoff')).toBeNull();
    expect(tabFromQuery('')).toBeNull();
    expect(tabFromQuery(null)).toBeNull();
  });
});
