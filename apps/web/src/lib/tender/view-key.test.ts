import { describe, expect, it } from 'vitest';

import { hiddenCalcIds, isTenderLayerKey, tenderLayerKey, viewKeyOf } from './view-key';

describe('ключи слоя «Расчёты»', () => {
  it('ключ вида - ревизия, страница, вид', () => {
    expect(viewKeyOf('rev', 81, 0)).toBe('rev:81:0');
  });

  it('слой расчёта хранится по имени tender:<calc_id>', () => {
    expect(tenderLayerKey('c1')).toBe('tender:c1');
    expect(isTenderLayerKey('tender:c1')).toBe(true);
    expect(isTenderLayerKey('02_МОНОЛИТ')).toBe(false);
  });

  it('скрытые расчёты выбираются из общего набора скрытых слоёв листа', () => {
    const hidden = new Set(['02_МОНОЛИТ', 'tender:c1', 'tender:c2']);
    expect([...hiddenCalcIds(hidden)].sort()).toEqual(['c1', 'c2']);
  });
});
