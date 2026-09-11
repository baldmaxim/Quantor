import { describe, expect, it, vi } from 'vitest';

import { boundsOfPoints, ShapeIndex } from './shape-index';
import { GridIndex } from './spatial-index';

/**
 * Индекс фигур поверх сетки (промт 04): синхронизация со списком без перестройки и порядок списка.
 */

interface Shape {
  readonly id: string;
  readonly points: readonly { readonly x: number; readonly y: number }[];
}

const shape = (id: string, x: number, y: number, size = 0.05): Shape => ({
  id,
  points: [
    { x, y },
    { x: x + size, y: y + size },
  ],
});

const everywhere = [{ minX: 0, minY: 0, maxX: 1, maxY: 1 }];
const ids = (index: ShapeIndex<Shape>) => index.query(everywhere).map((hit) => hit.item.id);

describe('индекс фигур', () => {
  it('охват точек — их минимум и максимум, у пустой фигуры — неконечный', () => {
    expect(
      boundsOfPoints([
        { x: 0.3, y: 0.7 },
        { x: 0.1, y: 0.9 },
      ]),
    ).toEqual({ minX: 0.1, minY: 0.7, maxX: 0.3, maxY: 0.9 });
    expect(Number.isFinite(boundsOfPoints([]).minX)).toBe(false);
  });

  it('отдаёт фигуры в порядке списка, а не в порядке ячеек', () => {
    const index = new ShapeIndex<Shape>();
    index.sync([shape('c', 0.9, 0.9), shape('a', 0.1, 0.1), shape('b', 0.5, 0.5)]);

    expect(ids(index)).toEqual(['c', 'a', 'b']);
    expect(index.orderOf('b')).toBe(2);
    expect(index.orderOf('нет')).toBeNull();
  });

  it('тот же массив второй раз не трогает сетку', () => {
    const set = vi.spyOn(GridIndex.prototype, 'set');
    const index = new ShapeIndex<Shape>();
    const list = [shape('a', 0.1, 0.1), shape('b', 0.5, 0.5)];
    index.sync(list);
    set.mockClear();

    index.sync(list);

    expect(set).not.toHaveBeenCalled();
    set.mockRestore();
  });

  it('новый список: неизменённые не переносятся, изменённая переносится, пропавшая удаляется', () => {
    const set = vi.spyOn(GridIndex.prototype, 'set');
    const remove = vi.spyOn(GridIndex.prototype, 'delete');
    const index = new ShapeIndex<Shape>();
    const a = shape('a', 0.1, 0.1);
    const b = shape('b', 0.5, 0.5);
    const c = shape('c', 0.8, 0.8);
    index.sync([a, b, c]);
    set.mockClear();

    // Кэш запросов после правки: `a` — тот же объект, `b` — новый объект с теми же точками,
    // `c` сдвинута, `d` новая, а прежней `c` в списке нет под старыми координатами.
    const sameB = { ...b, points: b.points.map((point) => ({ ...point })) };
    const movedC = shape('c', 0.2, 0.8);
    const d = shape('d', 0.4, 0.1);
    index.sync([a, sameB, movedC, d]);

    expect(set.mock.calls.map((call) => call[0])).toEqual(['c', 'd']);
    expect(index.query([{ minX: 0.79, minY: 0.79, maxX: 0.81, maxY: 0.81 }])).toEqual([]);
    expect(index.query([{ minX: 0.2, minY: 0.8, maxX: 0.21, maxY: 0.81 }])[0]?.item).toBe(movedC);

    set.mockClear();
    index.sync([sameB, d]);
    expect(set).not.toHaveBeenCalled();
    expect(remove.mock.calls.map((call) => call[0]).sort()).toEqual(['a', 'c']);
    expect(ids(index)).toEqual(['b', 'd']);
    expect(index.size).toBe(2);

    set.mockRestore();
    remove.mockRestore();
  });

  it('перестановка в списке меняет порядок без переноса охватов', () => {
    const set = vi.spyOn(GridIndex.prototype, 'set');
    const index = new ShapeIndex<Shape>();
    const a = shape('a', 0.1, 0.1);
    const b = shape('b', 0.5, 0.5);
    index.sync([a, b]);
    set.mockClear();

    index.sync([b, a]);

    expect(set).not.toHaveBeenCalled();
    expect(ids(index)).toEqual(['b', 'a']);
    set.mockRestore();
  });

  it('несколько прямоугольников запроса — фигура один раз', () => {
    const index = new ShapeIndex<Shape>();
    index.sync([shape('wide', 0.1, 0.1, 0.6)]);

    expect(
      index.query([
        { minX: 0.15, minY: 0.15, maxX: 0.2, maxY: 0.2 },
        { minX: 0.6, minY: 0.6, maxX: 0.65, maxY: 0.65 },
      ]),
    ).toHaveLength(1);
  });
});
