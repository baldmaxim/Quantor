import { describe, expect, it } from 'vitest';

import {
  edgeHandle,
  hitMidpoint,
  hitVertex,
  insertMidpoint,
  moveVertex,
  removeVertex,
} from './zone-edit';

const SQUARE: readonly (readonly [number, number])[] = [
  [0.1, 0.1],
  [0.5, 0.1],
  [0.5, 0.5],
  [0.1, 0.5],
];

describe('правка вершин', () => {
  it('moveVertex переносит одну вершину и не меняет исходное кольцо', () => {
    const next = moveVertex(SQUARE, 2, { x: 0.6, y: 0.7 });
    expect(next[2]).toEqual([0.6, 0.7]);
    expect(next[0]).toEqual([0.1, 0.1]);
    expect(SQUARE[2]).toEqual([0.5, 0.5]);
  });

  it('insertMidpoint добавляет вершину в середину ребра с индексом edge + 1', () => {
    const result = insertMidpoint(SQUARE, 1);
    expect(result?.index).toBe(2);
    expect(result?.ring).toHaveLength(5);
    expect(result?.ring[2]).toEqual([0.5, 0.3]);
  });

  it('insertMidpoint замыкающего ребра ставит вершину в конец кольца', () => {
    const result = insertMidpoint(SQUARE, 3);
    expect(result?.index).toBe(4);
    expect(result?.ring[4]).toEqual([0.1, 0.3]);
    expect(insertMidpoint(SQUARE, 9)).toBeNull();
  });

  it('removeVertex убирает вершину, но не оставляет меньше трёх', () => {
    const four = removeVertex(SQUARE, 0);
    expect(four).toEqual([
      [0.5, 0.1],
      [0.5, 0.5],
      [0.1, 0.5],
    ]);
    expect(removeVertex(four ?? [], 0)).toBeNull();
    expect(removeVertex(SQUARE, 7)).toBeNull();
  });
});

describe('попадание по ручкам', () => {
  const screen = [
    { x: 100, y: 100 },
    { x: 200, y: 100 },
    { x: 200, y: 105 },
  ];

  it('hitVertex выбирает ближайшую вершину в радиусе, иначе -1', () => {
    expect(hitVertex(screen, { x: 103, y: 102 })).toBe(0);
    expect(hitVertex(screen, { x: 198, y: 99 })).toBe(1);
    expect(hitVertex(screen, { x: 150, y: 150 })).toBe(-1);
  });

  it('середина ребра - ручка только у достаточно длинного ребра', () => {
    expect(edgeHandle(screen, 0)).toEqual({ x: 150, y: 100 });
    expect(edgeHandle(screen, 1)).toBeNull();
    expect(hitMidpoint(screen, { x: 152, y: 101 })).toBe(0);
    expect(hitMidpoint(screen, { x: 200, y: 102 })).toBe(-1);
  });
});
