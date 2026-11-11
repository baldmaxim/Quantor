import { describe, expect, it } from 'vitest';

import {
  buildSnapIndex,
  SNAP_RADIUS_PX,
  snapPoint,
  type ISnapOptions,
  type ISnapShape,
} from './zone-snap';

// Лист 1000 x 500 px: доли по x и y неизотропны.
const SCALE = { x: 1000, y: 500 };

const ROOM: ISnapShape = {
  closed: true,
  points: [
    [0.2, 0.2],
    [0.6, 0.2],
    [0.6, 0.6],
    [0.2, 0.6],
  ],
};
const DOOR: ISnapShape = {
  closed: false,
  points: [
    [0.8, 0.1],
    [0.8, 0.3],
  ],
};

const options = (patch: Partial<ISnapOptions> = {}, shapes = [ROOM, DOOR]): ISnapOptions => ({
  index: buildSnapIndex(shapes),
  scale: SCALE,
  placed: [],
  shift: false,
  alt: false,
  ...patch,
});

describe('snapPoint', () => {
  it('вершина зоны в радиусе: точка вершины', () => {
    // 6 px по x и 4 px по y от вершины (0.2, 0.2).
    const result = snapPoint({ x: 0.206, y: 0.208 }, options());
    expect(result).toEqual({ point: { x: 0.2, y: 0.2 }, kind: 'vertex' });
  });

  it('вершина важнее ребра, даже если ребро ближе', () => {
    // Рядом с вершиной (0.6, 0.2): до ребра y = 0.2 - 1 px, до вершины - 8 px по x.
    const result = snapPoint({ x: 0.592, y: 0.202 }, options());
    expect(result.kind).toBe('vertex');
    expect(result.point).toEqual({ x: 0.6, y: 0.2 });
  });

  it('ребро: проекция точки на отрезок', () => {
    const result = snapPoint({ x: 0.4, y: 0.206 }, options());
    expect(result.kind).toBe('edge');
    expect(result.point.x).toBeCloseTo(0.4, 10);
    expect(result.point.y).toBeCloseTo(0.2, 10);
  });

  it('замыкающее ребро помещения привязывает, ребро двери - тоже', () => {
    expect(snapPoint({ x: 0.203, y: 0.4 }, options()).kind).toBe('edge');
    const door = snapPoint({ x: 0.804, y: 0.2 }, options());
    expect(door.kind).toBe('edge');
    expect(door.point.x).toBeCloseTo(0.8, 10);
  });

  it('у двери одно ребро, у помещения - по числу вершин', () => {
    expect(buildSnapIndex([DOOR]).edges).toHaveLength(1);
    expect(buildSnapIndex([ROOM]).edges).toHaveLength(4);
  });

  it('расстояние меряется в пикселях, а не в долях', () => {
    expect(SNAP_RADIUS_PX).toBe(10);
    // Вертикальное ребро x = 0.2: сдвиг 0.015 по x = 15 px - не липнет.
    expect(snapPoint({ x: 0.215, y: 0.4 }, options({}, [ROOM])).kind).toBe('none');
    // Горизонтальное ребро y = 0.2: тот же сдвиг 0.015 по y = 7.5 px - липнет.
    const result = snapPoint({ x: 0.4, y: 0.215 }, options({}, [ROOM]));
    expect(result.kind).toBe('edge');
    expect(result.point.y).toBeCloseTo(0.2, 10);
  });

  it('вне радиуса - исходная точка', () => {
    expect(snapPoint({ x: 0.4, y: 0.4 }, options())).toEqual({
      point: { x: 0.4, y: 0.4 },
      kind: 'none',
    });
  });

  it('Alt выключает привязку', () => {
    const raw = { x: 0.206, y: 0.208 };
    expect(snapPoint(raw, options({ alt: true }))).toEqual({ point: raw, kind: 'none' });
  });

  it('поставленные вершины черновика - цели, кроме последней', () => {
    const placed = [
      { x: 0.9, y: 0.9 },
      { x: 0.95, y: 0.7 },
    ];
    const index = { index: buildSnapIndex([]) };
    expect(snapPoint({ x: 0.904, y: 0.902 }, options({ ...index, placed }))).toEqual({
      point: { x: 0.9, y: 0.9 },
      kind: 'vertex',
    });
    // Последняя вершина целью не служит.
    const near = { x: 0.952, y: 0.702 };
    expect(snapPoint(near, options({ ...index, placed }))).toEqual({ point: near, kind: 'none' });
  });

  it('вырожденный масштаб - исходная точка', () => {
    const raw = { x: 0.2, y: 0.2 };
    expect(snapPoint(raw, options({ scale: { x: 0, y: 500 } }))).toEqual({
      point: raw,
      kind: 'none',
    });
  });

  describe('ortho (Shift)', () => {
    const placed = [{ x: 0.3, y: 0.8 }];

    it('без поставленных вершин Shift ничего не ограничивает', () => {
      const raw = { x: 0.206, y: 0.208 };
      expect(snapPoint(raw, options({ shift: true })).kind).toBe('vertex');
    });

    it('горизонталь: ось по большему сдвигу на экране', () => {
      // dx = 300 px, dy = 25 px (0.05 * 500).
      const result = snapPoint({ x: 0.9, y: 0.85 }, options({ shift: true, placed }, []));
      expect(result).toEqual({ point: { x: 0.9, y: 0.8 }, kind: 'ortho' });
    });

    it('ось выбирается в пикселях, а не в долях', () => {
      // dx = 0.06 (60 px), dy = 0.1 (50 px): в долях вертикаль, на экране - горизонталь.
      const horizontal = snapPoint({ x: 0.36, y: 0.7 }, options({ shift: true, placed }, []));
      expect(horizontal).toEqual({ point: { x: 0.36, y: 0.8 }, kind: 'ortho' });
    });

    it('вертикаль: сдвиг по y на экране больше', () => {
      const result = snapPoint({ x: 0.35, y: 0.3 }, options({ shift: true, placed }, []));
      expect(result).toEqual({ point: { x: 0.3, y: 0.3 }, kind: 'ortho' });
    });

    it('вершина рядом с проекцией ortho побеждает', () => {
      // Горизонталь y = 0.8 уходит вправо; вершина (0.7, 0.8) стоит на оси.
      const shapes: ISnapShape[] = [
        {
          closed: false,
          points: [
            [0.7, 0.805],
            [0.7, 0.9],
          ],
        },
      ];
      const result = snapPoint({ x: 0.704, y: 0.85 }, options({ shift: true, placed }, shapes));
      expect(result).toEqual({ point: { x: 0.7, y: 0.805 }, kind: 'vertex' });
    });

    it('ось пересекает ребро рядом с проекцией: точка пересечения', () => {
      // Вертикальное ребро x = 0.6 от y = 0.5 до y = 0.95; ось y = 0.8.
      const shapes: ISnapShape[] = [
        {
          closed: false,
          points: [
            [0.6, 0.5],
            [0.6, 0.95],
          ],
        },
      ];
      const result = snapPoint({ x: 0.604, y: 0.83 }, options({ shift: true, placed }, shapes));
      expect(result.kind).toBe('edge');
      expect(result.point.x).toBeCloseTo(0.6, 10);
      expect(result.point.y).toBeCloseTo(0.8, 10);
    });

    it('ребро вне радиуса от проекции не мешает', () => {
      const shapes: ISnapShape[] = [
        {
          closed: false,
          points: [
            [0.6, 0.5],
            [0.6, 0.95],
          ],
        },
      ];
      const result = snapPoint({ x: 0.9, y: 0.83 }, options({ shift: true, placed }, shapes));
      expect(result).toEqual({ point: { x: 0.9, y: 0.8 }, kind: 'ortho' });
    });

    it('Alt сильнее Shift', () => {
      const raw = { x: 0.9, y: 0.85 };
      expect(snapPoint(raw, options({ shift: true, alt: true, placed }, []))).toEqual({
        point: raw,
        kind: 'none',
      });
    });
  });
});
