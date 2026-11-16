import { describe, expect, it, vi } from 'vitest';

import { createFacadesPainter, facadeColor, type IFacadeColors } from './facades-painter';

const colors: IFacadeColors = {
  accepted: 'green',
  candidate: 'blue',
  rejected: 'gray',
  danger: 'red',
};

const view = (id: string, status: 'accepted' | 'candidate' | 'rejected') => ({
  id,
  status,
  bbox: [0.1, 0.1, 0.5, 0.5] as [number, number, number, number],
  windows: [
    {
      bbox: [0.2, 0.2, 0.25, 0.3] as [number, number, number, number],
      height_mm: 1,
      source: 'observed' as const,
      width_mm: 1,
      z_bottom_mm: 0,
      z_top_mm: 1,
    },
  ],
});

const placement = { x: 0, y: 0, width: 1000, height: 1000, rotation: 0 as const };
const area = [{ x: 0, y: 0, width: 1000, height: 1000 }];

const mockContext = () => {
  const strokes: { rect: number[]; style: string; width: number }[] = [];
  const state = { strokeStyle: '', lineWidth: 0 };
  const context = {
    canvas: { width: 1000, height: 1000 },
    setTransform: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    scale: vi.fn(),
    clearRect: vi.fn(),
    setLineDash: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn((...rect: number[]) =>
      strokes.push({ rect, style: state.strokeStyle, width: state.lineWidth }),
    ),
    set strokeStyle(value: string) {
      state.strokeStyle = value;
    },
    set lineWidth(value: number) {
      state.lineWidth = value;
    },
    set fillStyle(_value: string) {},
    set globalAlpha(_value: number) {},
  } as unknown as CanvasRenderingContext2D;
  return { context, strokes };
};

describe('createFacadesPainter', () => {
  it('цвет берётся по статусу', () => {
    expect(facadeColor(colors, 'accepted')).toBe('green');
    expect(facadeColor(colors, 'candidate')).toBe('blue');
    expect(facadeColor(colors, 'rejected')).toBe('gray');
  });

  it('рисует рамку вида и рамки окон своим цветом', () => {
    const { context, strokes } = mockContext();
    createFacadesPainter({ views: [view('a', 'accepted')], colors, activeId: null }, { clear: true }).paint(
      context,
      placement,
      1,
      null,
    );
    expect(strokes).toHaveLength(2);
    expect(strokes[0]?.rect).toEqual([100, 100, 400, 400]);
    expect(strokes[0]?.style).toBe('green');
  });

  it('выбранный вид толще и рисуется последним', () => {
    const { context, strokes } = mockContext();
    createFacadesPainter(
      { views: [view('a', 'candidate'), view('b', 'rejected')], colors, activeId: 'a' },
      { clear: true },
    ).paint(context, placement, 1, null);
    expect(strokes).toHaveLength(4);
    const frames = strokes.filter((item) => item.rect[2] === 400);
    expect(frames[0]?.style).toBe('gray');
    expect(frames[1]?.style).toBe('blue');
    expect(frames[1]?.width).toBeGreaterThan(frames[0]?.width ?? 0);
  });

  it('touches: есть что рисовать только в видимой области рамок', () => {
    const painter = createFacadesPainter(
      { views: [view('a', 'candidate')], colors, activeId: null },
      { clear: true },
    );
    expect(painter.touches(placement, 1, area)).toBe(true);
    expect(painter.touches(placement, 1, [{ x: 800, y: 800, width: 100, height: 100 }])).toBe(false);
  });
});
