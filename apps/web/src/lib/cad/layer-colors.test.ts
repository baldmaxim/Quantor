import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  assignLayerColors,
  CAD_LAYER_PALETTE_SIZE,
  layerColorSlot,
  layerColorToken,
  layerColorVar,
} from './layer-colors';

describe('layerColorSlot', () => {
  it('идёт по порядку и замыкается по размеру палитры', () => {
    expect(layerColorSlot(0)).toBe(0);
    expect(layerColorSlot(5)).toBe(5);
    expect(layerColorSlot(CAD_LAYER_PALETTE_SIZE)).toBe(0);
    expect(layerColorSlot(CAD_LAYER_PALETTE_SIZE + 3)).toBe(3);
  });

  it('соседние слои - разные цвета', () => {
    for (let index = 0; index < CAD_LAYER_PALETTE_SIZE * 2; index += 1) {
      expect(layerColorSlot(index)).not.toBe(layerColorSlot(index + 1));
    }
  });

  it('детерминирован и устойчив к мусору на входе', () => {
    expect(layerColorSlot(7)).toBe(layerColorSlot(7));
    expect(layerColorSlot(-1)).toBe(CAD_LAYER_PALETTE_SIZE - 1);
    expect(layerColorSlot(Number.NaN)).toBe(0);
    expect(layerColorSlot(2.9)).toBe(2);
  });
});

describe('токены слоя', () => {
  it('токен нумеруется с единицы, var() ссылается на него', () => {
    expect(layerColorToken(0)).toBe('--cad-layer-1');
    expect(layerColorToken(11)).toBe('--cad-layer-12');
    expect(layerColorToken(12)).toBe('--cad-layer-1');
    expect(layerColorVar(2)).toBe('var(--cad-layer-3)');
  });
});

describe('assignLayerColors', () => {
  const palette = ['a', 'b', 'c'];

  it('красит слои по порядку палитры', () => {
    expect(assignLayerColors(palette, 2)).toEqual(['a', 'b']);
  });

  it('палитра короче числа слоёв - цвета повторяются, пустой палитре цвета нет', () => {
    expect(
      assignLayerColors(
        Array.from({ length: 12 }, (_, i) => `c${i}`),
        14,
      ),
    ).toEqual([...Array.from({ length: 12 }, (_, i) => `c${i}`), 'c0', 'c1']);
    expect(assignLayerColors([], 3)).toEqual([]);
    expect(assignLayerColors(palette, 0)).toEqual([]);
  });
});

/** Токены в глобальном CSS обязаны быть для обеих тем и читаться на бумаге листа и на панели. */
describe('палитра в base.css', () => {
  // vitest запускается из apps/web.
  const css = readFileSync(resolve(process.cwd(), '../../packages/ui/src/base.css'), 'utf-8');

  const blockAfter = (opener: string): string => {
    const start = css.indexOf(opener);
    expect(start).toBeGreaterThanOrEqual(0);
    return css.slice(start, css.indexOf('\n}', start));
  };
  const token = (block: string, name: string): string => {
    const match = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(block);
    expect(match, name).not.toBeNull();
    return match?.[1] ?? '#000000';
  };
  const channel = (value: number): number => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (hex: string): number => {
    const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const contrast = (a: string, b: string): number => {
    const [x, y] = [luminance(a), luminance(b)];
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };

  const themes = [
    { name: 'светлая', block: () => blockAfter(':root {'), paper: '--canvas', panel: '--surface' },
    {
      name: 'тёмная (явная)',
      block: () => blockAfter(":root[data-theme='dark'] {"),
      paper: '--canvas',
      panel: '--surface',
    },
    {
      name: 'тёмная (системная)',
      block: () => blockAfter(":root:not([data-theme='light']) {"),
      paper: '--canvas',
      panel: '--surface',
    },
  ];

  for (const theme of themes) {
    it(`${theme.name} тема: все цвета заданы, различимы и контрастны (>= 3:1)`, () => {
      const block = theme.block();
      const colors = Array.from({ length: CAD_LAYER_PALETTE_SIZE }, (_, index) =>
        token(block, `--cad-layer-${index + 1}`).toLowerCase(),
      );
      expect(new Set(colors).size).toBe(CAD_LAYER_PALETTE_SIZE);
      // Бумага листа и панель в тёмной теме объявлены в этом же блоке; в светлой - тоже.
      const paper = token(block, theme.paper);
      const panel = token(block, theme.panel);
      for (const color of colors) {
        expect(contrast(color, paper)).toBeGreaterThanOrEqual(3);
        expect(contrast(color, panel)).toBeGreaterThanOrEqual(3);
      }
    });
  }
});
