import { describe, expect, it } from 'vitest';

import { heightsFixture } from './floor3d-fixtures';
import { draftOf, sectionLabelOf, sheetOverridesOf, writeOfDraft } from './floor3d-heights';

describe('подоконник и высота окна листа', () => {
  it('переопределения берутся только из источника «ввод»; «не задано» - null', () => {
    expect(sheetOverridesOf(heightsFixture())).toMatchObject({
      window_sill_mm: null,
      window_head_mm: null,
    });
    const saved = heightsFixture({
      window_sill: { value_mm: 900, source: 'manual', default_mm: null },
      window_head: { value_mm: 2400, source: 'manual', default_mm: null },
    });
    expect(sheetOverridesOf(saved)).toMatchObject({ window_sill_mm: 900, window_head_mm: 2400 });
  });

  it('запись: пара проверяется как на сервере', () => {
    const base = draftOf(sheetOverridesOf(heightsFixture()));
    expect(writeOfDraft({ ...base, window_sill_mm: '0', window_head_mm: '1500' })).toEqual({
      write: expect.objectContaining({ window_sill_mm: 0, window_head_mm: 1500 }),
    });
    expect(writeOfDraft({ ...base, window_sill_mm: '900' })).toHaveProperty('error');
    expect(writeOfDraft({ ...base, window_head_mm: '2400' })).toHaveProperty('error');
    expect(writeOfDraft({ ...base, window_sill_mm: '2400', window_head_mm: '2400' })).toHaveProperty(
      'error',
    );
    expect(writeOfDraft({ ...base, window_sill_mm: '0', window_head_mm: '6001' })).toHaveProperty(
      'error',
    );
  });

  it('секция листа - только при корпусе и секции вместе', () => {
    expect(sectionLabelOf({ corps: '1', section: '3' })).toBe('корп. 1, сек. 3');
    expect(sectionLabelOf({ corps: ' 1 ', section: ' 3 ' })).toBe('корп. 1, сек. 3');
    expect(sectionLabelOf({ corps: '1', section: null })).toBeNull();
    expect(sectionLabelOf({ corps: null, section: '3' })).toBeNull();
    expect(sectionLabelOf({ corps: '', section: '' })).toBeNull();
    expect(sectionLabelOf(null)).toBeNull();
    expect(sectionLabelOf(undefined)).toBeNull();
  });
});
