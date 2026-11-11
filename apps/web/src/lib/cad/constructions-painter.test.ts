import { describe, expect, it } from 'vitest';

import { construction } from './constructions-fixtures';
import { buildShapes } from './constructions';
import { createConstructionsPainter, type IConstructionPaintData } from './constructions-painter';

const COLORS = { masonry: 'brown', monolith: 'indigo', check: 'amber', accent: 'blue', notInVor: 'red' };
const FRAME = { originX: 100, originY: 500, mmPerPt: 10 };
const PAGE = { width: 1000, height: 1000 };
const PLACEMENT = { x: 0, y: 0, width: 1000, height: 1000, rotation: 0 as const };

const recording = () => {
  const calls: { name: string; args: unknown[]; fill: unknown; stroke: unknown; alpha: number; width: number }[] = [];
  const state = { fill: '', stroke: '', alpha: 1, width: 1 };
  const context = new Proxy(
    { canvas: { width: 1000, height: 1000 } },
    {
      get: (target, key) => {
        if (key in target) return Reflect.get(target, key);
        return (...args: unknown[]) =>
          void calls.push({ name: String(key), args, fill: state.fill, stroke: state.stroke, alpha: state.alpha, width: state.width });
      },
      set: (_target, key, value) => {
        if (key === 'fillStyle') state.fill = value;
        if (key === 'strokeStyle') state.stroke = value;
        if (key === 'globalAlpha') state.alpha = value;
        if (key === 'lineWidth') state.width = value;
        return true;
      },
    },
  ) as unknown as CanvasRenderingContext2D;
  return { context, calls };
};

const data = (selected: string[] = []): IConstructionPaintData => ({
  shapes: buildShapes(
    [
      construction({ id: 'm' }),
      construction({ id: 'c', kind: 'monolith_wall' }),
      construction({
        id: 'k',
        computed: { ...construction({ id: 'x' }).computed, status: 'thickness_check' },
      }),
      construction({ id: 'acc', accepted: true }),
    ],
    FRAME,
    PAGE,
  ),
  colors: COLORS,
  selected: new Set(selected),
});

describe('рисовальщик конструкций', () => {
  it('кладка, монолит и «проверить» - разные токены заливки, заливка evenodd', () => {
    const { context, calls } = recording();
    createConstructionsPainter(data(), { clear: true }).paint(context, PLACEMENT, 1, null);
    const fills = calls.filter((call) => call.name === 'fill');
    expect(new Set(fills.map((call) => call.fill))).toEqual(new Set(['brown', 'indigo', 'amber']));
    expect(fills.every((call) => call.args[0] === 'evenodd')).toBe(true);
  });

  it('принятая заливка плотнее, выделенная - контур акцента потолще', () => {
    const { context, calls } = recording();
    createConstructionsPainter(data(['m']), { clear: true }).paint(context, PLACEMENT, 1, null);
    const fills = calls.filter((call) => call.name === 'fill');
    const plain = fills.find((call) => call.fill === 'indigo');
    const accepted = fills.filter((call) => call.fill === 'brown').map((call) => call.alpha);
    expect(Math.max(...accepted)).toBeGreaterThan(plain?.alpha ?? 1);
    const strokes = calls.filter((call) => call.name === 'stroke');
    const selectedStroke = strokes.find((call) => call.stroke === 'blue');
    expect(selectedStroke).toBeDefined();
    expect(selectedStroke?.width).toBeGreaterThan(Math.max(...strokes.filter((c) => c.stroke !== 'blue').map((c) => c.width)));
    // Выделенная рисуется последней.
    expect(calls.filter((call) => call.name === 'stroke').at(-1)?.stroke).toBe('blue');
  });

  it('поверх чужого слоя (clear: false) холст не очищается', () => {
    const over = recording();
    createConstructionsPainter(data(), { clear: false }).paint(over.context, PLACEMENT, 1, null);
    expect(over.calls.some((call) => call.name === 'clearRect')).toBe(false);
    const alone = recording();
    createConstructionsPainter(data(), { clear: true }).paint(alone.context, PLACEMENT, 1, null);
    expect(alone.calls.some((call) => call.name === 'clearRect')).toBe(true);
  });

  it('вне полосы ничего не рисуется; touches согласован с paint', () => {
    const painter = createConstructionsPainter(data(), { clear: true });
    const strip = [{ x: 0, y: 800, width: 1000, height: 200 }];
    const { context, calls } = recording();
    painter.paint(context, PLACEMENT, 1, strip);
    expect(calls.some((call) => call.name === 'fill')).toBe(false);
    expect(painter.touches(PLACEMENT, 1, strip)).toBe(false);
    expect(painter.touches(PLACEMENT, 1, [{ x: 100, y: 480, width: 100, height: 40 }])).toBe(true);
  });
});

describe('подсветка «не в ВОР»', () => {
  const hatched = (notInVor: ReadonlySet<string> | undefined) => {
    const { context, calls } = recording();
    createConstructionsPainter({ ...data(), notInVor }, { clear: true }).paint(context, PLACEMENT, 1, null);
    return calls.filter((call) => call.stroke === 'red' && call.name === 'stroke');
  };

  it('без набора (ВОР не загружен или подсветка выключена) токен «не в ВОР» не используется', () => {
    expect(hatched(undefined)).toHaveLength(0);
    expect(hatched(new Set())).toHaveLength(0);
  });

  it('конструкция из набора: штриховка и пунктирный контур токеном, остальные без них', () => {
    const { context, calls } = recording();
    createConstructionsPainter({ ...data(), notInVor: new Set(['m']) }, { clear: true }).paint(
      context,
      PLACEMENT,
      1,
      null,
    );
    const strokes = calls.filter((call) => call.stroke === 'red' && call.name === 'stroke');
    // Штриховка и контур - по одной конструкции 'm'.
    expect(strokes).toHaveLength(2);
    expect(calls.some((call) => call.name === 'clip')).toBe(true);
    expect(calls.filter((call) => call.name === 'setLineDash').some((call) => (call.args[0] as number[]).length > 0)).toBe(true);
  });
});

