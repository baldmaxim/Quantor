/**
 * Слой черновика калибровки.
 *
 * Проверяется то, что видит пользователь: где оказались точки на холсте, пунктирная линия
 * до второго щелчка или сплошная после, и что чужой слой не тронут. Координаты сверяются
 * с ожидаемыми числами: ошибка здесь выглядит как «точка встала не туда, куда я щёлкнул».
 */

import { describe, expect, it, vi } from 'vitest';

import type { SheetPlacement } from '@/lib/viewer/coordinates';
import type { ScaleDraftState } from '@/lib/viewer/scale-draft';
import { drawScaleDraft, scaleDraftTouches } from '@/lib/viewer/scale-overlay';

const placement: SheetPlacement = { x: 0, y: 0, width: 1000, height: 2000, rotation: 0 };
const style = { color: '#14539e' };

interface Recorded {
  context: CanvasRenderingContext2D;
  arcs: { x: number; y: number }[];
  lines: { x: number; y: number }[];
  moves: { x: number; y: number }[];
  dashes: number[][];
  cleared: number;
  strokes: number;
  fills: number;
}

const fakeContext = (): Recorded => {
  const arcs: Recorded['arcs'] = [];
  const lines: Recorded['lines'] = [];
  const moves: Recorded['moves'] = [];
  const dashes: number[][] = [];
  const counters = { cleared: 0, strokes: 0, fills: 0 };

  const context = {
    canvas: { width: 1000, height: 2000 },
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    setTransform: vi.fn(),
    clearRect: vi.fn(() => {
      counters.cleared += 1;
    }),
    beginPath: vi.fn(),
    moveTo: vi.fn((x: number, y: number) => {
      moves.push({ x, y });
    }),
    lineTo: vi.fn((x: number, y: number) => {
      lines.push({ x, y });
    }),
    arc: vi.fn((x: number, y: number) => {
      arcs.push({ x, y });
    }),
    fill: vi.fn(() => {
      counters.fills += 1;
    }),
    stroke: vi.fn(() => {
      counters.strokes += 1;
    }),
    setLineDash: vi.fn((pattern: number[]) => {
      dashes.push([...pattern]);
    }),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 0,
  } as unknown as CanvasRenderingContext2D;

  return {
    context,
    arcs,
    lines,
    moves,
    dashes,
    get cleared() {
      return counters.cleared;
    },
    get strokes() {
      return counters.strokes;
    },
    get fills() {
      return counters.fills;
    },
  };
};

const state = (overrides: Partial<ScaleDraftState> = {}): ScaleDraftState => ({
  phase: 'idle',
  a: null,
  b: null,
  hover: null,
  ...overrides,
});

describe('слой черновика калибровки', () => {
  it('очищает холст перед каждой отрисовкой', () => {
    // Без очистки резиновая линия оставляла бы за собой веер прошлых положений.
    const recorded = fakeContext();

    drawScaleDraft(recorded.context, placement, state(), style);

    expect(recorded.cleared).toBe(1);
  });

  it('на пустом черновике рисует только перекрестие под курсором', () => {
    const recorded = fakeContext();

    const drawn = drawScaleDraft(
      recorded.context,
      placement,
      state({ hover: { x: 0.5, y: 0.25 } }),
      style,
    );

    expect(drawn).toBe(0);
    // Перекрестие — две линии через точку (500, 500).
    expect(recorded.moves).toContainEqual({ x: 500 - 12, y: 500 });
    expect(recorded.moves).toContainEqual({ x: 500, y: 500 - 12 });
    expect(recorded.arcs).toHaveLength(0);
  });

  it('без курсора и без точек не рисует ничего', () => {
    const recorded = fakeContext();

    const drawn = drawScaleDraft(recorded.context, placement, state(), style);

    expect(drawn).toBe(0);
    expect(recorded.arcs).toHaveLength(0);
    expect(recorded.strokes).toBe(0);
  });

  it('первую точку ставит там, куда щёлкнули', () => {
    const recorded = fakeContext();

    const drawn = drawScaleDraft(
      recorded.context,
      placement,
      state({ phase: 'awaiting-second', a: { x: 0.25, y: 0.5 }, hover: { x: 0.25, y: 0.5 } }),
      style,
    );

    expect(drawn).toBe(1);
    // 0.25 от ширины 1000 и 0.5 от высоты 2000.
    expect(recorded.arcs).toContainEqual({ x: 250, y: 1000 });
  });

  it('до второго щелчка линия пунктирная', () => {
    // Предварительная линия не должна выглядеть как результат.
    const recorded = fakeContext();

    drawScaleDraft(
      recorded.context,
      placement,
      state({ phase: 'awaiting-second', a: { x: 0.25, y: 0.5 }, hover: { x: 0.75, y: 0.5 } }),
      style,
    );

    expect(recorded.dashes[0]).toEqual([6, 4]);
    expect(recorded.moves).toContainEqual({ x: 250, y: 1000 });
    expect(recorded.lines).toContainEqual({ x: 750, y: 1000 });
  });

  it('после второго щелчка линия сплошная и точек две', () => {
    const recorded = fakeContext();

    const drawn = drawScaleDraft(
      recorded.context,
      placement,
      state({ phase: 'complete', a: { x: 0.25, y: 0.5 }, b: { x: 0.75, y: 0.5 } }),
      style,
    );

    expect(drawn).toBe(2);
    expect(recorded.dashes[0]).toEqual([]);
    expect(recorded.arcs).toContainEqual({ x: 250, y: 1000 });
    expect(recorded.arcs).toContainEqual({ x: 750, y: 1000 });
  });

  it('учитывает плотность пикселей', () => {
    // Холст слоя и холст страницы обязаны совпадать пиксель в пиксель, иначе линия
    // «плывёт» относительно чертежа на дробных масштабах.
    const recorded = fakeContext();

    drawScaleDraft(recorded.context, placement, state({ hover: { x: 0.5, y: 0.5 } }), style, 2);

    expect(recorded.context.scale).toHaveBeenCalledWith(2, 2);
  });

  it('пустой черновик нечего рисовать, с курсором или точкой — есть', () => {
    // Панорама не трогает холст пустого слоя; перекрестие под курсором — уже содержимое.
    expect(scaleDraftTouches(state())).toBe(false);
    expect(scaleDraftTouches(state({ hover: { x: 0.5, y: 0.5 } }))).toBe(true);
    expect(scaleDraftTouches(state({ phase: 'awaiting-second', a: { x: 0.1, y: 0.1 } }))).toBe(
      true,
    );
  });
});
