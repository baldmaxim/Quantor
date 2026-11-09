import { describe, expect, it, vi } from 'vitest';

import type { SheetPlacement } from '@/lib/viewer/coordinates';

import { createCadPainter, type ICadPaintData } from './cad-painter';
import type { INormalizedPath } from './frame';

const PLACEMENT: SheetPlacement = { x: 0, y: 0, width: 1000, height: 500, rotation: 0 };

const path = (
  points: number[],
  extra: Partial<INormalizedPath> = {},
): INormalizedPath => {
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

describe('createCadPainter', () => {
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

  it('ставит точки по размещению листа', () => {
    const { context } = fakeContext();
    const placement = { ...PLACEMENT, x: 10, y: 20 };
    createCadPainter(data()).paint(context, placement, 1, null);
    expect(context.moveTo).toHaveBeenCalledWith(10 + 0.1 * 1000, 20 + 0.1 * 500);
    expect(context.lineTo).toHaveBeenCalledWith(10 + 0.2 * 1000, 20 + 0.2 * 500);
  });

  it('замкнутая заливка закрывает контур и заливает', () => {
    const { context, calls } = fakeContext();
    createCadPainter(
      data({ paths: [path([0.1, 0.1, 0.3, 0.1, 0.3, 0.3], { closed: true, fill: true })] }),
    ).paint(context, PLACEMENT, 1, null);
    expect(calls).toContain('fill');
    expect(calls).toContain('closePath');
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
