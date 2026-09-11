/**
 * Слой измерений: отрисовка и попадание курсора.
 *
 * Проверяются координаты на холсте и выбор фигуры, а не «что-то нарисовалось». Ошибка
 * здесь выглядит как «щёлкаю по линии, а выделяется соседняя» — и находится долго.
 */

import { describe, expect, it, vi } from 'vitest';

import type { NormalizedPoint, SheetPlacement } from '@/lib/viewer/coordinates';
import {
  drawMeasurements,
  hitTestMeasurements,
  hitTestVertex,
  measurementsTouch,
  type MeasurementOverlayState,
  type OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';

const placement: SheetPlacement = { x: 0, y: 0, width: 1000, height: 1000, rotation: 0 };
const style = { colors: { accent: '#14539e', danger: '#b42318' }, fallbackColor: '#000000' };

const p = (x: number, y: number): NormalizedPoint => ({ x, y });

const measurement = (overrides: Partial<OverlayMeasurement> = {}): OverlayMeasurement => ({
  id: 'm1',
  geometryType: 'line',
  points: [p(0.1, 0.5), p(0.9, 0.5)],
  colorKey: 'accent',
  ...overrides,
});

const state = (overrides: Partial<MeasurementOverlayState> = {}): MeasurementOverlayState => ({
  measurements: [],
  selectedId: null,
  hoveredId: null,
  draft: [],
  draftType: null,
  draftHover: null,
  dragOverride: null,
  ...overrides,
});

interface Recorded {
  context: CanvasRenderingContext2D;
  arcs: { x: number; y: number; r: number }[];
  moves: { x: number; y: number }[];
  lines: { x: number; y: number }[];
  dashes: number[][];
  closes: number;
  fills: number;
  strokes: number;
  cleared: number;
  colors: string[];
}

const fakeContext = (): Recorded => {
  const arcs: Recorded['arcs'] = [];
  const moves: Recorded['moves'] = [];
  const lines: Recorded['lines'] = [];
  const dashes: number[][] = [];
  const colors: string[] = [];
  const counters = { closes: 0, fills: 0, strokes: 0, cleared: 0 };

  const context = {
    canvas: { width: 1000, height: 1000 },
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    setTransform: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    clearRect: vi.fn(() => {
      counters.cleared += 1;
    }),
    beginPath: vi.fn(),
    closePath: vi.fn(() => {
      counters.closes += 1;
    }),
    moveTo: vi.fn((x: number, y: number) => moves.push({ x, y })),
    lineTo: vi.fn((x: number, y: number) => lines.push({ x, y })),
    arc: vi.fn((x: number, y: number, r: number) => arcs.push({ x, y, r })),
    fill: vi.fn(() => {
      counters.fills += 1;
    }),
    stroke: vi.fn(() => {
      counters.strokes += 1;
    }),
    setLineDash: vi.fn((pattern: number[]) => dashes.push([...pattern])),
    set strokeStyle(value: string) {
      colors.push(value);
    },
    fillStyle: '',
    lineWidth: 0,
    globalAlpha: 1,
  } as unknown as CanvasRenderingContext2D;

  return {
    context,
    arcs,
    moves,
    lines,
    dashes,
    colors,
    get closes() {
      return counters.closes;
    },
    get fills() {
      return counters.fills;
    },
    get strokes() {
      return counters.strokes;
    },
    get cleared() {
      return counters.cleared;
    },
  };
};

describe('отрисовка', () => {
  it('очищает холст перед каждым кадром', () => {
    const recorded = fakeContext();

    drawMeasurements(recorded.context, placement, state(), style);

    expect(recorded.cleared).toBe(1);
  });

  it('метка счёта встаёт туда, куда щёлкнули', () => {
    const recorded = fakeContext();

    const drawn = drawMeasurements(
      recorded.context,
      placement,
      state({ measurements: [measurement({ geometryType: 'count', points: [p(0.25, 0.75)] })] }),
      style,
    );

    expect(drawn).toBe(1);
    expect(recorded.arcs[0]).toMatchObject({ x: 250, y: 750 });
  });

  it('линия рисуется от точки до точки', () => {
    const recorded = fakeContext();

    drawMeasurements(recorded.context, placement, state({ measurements: [measurement()] }), style);

    expect(recorded.moves).toContainEqual({ x: 100, y: 500 });
    expect(recorded.lines).toContainEqual({ x: 900, y: 500 });
  });

  it('многоугольник замыкается и заливается', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({
        measurements: [
          measurement({
            geometryType: 'polygon',
            points: [p(0.1, 0.1), p(0.9, 0.1), p(0.9, 0.9)],
          }),
        ],
      }),
      style,
    );

    expect(recorded.closes).toBe(1);
    expect(recorded.fills).toBeGreaterThan(0);
  });

  it('ломаная не замыкается', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({
        measurements: [
          measurement({
            geometryType: 'polyline',
            points: [p(0.1, 0.1), p(0.5, 0.1), p(0.9, 0.9)],
          }),
        ],
      }),
      style,
    );

    expect(recorded.closes).toBe(0);
  });

  it('ручки вершин рисуются только у выбранного', () => {
    // У всех сразу они превратили бы чертёж в россыпь точек.
    const withoutSelection = fakeContext();
    drawMeasurements(
      withoutSelection.context,
      placement,
      state({ measurements: [measurement()] }),
      style,
    );

    const withSelection = fakeContext();
    drawMeasurements(
      withSelection.context,
      placement,
      state({ measurements: [measurement()], selectedId: 'm1' }),
      style,
    );

    expect(withoutSelection.arcs).toHaveLength(0);
    expect(withSelection.arcs).toHaveLength(2);
  });

  it('цвет берётся по ключу палитры', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({ measurements: [measurement({ colorKey: 'danger' })] }),
      style,
    );

    expect(recorded.colors).toContain('#b42318');
  });

  it('неизвестный ключ палитры не роняет отрисовку', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({ measurements: [measurement({ colorKey: 'нет такого' })] }),
      style,
    );

    expect(recorded.colors).toContain('#000000');
  });

  it('черновик рисуется пунктиром', () => {
    // Черновик ещё не результат и выглядеть как результат не должен.
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({ draft: [p(0.1, 0.1), p(0.5, 0.5)], draftType: 'polyline' }),
      style,
    );

    expect(recorded.dashes).toContainEqual([6, 4]);
  });

  it('перетаскиваемая вершина рисуется вместо сохранённой', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({
        measurements: [measurement()],
        dragOverride: { id: 'm1', points: [p(0.1, 0.5), p(0.5, 0.5)] },
      }),
      style,
    );

    // Конец линии сдвинут: показывается предварительная геометрия, а не сохранённая.
    expect(recorded.lines).toContainEqual({ x: 500, y: 500 });
    expect(recorded.lines).not.toContainEqual({ x: 900, y: 500 });
  });

  it('фигура за краем холста не растеризуется', () => {
    const recorded = fakeContext();

    const drawn = drawMeasurements(
      recorded.context,
      { ...placement, x: -5000 },
      state({ measurements: [measurement()] }),
      style,
    );

    expect(drawn).toBe(0);
    expect(recorded.strokes).toBe(0);
  });

  it('фигура, задевающая край холста, рисуется', () => {
    const recorded = fakeContext();

    // Линия от 0,1 до 0,9 листа в 1000 пикселей, сдвинутого на -800: правый конец на холсте.
    const drawn = drawMeasurements(
      recorded.context,
      { ...placement, x: -800 },
      state({ measurements: [measurement()] }),
      style,
    );

    expect(drawn).toBe(1);
  });

  it('учитывает плотность пикселей', () => {
    const recorded = fakeContext();

    drawMeasurements(recorded.context, placement, state(), style, 2);

    expect(recorded.context.scale).toHaveBeenCalledWith(2, 2);
  });

  it('на повёрнутом листе отсечение идёт по повёрнутым координатам', () => {
    // Охват считается по нормализованным точкам, а в пиксели переводятся его углы. При повороте
    // на 90° точка (x, y) встаёт в (1 − y, x): отсекать по неповёрнутым было бы ошибкой.
    const recorded = fakeContext();
    const rotated: SheetPlacement = { ...placement, x: -900, rotation: 90 };
    // (0,05; 0,05) → (0,95; 0,05) → x = −900 + 950 = 50: на холсте.
    const visible = measurement({ id: 'visible', geometryType: 'count', points: [p(0.05, 0.05)] });
    // (0,95; 0,95) → (0,05; 0,95) → x = −900 + 50 = −850: за краем, хотя без поворота был бы на 50.
    const hidden = measurement({ id: 'hidden', geometryType: 'count', points: [p(0.95, 0.95)] });

    const drawn = drawMeasurements(
      recorded.context,
      rotated,
      state({ measurements: [visible, hidden] }),
      style,
    );

    expect(drawn).toBe(1);
    expect(recorded.arcs[0]).toMatchObject({ x: 50, y: 50 });
  });
});

describe('отрисовка полосами', () => {
  // Панорама сдвигает пиксели слоя и присылает только открывшиеся полосы (ADR-0025).
  const left = measurement({ id: 'left', geometryType: 'count', points: [p(0.1, 0.5)] });
  const right = measurement({ id: 'right', geometryType: 'count', points: [p(0.9, 0.5)] });

  it('рисует только фигуры, задевающие полосу', () => {
    const recorded = fakeContext();

    const drawn = drawMeasurements(
      recorded.context,
      placement,
      state({ measurements: [left, right] }),
      style,
      1,
      [{ x: 850, y: 0, width: 150, height: 1000 }],
    );

    expect(drawn).toBe(1);
    expect(recorded.arcs).toEqual([expect.objectContaining({ x: 900, y: 500 })]);
    expect(recorded.context.clip).toHaveBeenCalledTimes(1);
  });

  it('метка у самой границы полосы рисуется: запас на радиус', () => {
    const recorded = fakeContext();
    // Центр метки в 3 пикселях левее полосы: её правый край заходит в полосу.
    const edge = measurement({ id: 'edge', geometryType: 'count', points: [p(0.847, 0.5)] });

    const drawn = drawMeasurements(
      recorded.context,
      placement,
      state({ measurements: [edge] }),
      style,
      1,
      [{ x: 850, y: 0, width: 150, height: 1000 }],
    );

    expect(drawn).toBe(1);
  });

  it('вопрос «есть ли что рисовать» отвечает так же, как отрисовка', () => {
    const areas = [
      [{ x: 850, y: 0, width: 150, height: 1000 }],
      [{ x: 0, y: 0, width: 50, height: 1000 }],
      [{ x: 400, y: 0, width: 50, height: 1000 }],
    ];

    for (const area of areas) {
      const recorded = fakeContext();
      const drawn = drawMeasurements(
        recorded.context,
        placement,
        state({ measurements: [left, right] }),
        style,
        1,
        area,
      );
      expect(measurementsTouch(placement, state({ measurements: [left, right] }), 1, area)).toBe(
        drawn > 0,
      );
    }
  });

  it('перетаскиваемая фигура отвечает по перетаскиваемой геометрии', () => {
    // Вершину утащили в полосу: пока жест идёт, в полосе есть что рисовать.
    const area = [{ x: 850, y: 0, width: 150, height: 1000 }];
    const dragged = state({
      measurements: [left],
      dragOverride: { id: 'left', points: [p(0.9, 0.5)] },
    });

    expect(measurementsTouch(placement, dragged, 1, area)).toBe(true);
    expect(measurementsTouch(placement, state({ measurements: [left] }), 1, area)).toBe(false);
  });

  it('черновик задевает любую полосу: он под курсором и дёшев', () => {
    expect(
      measurementsTouch(placement, state({ draft: [p(0.1, 0.1)], draftType: 'polyline' }), 1, [
        { x: 900, y: 900, width: 10, height: 10 },
      ]),
    ).toBe(true);
  });

  it('черновик рисуется и в полосе: он часть того же слоя', () => {
    const recorded = fakeContext();

    drawMeasurements(
      recorded.context,
      placement,
      state({ draft: [p(0.1, 0.5), p(0.9, 0.5)], draftType: 'line' }),
      style,
      1,
      [{ x: 850, y: 0, width: 150, height: 1000 }],
    );

    expect(recorded.dashes).toContainEqual([6, 4]);
  });
});

describe('попадание курсора', () => {
  it('находит линию рядом с курсором', () => {
    const line = measurement();

    expect(hitTestMeasurements([line], p(0.5, 0.5), placement)?.id).toBe('m1');
  });

  it('не находит линию вдалеке', () => {
    const line = measurement();

    expect(hitTestMeasurements([line], p(0.5, 0.9), placement)).toBeNull();
  });

  it('находит метку счёта', () => {
    const mark = measurement({ geometryType: 'count', points: [p(0.5, 0.5)] });

    expect(hitTestMeasurements([mark], p(0.5, 0.5), placement)?.id).toBe('m1');
  });

  it('попадание внутрь многоугольника засчитывается', () => {
    const area = measurement({
      geometryType: 'polygon',
      points: [p(0.1, 0.1), p(0.9, 0.1), p(0.9, 0.9), p(0.1, 0.9)],
    });

    expect(hitTestMeasurements([area], p(0.5, 0.5), placement)?.id).toBe('m1');
  });

  it('из перекрывающихся побеждает меньшая', () => {
    // Крупная фигура обычно окружает мелкие: выбирать нужно то, во что целились.
    const big = measurement({
      id: 'big',
      geometryType: 'polygon',
      points: [p(0, 0), p(1, 0), p(1, 1), p(0, 1)],
    });
    const small = measurement({
      id: 'small',
      geometryType: 'polygon',
      points: [p(0.4, 0.4), p(0.6, 0.4), p(0.6, 0.6), p(0.4, 0.6)],
    });

    expect(hitTestMeasurements([big, small], p(0.5, 0.5), placement)?.id).toBe('small');
  });

  it('работает на любом масштабе', () => {
    // Попадание считается в экранных пикселях, но точка приходит нормализованной:
    // на другом масштабе выбор обязан вести себя так же.
    const zoomed: SheetPlacement = { ...placement, width: 4000, height: 4000 };
    const line = measurement();

    expect(hitTestMeasurements([line], p(0.5, 0.5), zoomed)?.id).toBe('m1');
  });

  it('пустой список ничего не находит', () => {
    expect(hitTestMeasurements([], p(0.5, 0.5), placement)).toBeNull();
  });
});

describe('попадание по вершине', () => {
  const points = [p(0.1, 0.1), p(0.9, 0.1), p(0.9, 0.9)];

  it('находит ближайшую вершину', () => {
    expect(hitTestVertex(points, p(0.9, 0.1), placement)).toBe(1);
  });

  it('не находит вершину вдалеке', () => {
    expect(hitTestVertex(points, p(0.5, 0.5), placement)).toBeNull();
  });

  it('на приближённом листе вершина всё ещё находится', () => {
    const zoomed: SheetPlacement = { ...placement, width: 5000, height: 5000 };

    expect(hitTestVertex(points, p(0.1, 0.1), zoomed)).toBe(0);
  });
});
