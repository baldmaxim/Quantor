import { describe, expect, it, vi } from 'vitest';

import type { SectionLevelRead } from '@quantor/api-client';

import { bandAlpha, createSectionsPainter, levelColor, type ISectionColors } from './sections-painter';

const colors: ISectionColors = {
  accepted: 'green',
  candidate: 'blue',
  rejected: 'gray',
  danger: 'red',
};

describe('цвет и заливка по статусу', () => {
  it('цвет берётся по статусу', () => {
    expect(levelColor(colors, 'accepted')).toBe('green');
    expect(levelColor(colors, 'candidate')).toBe('blue');
    expect(levelColor(colors, 'rejected')).toBe('gray');
  });
  it('принятое закрашено сильнее кандидата, отклонённое - слабее всех', () => {
    expect(bandAlpha('accepted')).toBeGreaterThan(bandAlpha('candidate'));
    expect(bandAlpha('candidate')).toBeGreaterThan(bandAlpha('rejected'));
  });
});

const level = {
  id: 'l1',
  status: 'candidate',
  markup: {
    band: [0.1, 0.1, 0.3, 0.3],
    upper_mark: [0.1, 0.1, 0.2, 0.12],
    lower_mark: [0.1, 0.28, 0.2, 0.3],
    dims: [{ value_mm: 3000, role: 'clear', bbox: [0.4, 0.1, 0.45, 0.3] }],
  },
} as unknown as SectionLevelRead;

const placement = { x: 0, y: 0, width: 1000, height: 1000, rotation: 0 as const };
const area = [{ x: 0, y: 0, width: 1000, height: 1000 }];

describe('createSectionsPainter', () => {
  it('рисует полосу, две отметки и размер; лист кладётся без поворота', () => {
    const calls: number[][] = [];
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
      strokeRect: vi.fn((...args: number[]) => calls.push(args)),
    } as unknown as CanvasRenderingContext2D;
    const painter = createSectionsPainter(
      { levels: [level], issues: [{ bbox: [0.5, 0.5, 0.6, 0.6] }], colors, activeId: null },
      { clear: true },
    );
    painter.paint(context, placement, 1, null);
    // полоса + верхняя + нижняя отметки + размер + замечание
    expect(calls).toHaveLength(5);
    expect(calls[0]).toEqual([100, 100, 200, 200]);
  });

  it('touches: есть что рисовать только в полосе с разметкой', () => {
    const painter = createSectionsPainter(
      { levels: [level], issues: [], colors, activeId: null },
      { clear: true },
    );
    expect(painter.touches(placement, 1, area)).toBe(true);
    expect(painter.touches(placement, 1, [{ x: 800, y: 800, width: 100, height: 100 }])).toBe(false);
  });
});
