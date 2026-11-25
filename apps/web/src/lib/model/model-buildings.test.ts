import type { ModelStoreyRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { elevationLevels, hasBuildings, storeysByBuilding } from './model-buildings';

const storey = (
  key: string,
  elevation: number,
  building?: readonly [string, string],
): ModelStoreyRead =>
  ({
    storey_key: key,
    name: key,
    elevation_mm: elevation,
    building_key: building?.[0] ?? null,
    building_name: building?.[1] ?? null,
  }) as unknown as ModelStoreyRead;

const K1 = ['k1', 'Корпус 1'] as const;
const K7 = ['k7', 'Корпус 7'] as const;

describe('этажи по зданиям', () => {
  it('модель одного здания - одна группа без имени', () => {
    const groups = storeysByBuilding([storey('a', 0), storey('b', 3000)]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBeNull();
    expect(groups[0]?.storeys.map((s) => s.storey_key)).toEqual(['a', 'b']);
    expect(hasBuildings(groups)).toBe(false);
  });

  it('корпуса в порядке ответа API, этажи каждого - свои', () => {
    const groups = storeysByBuilding([
      storey('k1-0', 0, K1),
      storey('k1-3', 3000, K1),
      storey('k7-0', 0, K7),
      storey('k7-3', 3050, K7),
    ]);
    expect(groups.map((g) => [g.name, g.storeys.map((s) => s.storey_key)])).toEqual([
      ['Корпус 1', ['k1-0', 'k1-3']],
      ['Корпус 7', ['k7-0', 'k7-3']],
    ]);
    expect(hasBuildings(groups)).toBe(true);
  });
});

describe('уровни «Всего дома»', () => {
  it('одна отметка у разных зданий - один уровень', () => {
    const { levels, levelOf } = elevationLevels([
      storey('k1-0', 0, K1),
      storey('k1-3', 3000, K1),
      storey('k7-0', 0, K7),
      storey('k7-3', 3050, K7),
    ]);
    expect(levels).toEqual([0, 3000, 3050]);
    expect([...levelOf]).toEqual([
      ['k1-0', 0],
      ['k1-3', 1],
      ['k7-0', 0],
      ['k7-3', 2],
    ]);
  });

  it('в модели одного здания уровень - номер этажа снизу', () => {
    const { levelOf } = elevationLevels([storey('b', 3000), storey('a', 0)]);
    expect(levelOf.get('a')).toBe(0);
    expect(levelOf.get('b')).toBe(1);
  });
});
