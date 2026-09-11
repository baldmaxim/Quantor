import { describe, expect, it, vi } from 'vitest';

import type { SheetPlacement } from './coordinates';
import type { PixelRect } from './layer-paint';
import {
  planLayerUpdate,
  ViewportLayer,
  type LayerPainter,
  type LayerView,
  type PaintedLayer,
} from './viewport-layer';

/**
 * Слой, который догоняет камеру сдвигом пикселей (ADR-0025).
 *
 * Ошибка здесь видна как фигуры, отставшие от листа на долю пикселя и копящие отставание,
 * «хвосты» старых фигур в открывшейся полосе или слой, мыльный после зума. Поэтому проверяется
 * арифметика сдвига и то, какие полосы и в какой раскладке уходят рисовальщику.
 */

const PAGE = { width: 2384, height: 1684 };

const view = (overrides: Partial<LayerView> = {}): LayerView => ({
  camera: { scale: 2.66, offsetX: -3000.25, offsetY: -1500.5 },
  page: PAGE,
  width: 1600,
  height: 1000,
  ratio: 1.5,
  ...overrides,
});

const paintedAt = (current: LayerView): PaintedLayer => ({
  scale: current.camera.scale,
  offsetX: current.camera.offsetX,
  offsetY: current.camera.offsetY,
  pageWidth: current.page.width,
  pageHeight: current.page.height,
  width: current.width,
  height: current.height,
  ratio: current.ratio,
});

const moved = (base: LayerView, dx: number, dy: number): LayerView => ({
  ...base,
  camera: {
    ...base.camera,
    offsetX: base.camera.offsetX + dx,
    offsetY: base.camera.offsetY + dy,
  },
});

describe('план обновления слоя', () => {
  it('ненарисованный слой рисуется целиком', () => {
    expect(planLayerUpdate(null, view())).toEqual({ kind: 'repaint' });
  });

  it('другая плотность, размер области или лист — целиком', () => {
    const painted = paintedAt(view());

    expect(planLayerUpdate(painted, view({ ratio: 2 })).kind).toBe('repaint');
    expect(planLayerUpdate(painted, view({ width: 1200 })).kind).toBe('repaint');
    expect(planLayerUpdate(painted, view({ page: { width: 1684, height: 2384 } })).kind).toBe(
      'repaint',
    );
  });

  it('панорама вправо-вниз сдвигает пиксели и открывает левую и верхнюю полосы', () => {
    const start = view();
    // 100 CSS-пикселей на плотности 1,5 — ровно 150 физических.
    const update = planLayerUpdate(paintedAt(start), moved(start, 100, 40));

    expect(update).toEqual({
      kind: 'shift',
      dx: 150,
      dy: 60,
      strips: [
        { x: 0, y: 0, width: 150, height: 1500 },
        { x: 0, y: 0, width: 2400, height: 60 },
      ],
      offsetX: start.camera.offsetX + 100,
      offsetY: start.camera.offsetY + 40,
      transform: '',
    });
  });

  it('панорама влево-вверх открывает правую и нижнюю полосы', () => {
    const start = view();
    const update = planLayerUpdate(paintedAt(start), moved(start, -20, -10));
    if (update.kind !== 'shift') throw new Error('ожидался сдвиг');

    expect(update.strips).toEqual<PixelRect[]>([
      { x: 2370, y: 0, width: 30, height: 1500 },
      { x: 0, y: 1485, width: 2400, height: 15 },
    ]);
  });

  it('дробный сдвиг: пиксели — на целое, остаток — CSS-сдвигом холста', () => {
    const start = view();
    // 10,3 CSS-пикселя — 15,45 физических: сдвиг на 15, остаток 0,45 физических = 0,3 CSS.
    const update = planLayerUpdate(paintedAt(start), moved(start, 10.3, 0));
    if (update.kind !== 'shift') throw new Error('ожидался сдвиг');

    expect(update.dx).toBe(15);
    expect(update.offsetX).toBeCloseTo(start.camera.offsetX + 10, 10);
    const residual = /translate\(([-\d.e]+)px, ([-\d.e]+)px\)/.exec(update.transform);
    expect(Number(residual?.[1])).toBeCloseTo(0.3, 10);
  });

  it('остаток не копится: сотня мелких кадров сходится к камере', () => {
    let current = view();
    let painted = paintedAt(current);
    for (let frame = 0; frame < 100; frame += 1) {
      current = moved(current, 0.77, -0.31);
      const update = planLayerUpdate(painted, current);
      if (update.kind !== 'shift') throw new Error('ожидался сдвиг');
      painted = { ...painted, offsetX: update.offsetX, offsetY: update.offsetY };
    }

    // Пиксели отстают от камеры меньше чем на половину физического пикселя.
    expect(Math.abs(current.camera.offsetX - painted.offsetX) * 1.5).toBeLessThanOrEqual(0.5);
    expect(Math.abs(current.camera.offsetY - painted.offsetY) * 1.5).toBeLessThanOrEqual(0.5);
  });

  it('сдвиг больше холста — целиком', () => {
    const start = view();
    expect(planLayerUpdate(paintedAt(start), moved(start, 1700, 0)).kind).toBe('repaint');
  });

  it('зум посреди жеста растягивает холст, а не перерисовывает', () => {
    const start = view();
    const zoomed: LayerView = {
      ...start,
      camera: { scale: 5.32, offsetX: -6500, offsetY: -3400 },
    };
    const update = planLayerUpdate(paintedAt(start), zoomed);
    if (update.kind !== 'stretch') throw new Error('ожидалось растяжение');

    // Точка листа, нарисованная при прежней камере, после растяжения встаёт туда, куда её
    // поставила бы новая камера.
    const match = /translate\(([-\d.e]+)px, ([-\d.e]+)px\) scale\(([-\d.e]+)\)/.exec(
      update.transform,
    );
    const [tx, ty, k] = [Number(match?.[1]), Number(match?.[2]), Number(match?.[3])];
    const point = { x: 0.4, y: 0.6 };
    const paintedX = start.camera.offsetX + point.x * PAGE.width * start.camera.scale;
    const paintedY = start.camera.offsetY + point.y * PAGE.height * start.camera.scale;
    expect(tx + k * paintedX).toBeCloseTo(zoomed.camera.offsetX + point.x * PAGE.width * 5.32, 6);
    expect(ty + k * paintedY).toBeCloseTo(zoomed.camera.offsetY + point.y * PAGE.height * 5.32, 6);
  });
});

/** Холст с записывающим контекстом: что копировалось и где рисовал рисовальщик. */
const fakeCanvas = () => {
  const draws: { image: unknown; x: number; y: number; operation: string }[] = [];
  const context = {
    save: vi.fn(),
    restore: vi.fn(),
    setTransform: vi.fn(),
    globalCompositeOperation: 'source-over',
    drawImage(image: unknown, x: number, y: number) {
      draws.push({ image, x, y, operation: this.globalCompositeOperation });
    },
  };
  const canvas = {
    width: 0,
    height: 0,
    style: { width: '', height: '', transform: '' },
    getContext: () => context,
  } as unknown as HTMLCanvasElement;
  return { canvas, draws };
};

describe('слой на холсте', () => {
  /**
   * Рисовальщик, который записывает вызовы. `content` — прямоугольник в CSS-пикселях экрана при
   * текущей раскладке, где «есть фигура»: по нему отвечает `touches`. Нет — рисовать везде есть что.
   */
  const recordingPainter = (
    content?: (placement: SheetPlacement) => {
      x: number;
      y: number;
      width: number;
      height: number;
    },
  ) => {
    const calls: { placement: SheetPlacement; area: readonly PixelRect[] | null }[] = [];
    const painter: LayerPainter = {
      paint: (_context, placement, _ratio, area) => {
        calls.push({ placement, area });
      },
      touches: (placement, ratio, area) => {
        if (!content) return true;
        const figure = content(placement);
        return area.some(
          (rect) =>
            figure.x + figure.width >= rect.x / ratio &&
            figure.x <= (rect.x + rect.width) / ratio &&
            figure.y + figure.height >= rect.y / ratio &&
            figure.y <= (rect.y + rect.height) / ratio,
        );
      },
    };
    return { painter, calls };
  };

  it('первый кадр рисует слой целиком в размер области', () => {
    const { canvas } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);

    layer.follow(view(), painter);

    expect(canvas.width).toBe(2400);
    expect(canvas.height).toBe(1500);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.area).toBeNull();
    expect(calls[0]?.placement.x).toBe(-3000.25);
  });

  it('панорама копирует холст в себя и дорисовывает полосы по сдвинутой раскладке', () => {
    const { canvas, draws } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 100, 0), painter);

    expect(draws).toEqual([{ image: canvas, x: 150, y: 0, operation: 'copy' }]);
    expect(calls[1]?.area).toEqual([{ x: 0, y: 0, width: 150, height: 1500 }]);
    // Раскладка полос — та, которой соответствуют пиксели после сдвига.
    expect(calls[1]?.placement.x).toBeCloseTo(start.camera.offsetX + 100, 10);
    expect(layer.getPainted()?.offsetX).toBeCloseTo(start.camera.offsetX + 100, 10);
    expect(canvas.style.transform).toBe('');
  });

  it('в полосах рисовать нечего — холст не трогается, сдвигает CSS', () => {
    // Фигура в центре области; панорама открывает левую полосу, где пусто.
    const { canvas, draws } = fakeCanvas();
    const { painter, calls } = recordingPainter((placement) => ({
      x: placement.x + 3200,
      y: placement.y + 2000,
      width: 20,
      height: 20,
    }));
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 40, 0), painter);
    layer.follow(moved(start, 90, 0), painter);

    expect(draws).toHaveLength(0);
    expect(calls).toHaveLength(1);
    // Пиксели лежат там, где нарисованы, — CSS сдвигает холст на всё пройденное расстояние.
    expect(layer.getPainted()?.offsetX).toBe(start.camera.offsetX);
    const shift = /translate\(([-\d.e]+)px, ([-\d.e]+)px\)/.exec(canvas.style.transform);
    expect(Number(shift?.[1])).toBeCloseTo(90, 10);
  });

  it('фигура вошла в накопленную полосу — копия на весь путь и дорисовка всей полосы', () => {
    // Фигура левее области на 150 CSS-пикселей: в кадр она входит после сдвига дальше 150.
    const { canvas, draws } = fakeCanvas();
    const figure = (placement: SheetPlacement) => ({
      x: placement.x + 3000.25 - 150,
      y: placement.y + 1500.5 + 100,
      width: 10,
      height: 10,
    });
    const { painter, calls } = recordingPainter(figure);
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 100, 0), painter);
    expect(draws).toHaveLength(0);

    layer.follow(moved(start, 200, 0), painter);
    // 200 CSS-пикселей на плотности 1,5 — 300 физических: накопленный путь целиком.
    expect(draws).toEqual([{ image: canvas, x: 300, y: 0, operation: 'copy' }]);
    expect(calls.at(-1)?.area).toEqual([{ x: 0, y: 0, width: 300, height: 1500 }]);
    expect(canvas.style.transform).toBe('');
  });

  it('пустой холст и пустой вид — сдвиг за край холста ничего не перерисовывает', () => {
    const { canvas, draws } = fakeCanvas();
    // Фигура далеко за пределами любого вида в этом тесте.
    const { painter, calls } = recordingPainter(() => ({
      x: 1e9,
      y: 1e9,
      width: 1,
      height: 1,
    }));
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 5000, 0), painter);

    expect(draws).toHaveLength(0);
    expect(calls).toHaveLength(1);
    expect(layer.getPainted()?.offsetX).toBe(start.camera.offsetX + 5000);
    expect(canvas.style.transform).toBe('');
  });

  it('холст с фигурами при сдвиге за его край перерисовывается целиком', () => {
    const { canvas } = fakeCanvas();
    // Фигура в левом верхнем углу исходного вида: после ухода за край её не должно остаться.
    const { painter, calls } = recordingPainter((placement) => ({
      x: placement.x + 3000.25 + 10,
      y: placement.y + 1500.5 + 10,
      width: 10,
      height: 10,
    }));
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 5000, 0), painter);

    expect(calls).toHaveLength(2);
    expect(calls[1]?.area).toBeNull();
  });

  it('сдвиг меньше физического пикселя не трогает пиксели, только CSS', () => {
    const { canvas, draws } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    layer.follow(moved(start, 0.2, 0), painter);

    expect(draws).toHaveLength(0);
    expect(calls).toHaveLength(1);
    const residual = /translate\(([-\d.e]+)px, ([-\d.e]+)px\)/.exec(canvas.style.transform);
    expect(Number(residual?.[1])).toBeCloseTo(0.2, 10);
    expect(Number(residual?.[2])).toBe(0);
  });

  it('зум растягивает, а затихание жеста перерисовывает резко и снимает растяжение', () => {
    const { canvas } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);

    const zoomed: LayerView = { ...start, camera: { ...start.camera, scale: 3 } };
    layer.follow(zoomed, painter);
    expect(calls).toHaveLength(1);
    expect(canvas.style.transform).toContain('scale(');

    layer.settle(zoomed, painter);
    expect(calls).toHaveLength(2);
    expect(calls[1]?.area).toBeNull();
    expect(canvas.style.transform).toBe('');
  });

  it('затихание после чистой панорамы ничего не перерисовывает', () => {
    const { canvas } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);
    layer.follow(moved(start, 50, 50), painter);

    layer.settle(moved(start, 50, 50), painter);

    expect(calls).toHaveLength(2);
  });

  it('данные изменились — перерисовка целиком по точной камере', () => {
    const { canvas } = fakeCanvas();
    const { painter, calls } = recordingPainter();
    const layer = new ViewportLayer(canvas);
    const start = view();
    layer.follow(start, painter);
    layer.follow(moved(start, 10.3, 0), painter);

    layer.repaint(moved(start, 10.3, 0), painter);

    expect(calls.at(-1)?.area).toBeNull();
    expect(calls.at(-1)?.placement.x).toBeCloseTo(start.camera.offsetX + 10.3, 10);
    expect(canvas.style.transform).toBe('');
  });
});
