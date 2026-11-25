import type { AiVorMapSuggestionRead, CadVorLinkRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { vorItem } from '@/lib/cad/vor-fixtures';

import { hasUnlinked, planAccept } from './ai-map';

const suggestion = (
  id: string,
  objects: { key: string; linked?: boolean }[],
): AiVorMapSuggestionRead => ({
  item: vorItem({ id }),
  objects: objects.map(({ key, linked = false }) => ({
    group_key: key,
    kind: 'construction',
    title: key,
    linked,
  })),
  confidence: 'high',
  rationale: 'толщина совпала',
});

const link = (key: string, itemId: string): CadVorLinkRead => ({
  id: `l-${key}-${itemId}`,
  group_key: key,
  item: vorItem({ id: itemId }),
  created_at: '2026-11-25T10:00:00Z',
});

describe('план принятия ИИ-предложений', () => {
  it('добавляет строку к прежним связям группы, а не заменяет их', () => {
    const plan = planAccept(
      [suggestion('new', [{ key: 'masonry|190|' }])],
      [link('masonry|190|', 'old')],
    );
    expect(plan).toEqual([{ groupKey: 'masonry|190|', itemIds: ['old', 'new'] }]);
  });

  it('один шаг на ключ: несколько позиций одной группы сливаются', () => {
    const plan = planAccept(
      [suggestion('a', [{ key: 'k1' }, { key: 'k2' }]), suggestion('b', [{ key: 'k1' }])],
      [],
    );
    expect(plan).toEqual([
      { groupKey: 'k1', itemIds: ['a', 'b'] },
      { groupKey: 'k2', itemIds: ['a'] },
    ]);
  });

  it('пропускает уже связанные пары', () => {
    const rows = [suggestion('a', [{ key: 'k1', linked: true }])];
    expect(planAccept(rows, [link('k1', 'a')])).toEqual([]);
    expect(hasUnlinked(rows[0]!)).toBe(false);
    expect(hasUnlinked(suggestion('a', [{ key: 'k1', linked: true }, { key: 'k2' }]))).toBe(true);
  });
});
