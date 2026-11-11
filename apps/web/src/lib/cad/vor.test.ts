import { describe, expect, it } from 'vitest';

import { construction } from './constructions-fixtures';
import {
  constructionVorStatus,
  notInVorIds,
  thicknessesOfKeys,
  thicknessListText,
  vorItemQuantity,
} from './vor';
import { coverage, coverageGroup, LINKED_ITEM } from './vor-fixtures';

describe('подсветка «не в ВОР»', () => {
  it('ВОР не загружен: пусто, даже если сервер прислал ключи', () => {
    expect(notInVorIds(coverage({ has_vor: false, not_in_vor_keys: ['a'] }), true)).toBeUndefined();
    expect(notInVorIds(null, true)).toBeUndefined();
  });

  it('ВОР есть: набор конструкций; переключатель выключен - пусто', () => {
    expect([...(notInVorIds(coverage(), true) ?? [])]).toEqual(['a']);
    expect(notInVorIds(coverage(), false)).toBeUndefined();
  });
});

describe('толщины ВОР', () => {
  it('из ключей групп: по возрастанию, без повторов', () => {
    expect(thicknessesOfKeys(['masonry|150|', 'masonry|80|', 'monolith_wall|80|monolith_concrete'])).toEqual([
      80, 150,
    ]);
    expect(thicknessListText([80, 150])).toBe('80, 150 мм');
  });
});

describe('количество строки ВОР', () => {
  it('не определено - прочерк, а не ноль', () => {
    expect(vorItemQuantity({ quantity: null, unit: 'м3' })).toBe('—');
    expect(vorItemQuantity(LINKED_ITEM)).toBe('55 м3');
  });
});

describe('статус конструкции в ВОР', () => {
  const cov = coverage({
    groups: [
      coverageGroup({ group_key: 'masonry|120|', thickness_mm: 120, status: 'linked', items: [LINKED_ITEM] }),
      coverageGroup(),
    ],
  });

  it('группа связана - «в ВОР» со строками', () => {
    const status = constructionVorStatus(cov, construction({ id: 'a' }));
    expect(status).toEqual({ state: 'in-vor', groupKey: 'masonry|120|', items: [LINKED_ITEM] });
  });

  it('группа не связана - «не в ВОР»', () => {
    const item = construction({ id: 'b' });
    const status = constructionVorStatus(cov, {
      ...item,
      computed: { ...item.computed, thickness_mm: 100 },
    });
    expect(status).toEqual({ state: 'not-in-vor', groupKey: 'masonry|100|' });
  });

  it('нет ВОР, нет толщины, нет данных', () => {
    expect(constructionVorStatus(coverage({ has_vor: false }), construction({ id: 'a' }))).toEqual({
      state: 'no-vor',
    });
    const item = construction({ id: 'c' });
    expect(
      constructionVorStatus(cov, { ...item, computed: { ...item.computed, thickness_mm: null } }),
    ).toEqual({ state: 'not-counted' });
    expect(constructionVorStatus(undefined, item)).toBeNull();
  });
});
