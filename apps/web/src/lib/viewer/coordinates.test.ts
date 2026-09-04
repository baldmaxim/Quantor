import { describe, expect, it } from 'vitest';

import {
  hitTest,
  normalizeRotation,
  placeSheet,
  rectContains,
  toNormalizedPoint,
  toScreenPoint,
  toScreenRect,
  unrotateUnitPoint,
  type NormalizedRect,
  type Rotation,
  type SheetPlacement,
} from './coordinates';

// Лист 1000×2000 пикселей, размещённый со смещением 100/50 — намеренно несимметрично,
// чтобы перепутанные оси были видны сразу.
const placement = (rotation: Rotation = 0): SheetPlacement => ({
  x: 100,
  y: 50,
  width: rotation === 90 || rotation === 270 ? 2000 : 1000,
  height: rotation === 90 || rotation === 270 ? 1000 : 2000,
  rotation,
});

describe('преобразование координат', () => {
  it('левый верхний угол листа попадает в его начало на экране', () => {
    expect(toScreenPoint({ x: 0, y: 0 }, placement())).toEqual({ x: 100, y: 50 });
  });

  it('правый нижний угол попадает в противоположный край', () => {
    expect(toScreenPoint({ x: 1, y: 1 }, placement())).toEqual({ x: 1100, y: 2050 });
  });

  it('центр остаётся центром', () => {
    expect(toScreenPoint({ x: 0.5, y: 0.5 }, placement())).toEqual({ x: 600, y: 1050 });
  });

  it('прямоугольник переводится с сохранением размеров', () => {
    const rect: NormalizedRect = [0.1, 0.2, 0.6, 0.4];

    expect(toScreenRect(rect, placement())).toEqual({
      x: 200,
      y: 450,
      width: 500,
      height: 400,
    });
  });
});

describe('поворот страницы', () => {
  it.each<Rotation>([0, 90, 180, 270])(
    'обратное преобразование возвращает исходную точку при повороте %s',
    (rotation) => {
      const source = { x: 0.23, y: 0.71 };

      const screen = toScreenPoint(source, placement(rotation));
      const back = toNormalizedPoint(screen, placement(rotation));

      expect(back.x).toBeCloseTo(source.x, 10);
      expect(back.y).toBeCloseTo(source.y, 10);
    },
  );

  it('поворот на 90° переносит левый верхний угол вправо вверх', () => {
    const screen = toScreenPoint({ x: 0, y: 0 }, placement(90));

    expect(screen).toEqual({ x: 2100, y: 50 });
  });

  it('поворот на 180° меняет углы местами', () => {
    const screen = toScreenPoint({ x: 0, y: 0 }, placement(180));

    expect(screen).toEqual({ x: 1100, y: 2050 });
  });

  it('прямоугольник после поворота остаётся с положительными размерами', () => {
    const rect: NormalizedRect = [0.1, 0.2, 0.6, 0.4];

    const screen = toScreenRect(rect, placement(90));

    expect(screen.width).toBeGreaterThan(0);
    expect(screen.height).toBeGreaterThan(0);
  });

  it('двойное обратное преобразование единичной точки тождественно', () => {
    const point = { x: 0.3, y: 0.8 };

    for (const rotation of [0, 90, 180, 270] as const) {
      const there = unrotateUnitPoint(point, rotation);
      expect(there.x).toBeGreaterThanOrEqual(0);
      expect(there.y).toBeGreaterThanOrEqual(0);
    }
  });

  it('произвольный угол приводится к допустимому', () => {
    expect(normalizeRotation(0)).toBe(0);
    expect(normalizeRotation(90)).toBe(90);
    expect(normalizeRotation(-90)).toBe(270);
    expect(normalizeRotation(450)).toBe(90);
    expect(normalizeRotation(37)).toBe(0);
  });
});

describe('размещение листа', () => {
  it('при повороте на 90° стороны меняются местами', () => {
    const placed = placeSheet(
      { widthPx: 2481, heightPx: 3509, rotation: 90 },
      { scale: 0.5, offsetX: 0, offsetY: 0 },
    );

    expect(placed.width).toBeCloseTo(3509 * 0.5);
    expect(placed.height).toBeCloseTo(2481 * 0.5);
  });

  it('без поворота стороны сохраняются', () => {
    const placed = placeSheet(
      { widthPx: 2481, heightPx: 3509, rotation: 0 },
      { scale: 1, offsetX: 10, offsetY: 20 },
    );

    expect(placed).toEqual({ x: 10, y: 20, width: 2481, height: 3509, rotation: 0 });
  });
});

describe('попадание в область', () => {
  const outer = { coords_norm: [0.0, 0.0, 1.0, 1.0] };
  const inner = { coords_norm: [0.4, 0.4, 0.6, 0.6] };
  const aside = { coords_norm: [0.8, 0.05, 0.95, 0.15] };

  it('точка внутри прямоугольника засчитывается', () => {
    expect(rectContains([0.1, 0.1, 0.9, 0.9], { x: 0.5, y: 0.5 })).toBe(true);
  });

  it('точка снаружи не засчитывается', () => {
    expect(rectContains([0.1, 0.1, 0.4, 0.4], { x: 0.5, y: 0.5 })).toBe(false);
  });

  it('из перекрывающихся выбирается наименьшая', () => {
    // Крупный блок обычно окружает мелкие: выбирать нужно то, во что целились.
    expect(hitTest([outer, inner], { x: 0.5, y: 0.5 })).toBe(inner);
  });

  it('порядок в списке не влияет на выбор', () => {
    expect(hitTest([inner, outer], { x: 0.5, y: 0.5 })).toBe(inner);
  });

  it('вне всех областей возвращается null', () => {
    expect(hitTest([inner, aside], { x: 0.01, y: 0.99 })).toBeNull();
  });

  it('область с испорченными координатами пропускается', () => {
    const broken = { coords_norm: [0.1, 0.2] };

    expect(hitTest([broken, inner], { x: 0.5, y: 0.5 })).toBe(inner);
  });

  it('перевёрнутый прямоугольник всё равно ловит точку', () => {
    // Экспорт иногда меняет углы местами; отбрасывать такую область нельзя.
    expect(rectContains([0.9, 0.9, 0.1, 0.1], { x: 0.5, y: 0.5 })).toBe(true);
  });
});
