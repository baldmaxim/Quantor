import { describe, expect, it } from 'vitest';

import { GridIndex, type NormalizedBounds } from './spatial-index';

/**
 * Пространственный индекс (промт 04).
 *
 * Индекс обязан отдавать ровно то же, что полный перебор охватов, — после вставок, переносов и
 * удалений, у края листа и за ним. Ошибка здесь выглядит как «щёлкаю по фигуре, а она не
 * выбирается» или «фигура пропала с экрана до следующей перерисовки».
 */

const sequence = (seed: number): (() => number) => {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
};

const box = (next: () => number, maxSize: number): NormalizedBounds => {
  // Часть охватов нарочно вылезает за лист: фигура у края не должна теряться.
  const x = next() * 1.2 - 0.1;
  const y = next() * 1.2 - 0.1;
  return { minX: x, minY: y, maxX: x + next() * maxSize, maxY: y + next() * maxSize };
};

const intersects = (a: NormalizedBounds, b: NormalizedBounds): boolean =>
  a.maxX >= b.minX && a.minX <= b.maxX && a.maxY >= b.minY && a.minY <= b.maxY;

const brute = (items: ReadonlyMap<number, NormalizedBounds>, query: NormalizedBounds): number[] =>
  [...items.entries()]
    .filter(([, bounds]) => intersects(bounds, query))
    .map(([key]) => key)
    .sort((a, b) => a - b);

const sorted = (keys: readonly number[]): number[] => [...keys].sort((a, b) => a - b);

describe('сетка против полного перебора', () => {
  it('поиск совпадает с перебором на крупных и мелких охватах', () => {
    for (const [seed, maxSize, cells] of [
      [1, 0.08, 32],
      [2, 0.01, 32],
      [3, 0.5, 8],
      [4, 0.002, 64],
    ] as const) {
      const next = sequence(seed);
      const index = new GridIndex<number>(cells);
      const items = new Map<number, NormalizedBounds>();
      for (let key = 0; key < 800; key += 1) {
        const bounds = box(next, maxSize);
        items.set(key, bounds);
        index.set(key, bounds);
      }

      for (let probe = 0; probe < 300; probe += 1) {
        const query = box(next, next() < 0.5 ? 0.003 : 0.3);
        expect(sorted(index.search(query))).toEqual(brute(items, query));
      }
    }
  });

  it('переносы и удаления не оставляют старых записей и не теряют новых', () => {
    const next = sequence(42);
    const index = new GridIndex<number>();
    const items = new Map<number, NormalizedBounds>();
    for (let key = 0; key < 500; key += 1) {
      const bounds = box(next, 0.05);
      items.set(key, bounds);
      index.set(key, bounds);
    }

    for (let step = 0; step < 2000; step += 1) {
      const key = Math.floor(next() * 600);
      const action = next();
      if (action < 0.2) {
        expect(index.delete(key)).toBe(items.delete(key));
      } else if (action < 0.6) {
        // Мелкий сдвиг — чаще всего те же ячейки: путь обновления на месте.
        const current = items.get(key) ?? box(next, 0.05);
        const dx = (next() - 0.5) * 0.004;
        const moved = {
          minX: current.minX + dx,
          minY: current.minY,
          maxX: current.maxX + dx,
          maxY: current.maxY,
        };
        items.set(key, moved);
        index.set(key, moved);
      } else {
        const bounds = box(next, 0.2);
        items.set(key, bounds);
        index.set(key, bounds);
      }
    }

    expect(index.size).toBe(items.size);
    for (let probe = 0; probe < 300; probe += 1) {
      const query = box(next, 0.2);
      expect(sorted(index.search(query))).toEqual(brute(items, query));
    }
  });

  it('запись во многих ячейках отдаётся один раз', () => {
    const index = new GridIndex<string>(16);
    index.set('big', { minX: 0, minY: 0, maxX: 1, maxY: 1 });

    expect(index.search({ minX: 0, minY: 0, maxX: 1, maxY: 1 })).toEqual(['big']);
  });

  it('касание краем — пересечение', () => {
    const index = new GridIndex<string>();
    index.set('a', { minX: 0.2, minY: 0.2, maxX: 0.3, maxY: 0.3 });

    expect(index.search({ minX: 0.3, minY: 0.3, maxX: 0.4, maxY: 0.4 })).toEqual(['a']);
    expect(index.search({ minX: 0.30001, minY: 0.3, maxX: 0.4, maxY: 0.4 })).toEqual([]);
  });

  it('охват без геометрии не находится, но учитывается и удаляется', () => {
    const index = new GridIndex<string>();
    index.set('empty', {
      minX: Number.POSITIVE_INFINITY,
      minY: Number.POSITIVE_INFINITY,
      maxX: Number.NEGATIVE_INFINITY,
      maxY: Number.NEGATIVE_INFINITY,
    });

    expect(index.size).toBe(1);
    expect(index.search({ minX: -10, minY: -10, maxX: 10, maxY: 10 })).toEqual([]);
    expect(index.delete('empty')).toBe(true);
    expect(index.size).toBe(0);
  });

  it('запись, получившая геометрию, находится; потерявшая — нет', () => {
    const index = new GridIndex<string>();
    const nowhere = { minX: Number.NaN, minY: 0, maxX: 0, maxY: 0 };
    index.set('shape', nowhere);
    index.set('shape', { minX: 0.5, minY: 0.5, maxX: 0.6, maxY: 0.6 });
    expect(index.search({ minX: 0.55, minY: 0.55, maxX: 0.56, maxY: 0.56 })).toEqual(['shape']);

    index.set('shape', nowhere);
    expect(index.search({ minX: 0, minY: 0, maxX: 1, maxY: 1 })).toEqual([]);
    expect(index.size).toBe(1);
  });

  it('очистка убирает всё', () => {
    const index = new GridIndex<string>();
    index.set('a', { minX: 0.1, minY: 0.1, maxX: 0.2, maxY: 0.2 });
    index.clear();

    expect(index.size).toBe(0);
    expect(index.search({ minX: 0, minY: 0, maxX: 1, maxY: 1 })).toEqual([]);
  });
});
