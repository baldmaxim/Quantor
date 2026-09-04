import { beforeEach, describe, expect, it, vi } from 'vitest';

import { drawOverlay, resizeOverlay, type OverlayRegion } from './overlay';
import type { SheetPlacement } from './coordinates';

/**
 * Слой распознанных областей.
 *
 * Проверяется то, что видно пользователю: скрытые типы не рисуются, полигон рисуется
 * полигоном, а координаты на холсте совпадают с нормализованными. Ошибка здесь выглядит
 * как «разметка не совпадает с чертежом» — самый дорогой класс дефектов в продукте.
 */

const placement: SheetPlacement = {
  x: 0,
  y: 0,
  width: 1000,
  height: 2000,
  rotation: 0,
};

const region = (overrides: Partial<OverlayRegion> = {}): OverlayRegion => ({
  id: 'r1',
  blockType: 'text',
  shapeType: 'rectangle',
  coords: [0.1, 0.2, 0.6, 0.4],
  polygon: null,
  ...overrides,
});

const style = {
  colors: { text: '#14539e', image: '#6d28d9', stamp: '#92400e' },
  fallbackColor: '#000000',
};

interface FakeContext {
  context: CanvasRenderingContext2D;
  rects: { x: number; y: number; width: number; height: number }[];
  strokes: number;
  paths: number;
  cleared: number;
}

const fakeContext = (): FakeContext => {
  const rects: FakeContext['rects'] = [];
  const state = { strokes: 0, paths: 0, cleared: 0 };

  const context = {
    canvas: { width: 1000, height: 2000 },
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    clearRect: vi.fn(() => {
      state.cleared += 1;
    }),
    fillRect: vi.fn((x: number, y: number, width: number, height: number) => {
      rects.push({ x, y, width, height });
    }),
    strokeRect: vi.fn(() => {
      state.strokes += 1;
    }),
    beginPath: vi.fn(() => {
      state.paths += 1;
    }),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    globalAlpha: 1,
    lineWidth: 1,
    fillStyle: '',
    strokeStyle: '',
  } as unknown as CanvasRenderingContext2D;

  return {
    context,
    rects,
    get strokes() {
      return state.strokes;
    },
    get paths() {
      return state.paths;
    },
    get cleared() {
      return state.cleared;
    },
  };
};

describe('слой областей', () => {
  let fake: FakeContext;

  beforeEach(() => {
    fake = fakeContext();
  });

  const draw = (
    regions: OverlayRegion[],
    overrides: Partial<Parameters<typeof drawOverlay>[2]> = {},
  ) =>
    drawOverlay(
      fake.context,
      placement,
      { regions, hiddenTypes: new Set(), selectedId: null, hoveredId: null, ...overrides },
      style,
    );

  it('холст очищается перед каждой отрисовкой', () => {
    draw([region()]);

    expect(fake.cleared).toBe(1);
  });

  it('прямоугольник ложится по нормализованным координатам', () => {
    draw([region()]);

    expect(fake.rects[0]).toEqual({ x: 100, y: 400, width: 500, height: 400 });
  });

  it('скрытый тип не рисуется', () => {
    const drawn = draw([region(), region({ id: 'r2', blockType: 'stamp' })], {
      hiddenTypes: new Set(['stamp']),
    });

    expect(drawn).toBe(1);
    expect(fake.rects).toHaveLength(1);
  });

  it('пустой список областей не роняет отрисовку', () => {
    expect(draw([])).toBe(0);
  });

  it('полигон рисуется контуром, а не прямоугольником', () => {
    draw([
      region({
        shapeType: 'polygon',
        polygon: [
          [0.1, 0.1],
          [0.9, 0.1],
          [0.5, 0.8],
        ],
      }),
    ]);

    expect(fake.paths).toBe(1);
    expect(fake.rects).toHaveLength(0);
  });

  it('полигон без точек рисуется как прямоугольник, а не пропадает', () => {
    // Экспорт иногда объявляет форму полигоном, но точек не даёт: терять область нельзя.
    draw([region({ shapeType: 'polygon', polygon: null })]);

    expect(fake.rects).toHaveLength(1);
  });

  it('выбранная область рисуется толще обычной', () => {
    draw([region()], { selectedId: 'r1' });
    const selectedWidth = fake.context.lineWidth;

    const plain = fakeContext();
    drawOverlay(
      plain.context,
      placement,
      { regions: [region()], hiddenTypes: new Set(), selectedId: null, hoveredId: null },
      style,
    );

    expect(selectedWidth).toBeGreaterThan(plain.context.lineWidth);
  });

  it('неизвестный тип области рисуется запасным цветом, а не пропадает', () => {
    const drawn = draw([region({ blockType: 'нечто' })]);

    expect(drawn).toBe(1);
  });

  it('область с перевёрнутыми углами всё равно получает положительные размеры', () => {
    draw([region({ coords: [0.6, 0.4, 0.1, 0.2] })]);

    expect(fake.rects[0]?.width).toBeGreaterThan(0);
    expect(fake.rects[0]?.height).toBeGreaterThan(0);
  });
});

describe('размер холста слоя', () => {
  it('учитывает плотность экрана', () => {
    const canvas = { width: 0, height: 0, style: {} } as HTMLCanvasElement;

    resizeOverlay(canvas, 500, 300, 2);

    expect(canvas.width).toBe(1000);
    expect(canvas.height).toBe(600);
    expect(canvas.style.width).toBe('500px');
  });

  it('не трогает холст, если размер не изменился', () => {
    const canvas = { width: 500, height: 300, style: {} } as HTMLCanvasElement;
    const before = canvas.width;

    resizeOverlay(canvas, 500, 300, 1);

    expect(canvas.width).toBe(before);
  });

  it('нулевой размер не приводит к нулевому холсту', () => {
    const canvas = { width: 0, height: 0, style: {} } as HTMLCanvasElement;

    resizeOverlay(canvas, 0, 0, 1);

    expect(canvas.width).toBeGreaterThan(0);
    expect(canvas.height).toBeGreaterThan(0);
  });
});
