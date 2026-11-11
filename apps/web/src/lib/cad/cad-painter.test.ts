import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { SheetPlacement } from '@/lib/viewer/coordinates';

import { createCadPainter, type ICadPaintData } from './cad-painter';
import type { INormalizedPath } from './frame';

/** `Path2D` jsdom не даёт: заглушка запоминает команды и вложенные пути. */
class FakePath2D {
  static created = 0;
  readonly ops: [string, ...number[]][] = [];
  readonly added: FakePath2D[] = [];
  constructor() {
    FakePath2D.created += 1;
  }
  moveTo(x: number, y: number) {
    this.ops.push(['moveTo', x, y]);
  }
  lineTo(x: number, y: number) {
    this.ops.push(['lineTo', x, y]);
  }
  closePath() {
    this.ops.push(['closePath']);
  }
  addPath(path: FakePath2D) {
    this.added.push(path);
  }
}

beforeAll(() => {
  vi.stubGlobal('Path2D', FakePath2D);
});
afterAll(() => {
  vi.unstubAllGlobals();
});

const PLACEMENT: SheetPlacement = { x: 0, y: 0, width: 1000, height: 500, rotation: 0 };

const path = (points: number[], extra: Partial<INormalizedPath> = {}): INormalizedPath => {
  const xs = points.filter((_, index) => index % 2 === 0);
  const ys = points.filter((_, index) => index % 2 === 1);
  return {
    layer: 0,
    closed: false,
    fill: false,
    points: new Float64Array(points),
    bounds: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    ...extra,
  };
};

const data = (patch: Partial<ICadPaintData> = {}): ICadPaintData => ({
  paths: [path([0.1, 0.1, 0.2, 0.2])],
  visibleLayers: new Set([0]),
  opacity: 0.5,
  layerColors: [],
  ink: 'ink',
  paper: null,
  crop: null,
  ...patch,
});

/** Двумерный контекст-заглушка: jsdom его не даёт. Записывает вызовы. */
const fakeContext = () => {
  const calls: string[] = [];
  const record = (name: string) => vi.fn(() => void calls.push(name));
  const context = {
    canvas: { width: 1000, height: 500 },
    setTransform: record('setTransform'),
    save: record('save'),
    restore: record('restore'),
    beginPath: record('beginPath'),
    rect: record('rect'),
    clip: record('clip'),
    clearRect: record('clearRect'),
    scale: record('scale'),
    translate: record('translate'),
    fillRect: record('fillRect'),
    moveTo: record('moveTo'),
    lineTo: record('lineTo'),
    closePath: record('closePath'),
    stroke: record('stroke'),
    fill: record('fill'),
    strokeRect: record('strokeRect'),
    setLineDash: record('setLineDash'),
    globalAlpha: 1,
  } as unknown as CanvasRenderingContext2D;
  return { context, calls };
};

/** Контекст, который запоминает цвет в момент каждой обводки и заливки. */
const colorRecorder = () => {
  const strokes: string[] = [];
  const fills: string[] = [];
  const context = {
    canvas: { width: 1000, height: 500 },
    strokeStyle: '',
    fillStyle: '',
    globalAlpha: 1,
    lineWidth: 1,
    lineJoin: 'miter',
    setTransform: () => undefined,
    save: () => undefined,
    restore: () => undefined,
    beginPath: () => undefined,
    rect: () => undefined,
    clip: () => undefined,
    clearRect: () => undefined,
    scale: () => undefined,
    translate: () => undefined,
    fillRect: () => undefined,
    moveTo: () => undefined,
    lineTo: () => undefined,
    closePath: () => undefined,
    stroke: () => void strokes.push(String(context.strokeStyle)),
    fill: () => void fills.push(String(context.fillStyle)),
    strokeRect: () => undefined,
    setLineDash: () => undefined,
  };
  return { context: context as unknown as CanvasRenderingContext2D, strokes, fills };
};

describe('createCadPainter', () => {
  it('каждый слой рисуется своим цветом, слой без цвета - чернилами', () => {
    const { context, strokes } = colorRecorder();
    createCadPainter(
      data({
        paths: [
          path([0.1, 0.1, 0.2, 0.2], { layer: 0 }),
          path([0.3, 0.1, 0.4, 0.2], { layer: 1 }),
          path([0.5, 0.1, 0.6, 0.2], { layer: 2 }),
          path([0.7, 0.1, 0.8, 0.2], { layer: 1 }),
        ],
        visibleLayers: new Set([0, 1, 2]),
        layerColors: ['red', 'green'],
      }),
    ).paint(context, PLACEMENT, 1, null);
    // Слои 0 и 1 - по обводке своего цвета (слой 1 - одна на два пути), слой 2 - чернила.
    expect([...strokes].sort()).toEqual(['green', 'ink', 'red']);
  });

  it('скрытый слой не рисуется даже своим цветом', () => {
    const { context, strokes } = colorRecorder();
    createCadPainter(
      data({
        paths: [path([0.1, 0.1, 0.2, 0.2], { layer: 0 }), path([0.3, 0.1, 0.4, 0.2], { layer: 1 })],
        visibleLayers: new Set([1]),
        layerColors: ['red', 'green'],
      }),
    ).paint(context, PLACEMENT, 1, null);
    expect(strokes).toEqual(['green']);
  });

  it('заливка берёт цвет своего слоя', () => {
    const { context, fills } = colorRecorder();
    createCadPainter(
      data({
        paths: [path([0.1, 0.1, 0.3, 0.1, 0.3, 0.3], { layer: 1, closed: true, fill: true })],
        visibleLayers: new Set([1]),
        layerColors: ['red', 'green'],
      }),
    ).paint(context, PLACEMENT, 1, null);
    expect(fills).toEqual(['green']);
  });

  it('рисует видимый слой и пропускает скрытый', () => {
    const shown = fakeContext();
    createCadPainter(data()).paint(shown.context, PLACEMENT, 1, null);
    expect(shown.calls).toContain('stroke');

    const hidden = fakeContext();
    createCadPainter(data({ visibleLayers: new Set<number>() })).paint(
      hidden.context,
      PLACEMENT,
      1,
      null,
    );
    expect(hidden.calls).not.toContain('stroke');
  });

  it('пути строятся один раз в листовых единицах, на кадре - перенос и масштаб', () => {
    const { context } = fakeContext();
    const placement = { ...PLACEMENT, x: 10, y: 20 };
    createCadPainter(data()).paint(context, placement, 1, null);
    expect(context.translate).toHaveBeenCalledWith(10, 20);
    // 1000 px ширины на 1000 единиц пути: масштаб 1 по обеим осям (пропорции листа 0,5 учтены в пути).
    expect(context.scale).toHaveBeenCalledWith(1, 1);
    const [path] = vi.mocked(context.stroke).mock.calls[0] as unknown as [FakePath2D];
    expect(path.ops).toEqual([
      ['moveTo', 0.1 * 1000, 0.1 * 500],
      ['lineTo', 0.2 * 1000, 0.2 * 500],
    ]);
  });

  it('Path2D кешируется на массиве путей: новый рисовальщик (смена слоя) их не пересобирает', () => {
    const paths = [
      path([0.1, 0.1, 0.2, 0.2], { layer: 0 }),
      path([0.3, 0.1, 0.4, 0.2], { layer: 1 }),
    ];
    const first = fakeContext();
    createCadPainter(data({ paths, visibleLayers: new Set([0, 1]) })).paint(
      first.context,
      PLACEMENT,
      1,
      null,
    );
    const before = FakePath2D.created;
    const second = fakeContext();
    const painter = createCadPainter(data({ paths, visibleLayers: new Set([1]) }));
    painter.paint(second.context, PLACEMENT, 1, null);
    painter.paint(second.context, PLACEMENT, 1, null);
    expect(FakePath2D.created).toBe(before);
  });

  it('слои одного цвета склеиваются в один проход', () => {
    const { context } = fakeContext();
    createCadPainter(
      data({
        paths: [path([0.1, 0.1, 0.2, 0.2], { layer: 0 }), path([0.3, 0.1, 0.4, 0.2], { layer: 1 })],
        visibleLayers: new Set([0, 1]),
        layerColors: ['red', 'red'],
      }),
    ).paint(context, PLACEMENT, 1, null);
    expect(context.stroke).toHaveBeenCalledTimes(1);
  });

  it('замкнутая заливка закрывает контур и заливает', () => {
    const { context, calls } = fakeContext();
    createCadPainter(
      data({ paths: [path([0.1, 0.1, 0.3, 0.1, 0.3, 0.3], { closed: true, fill: true })] }),
    ).paint(context, PLACEMENT, 1, null);
    expect(calls).toContain('fill');
    const [fillPath] = vi.mocked(context.fill).mock.calls[0] as unknown as [FakePath2D];
    expect(fillPath.ops.at(-1)).toEqual(['closePath']);
  });

  it('touches: пути вне полосы - рисовать нечего, внутри - есть', () => {
    const painter = createCadPainter(data());
    // Путь занимает экранные x 100-200, y 50-100.
    expect(painter.touches(PLACEMENT, 1, [{ x: 800, y: 0, width: 100, height: 500 }])).toBe(false);
    expect(painter.touches(PLACEMENT, 1, [{ x: 150, y: 0, width: 100, height: 500 }])).toBe(true);
  });

  it('touches: скрытый слой не считается содержимым', () => {
    const painter = createCadPainter(data({ visibleLayers: new Set<number>() }));
    expect(painter.touches(PLACEMENT, 1, [{ x: 0, y: 0, width: 1000, height: 500 }])).toBe(false);
  });

  it('бумага автономного просмотра есть всегда, пока она в полосе', () => {
    const painter = createCadPainter(data({ paper: 'paper', paths: [] }));
    expect(painter.touches(PLACEMENT, 1, [{ x: 0, y: 0, width: 100, height: 100 }])).toBe(true);
    const { context, calls } = fakeContext();
    painter.paint(context, PLACEMENT, 1, null);
    expect(calls).toContain('fillRect');
  });

  it('рамка контекста масштаба рисуется пунктиром поверх', () => {
    const painter = createCadPainter(
      data({ paths: [], crop: { rect: [0.1, 0.1, 0.5, 0.5], color: 'crop' } }),
    );
    const { context, calls } = fakeContext();
    painter.paint(context, PLACEMENT, 1, null);
    expect(calls).toContain('strokeRect');
    expect(context.strokeRect).toHaveBeenCalledWith(100, 50, 400, 200);
    expect(painter.touches(PLACEMENT, 1, [{ x: 0, y: 0, width: 1000, height: 500 }])).toBe(true);
  });
});
