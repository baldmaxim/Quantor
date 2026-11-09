import { describe, expect, it } from 'vitest';

import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { composePainters, createRemarksPainter, type IRemarkPaintData } from './remarks-painter';

const COLORS = { open: 'red', resolved: 'purple', onOpen: 'white', paper: 'ivory' };
const PLACEMENT = { x: 100, y: 50, width: 1000, height: 800, rotation: 0 as const };

const data = (patch: Partial<IRemarkPaintData> = {}): IRemarkPaintData => ({
  marks: [
    { id: 'a', number: 1, status: 'open', rect: [0.1, 0.1, 0.2, 0.3] },
    { id: 'b', number: 2, status: 'resolved', rect: [0.5, 0.5, 0.6, 0.7] },
  ],
  colors: COLORS,
  activeId: null,
  ...patch,
});

/** Контекст-пустышка: записывает вызовы рисования. */
const recording = () => {
  const calls: { name: string; args: unknown[]; dash: number[]; fill: unknown; stroke: unknown }[] = [];
  const state = { dash: [] as number[], fill: '', stroke: '' };
  const context = new Proxy(
    { canvas: { width: 2000, height: 1000 }, measureText: () => ({ width: 10 }) },
    {
      get: (target, key) => {
        if (key in target) return Reflect.get(target, key);
        if (key === 'setLineDash') return (dash: number[]) => void (state.dash = dash);
        return (...args: unknown[]) =>
          void calls.push({
            name: String(key),
            args,
            dash: state.dash,
            fill: state.fill,
            stroke: state.stroke,
          });
      },
      set: (_target, key, value) => {
        if (key === 'fillStyle') state.fill = value;
        if (key === 'strokeStyle') state.stroke = value;
        return true;
      },
    },
  ) as unknown as CanvasRenderingContext2D;
  return { context, calls };
};

describe('рисовальщик отметок', () => {
  it('рисует прямоугольник по доле листа и размещению', () => {
    const { context, calls } = recording();
    createRemarksPainter(data(), { clear: true }).paint(context, PLACEMENT, 1, null);
    const rects = calls.filter((call) => call.name === 'strokeRect' && call.stroke === 'red');
    // Рамка отметки 1: x = 100 + 0.1*1000, y = 50 + 0.1*800, 100 x 160.
    expect(rects[0]?.args).toEqual([200, 130, 100, 160]);
  });

  it('проверенное нарисовано пунктиром, открытое - сплошной', () => {
    const { context, calls } = recording();
    createRemarksPainter(data(), { clear: true }).paint(context, PLACEMENT, 1, null);
    const open = calls.find((call) => call.name === 'strokeRect' && call.stroke === 'red');
    const resolved = calls.find((call) => call.name === 'strokeRect' && call.stroke === 'purple');
    expect(open?.dash).toEqual([]);
    expect(resolved?.dash.length).toBeGreaterThan(0);
  });

  it('поверх чужого слоя (clear: false) холст не очищается', () => {
    const over = recording();
    createRemarksPainter(data(), { clear: false }).paint(over.context, PLACEMENT, 1, null);
    expect(over.calls.some((call) => call.name === 'clearRect')).toBe(false);
    const alone = recording();
    createRemarksPainter(data(), { clear: true }).paint(alone.context, PLACEMENT, 1, null);
    expect(alone.calls.some((call) => call.name === 'clearRect')).toBe(true);
  });

  it('touches: полоса без отметок - нет, с отметкой - да', () => {
    const painter = createRemarksPainter(data(), { clear: true });
    expect(painter.touches(PLACEMENT, 1, [{ x: 1500, y: 0, width: 400, height: 1000 }])).toBe(false);
    expect(painter.touches(PLACEMENT, 1, [{ x: 150, y: 100, width: 100, height: 100 }])).toBe(true);
  });

  it('вне полосы отметка не рисуется', () => {
    const { context, calls } = recording();
    createRemarksPainter(data(), { clear: true }).paint(context, PLACEMENT, 1, [
      { x: 1500, y: 0, width: 400, height: 1000 },
    ]);
    expect(calls.some((call) => call.name === 'strokeRect')).toBe(false);
  });
});

describe('композиция рисовальщиков', () => {
  const stub = (log: string[], name: string, touches: boolean): LayerPainter => ({
    paint: () => void log.push(name),
    touches: () => touches,
  });

  it('пустая композиция - нет слоя; один - он сам', () => {
    expect(composePainters(null, null)).toBeNull();
    const only = stub([], 'a', true);
    expect(composePainters(null, only)).toBe(only);
  });

  it('рисует по порядку, touches - если хоть один касается', () => {
    const log: string[] = [];
    const composed = composePainters(stub(log, 'cad', false), null, stub(log, 'marks', true));
    composed?.paint({} as CanvasRenderingContext2D, PLACEMENT, 1, null);
    expect(log).toEqual(['cad', 'marks']);
    expect(composed?.touches(PLACEMENT, 1, [])).toBe(true);
  });
});
