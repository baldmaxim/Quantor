import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Чернила по бумаге не зависят от темы.
 *
 * Лист чертежа светлый в обеих темах — это осознанно: бумага белая при любом оформлении.
 * Поэтому всё, что рисуется поверх листа, обязано быть тёмным всегда. Токен интерфейса
 * вроде `--accent` для этого не годится: в тёмной теме он светлеет до `#5fa2e8`, что на
 * кремовой бумаге даёт 2.2:1 — линию на листе почти не видно.
 *
 * Ошибка уже случалась дважды: сначала поле ввода покрасили цветом бумаги, потом линии
 * обмера — цветом интерфейса. Оба раза увидеть это можно было только глазами и только в
 * тёмной теме.
 */

const BASE_CSS = join(process.cwd(), '..', '..', 'packages', 'ui', 'src', 'base.css');
/**
 * Исходники просмотрщика, где цвета читаются из токенов. Весь каталог, а не один файл: чтение
 * цветов уже переезжало из `DrawingViewport` в хук слоёв, и проверка одного файла тихо
 * превращалась в проверку ничего.
 */
const VIEWER_DIR = join(process.cwd(), 'src', 'components', 'viewer');

/** Токены, которыми рисуют поверх листа. */
const SHEET_TOKENS = [
  '--canvas-ink',
  '--region-text',
  '--region-image',
  '--region-stamp',
  '--sheet-ink',
  '--sheet-ink-danger',
];

const countDefinitions = (css: string, token: string): number =>
  css.split('\n').filter((line) => new RegExp(`^\\s*${token}\\s*:`).test(line)).length;

describe('чернила по бумаге', () => {
  const css = readFileSync(BASE_CSS, 'utf8');

  it.each(SHEET_TOKENS)('%s объявлен ровно один раз', (token) => {
    // Второе объявление означало бы переопределение в теме — то есть светлый штрих по
    // светлой бумаге в одной из них.
    expect(countDefinitions(css, token)).toBe(1);
  });

  it('токены темы для листа светлые в обеих темах', () => {
    // Не проверка контраста, а фиксация причины: бумага остаётся светлой, и это намеренно.
    const declarations = css.split('\n').filter((line) => /^\s*--canvas\s*:/.test(line));

    expect(declarations).toHaveLength(3); // светлая, media-тёмная, явная тёмная
    for (const line of declarations) {
      const value = line.split(':')[1]?.trim().replace(';', '') ?? '';
      const channels =
        value
          .slice(1)
          .match(/../g)
          ?.map((pair) => parseInt(pair, 16)) ?? [];
      expect(Math.min(...channels)).toBeGreaterThan(0x80);
    }
  });

  it('просмотрщик не берёт цвет интерфейса для рисования по листу', () => {
    const sources = readdirSync(VIEWER_DIR)
      .filter((name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name))
      .map((name) => readFileSync(join(VIEWER_DIR, name), 'utf8'));
    const uiTokens = sources.flatMap((source) =>
      [...source.matchAll(/getPropertyValue\('(--[a-z-]+)'\)/g)].map((match) => match[1]),
    );

    // Пустой список означал бы, что чтение цветов переехало туда, куда проверка не смотрит.
    expect(uiTokens.length).toBeGreaterThan(0);
    for (const token of uiTokens) {
      expect(SHEET_TOKENS).toContain(token);
    }
  });
});
