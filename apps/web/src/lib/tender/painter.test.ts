import { describe, expect, it } from 'vitest';

import { element, layer, polyline } from './fixtures';
import { buildTenderPaintData } from './geometry';
import { LABEL_MIN_SHEET_PX, createTenderPainter } from './painter';

const FRAME = { originX: 100, originY: 700, mmPerPt: 10 };
const PAGE = { width: 1000, height: 800 };

const dataOf = (patch: Partial<Parameters<typeof buildTenderPaintData>[0]> = {}) => {
  const built = buildTenderPaintData({
    layers: [layer()],
    frame: FRAME,
    page: PAGE,
    colorOf: () => 'red',
    accent: 'blue',
    halo: 'white',
    selected: null,
    ...patch,
  });
  if (built === null) throw new Error('нет данных');
  return built;
};

/** Холст-подставка: записывает вызовы, рисует ничего. */
const fakeContext = (size = { width: 1200, height: 900 }) => {
  const calls: string[] = [];
  const context = new Proxy(
    { canvas: size, calls } as Record<string, unknown>,
    {
      get: (target, key: string) => {
        if (key in target) return target[key];
        return (...args: unknown[]) => {
          calls.push(key === 'fillText' ? `fillText:${String(args[0])}` : key);
        };
      },
      set: (target, key: string, value: unknown) => {
        target[key] = value;
        if (key === 'strokeStyle') calls.push(`strokeStyle:${String(value)}`);
        return true;
      },
    },
  );
  return { context: context as unknown as CanvasRenderingContext2D, calls };
};

const placement = (width: number) => ({
  x: 0,
  y: 0,
  width,
  height: (width * PAGE.height) / PAGE.width,
  rotation: 0 as const,
});

describe('рисовальщик слоя «Расчёты»', () => {
  it('рисует линии и значки; контекст возвращается в прежнее состояние', () => {
    const { context, calls } = fakeContext();
    createTenderPainter(dataOf(), { clear: false }).paint(context, placement(1000), 1, null);
    expect(calls.filter((name) => name === 'stroke').length).toBeGreaterThanOrEqual(2);
    expect(calls.at(-1)).toBe('restore');
    expect(calls).not.toContain('clearRect');
  });

  it('слой без других рисовальщиков чистит холст сам', () => {
    const { context, calls } = fakeContext();
    createTenderPainter(dataOf(), { clear: true }).paint(context, placement(1000), 1, null);
    expect(calls).toContain('clearRect');
  });

  it('подпись марки - только при крупном зуме', () => {
    const small = fakeContext();
    createTenderPainter(dataOf(), { clear: false }).paint(small.context, placement(1000), 1, null);
    expect(small.calls.some((name) => name.startsWith('fillText'))).toBe(false);
    const large = fakeContext({ width: 4000, height: 3000 });
    createTenderPainter(dataOf(), { clear: false }).paint(
      large.context,
      placement(LABEL_MIN_SHEET_PX),
      1,
      null,
    );
    expect(large.calls).toContain('fillText:КВ-2');
  });

  it('объекты вне видимой области не рисуются, а touches это знает', () => {
    const painter = createTenderPainter(dataOf(), { clear: false });
    const visible = [{ x: 0, y: 0, width: 1200, height: 900 }];
    const away = [{ x: 5000, y: 5000, width: 100, height: 100 }];
    expect(painter.touches(placement(1000), 1, visible)).toBe(true);
    expect(painter.touches(placement(1000), 1, away)).toBe(false);
    const { context, calls } = fakeContext();
    painter.paint(context, placement(1000), 1, away);
    expect(calls).not.toContain('stroke');
  });

  it('стояк в одной точке плана - круг, а не линия нулевой длины', () => {
    const riser = polyline({ kind: 'riser', pts: [[1000, 2000, 0], [1000, 2000, 2800]] });
    const { context, calls } = fakeContext();
    createTenderPainter(
      dataOf({ layers: [layer({ polylines: [riser], elements: [element({ pos: [9000, 100, 0] })] })] }),
      { clear: false },
    ).paint(context, placement(1000), 1, null);
    expect(calls).toContain('arc');
  });

  it('выбранный объект рисуется последним и цветом выделения', () => {
    const shared = layer();
    const selected = dataOf({ layers: [shared] }).paths[0]?.ref ?? null;
    const painter = createTenderPainter(dataOf({ layers: [shared], selected }), { clear: false });
    const { context, calls } = fakeContext();
    painter.paint(context, placement(1000), 1, null);
    const styles = calls.filter((name) => name.startsWith('strokeStyle:'));
    // Сначала прибор своим цветом, последней - выбранная линия цветом выделения.
    expect(styles).toContain('strokeStyle:red');
    expect(styles.at(-1)).toBe('strokeStyle:blue');
  });
});
