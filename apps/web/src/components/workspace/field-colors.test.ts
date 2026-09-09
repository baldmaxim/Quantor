import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Цвет бумаги чертежа — не цвет поля ввода.
 *
 * `--canvas` остаётся светлым и в тёмной теме: лист бумаги белый при любом оформлении.
 * Поле ввода, покрашенное этим токеном, получает светлый фон и светлый текст — набранное
 * становится невидимым. Ошибка нашлась на живой приёмке, когда в диалог масштаба вводили
 * известный размер и не видели, что вводят.
 *
 * Проверка читает исходники: увидеть такое можно только глазами в тёмной теме, а глаз
 * на каждый рендер не поставишь.
 */

const SRC = join(process.cwd(), 'src');

const componentFiles = (directory: string): string[] => {
  const found: string[] = [];

  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...componentFiles(full));
    else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) found.push(full);
  }

  return found;
};

/** Открывающие теги полей ввода вместе с их атрибутами. */
const fieldTags = (source: string): string[] =>
  [...source.matchAll(/<(?:input|textarea|select)\b[^>]*>/g)].map((match) => match[0]);

describe('цвета полей ввода', () => {
  it('ни одно поле не покрашено цветом бумаги чертежа', () => {
    const offenders: string[] = [];

    for (const path of componentFiles(SRC)) {
      for (const tag of fieldTags(readFileSync(path, 'utf8'))) {
        if (/\bbg-canvas\b/.test(tag)) {
          offenders.push(path.replace(SRC, '').replaceAll('\\', '/'));
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('поля задают цвет текста явно', () => {
    // Наследование цвета от родителя и есть причина ошибки: фон переопределили, текст —
    // нет, и они совпали. Явный цвет делает пару видимой в одном месте.
    const offenders: string[] = [];

    for (const path of componentFiles(SRC)) {
      for (const tag of fieldTags(readFileSync(path, 'utf8'))) {
        const styled = /\bbg-[a-z-]+/.test(tag);
        const coloured = /\btext-(?:text|muted|accent|danger)\b/.test(tag);
        if (styled && !coloured) {
          offenders.push(`${path.replace(SRC, '').replaceAll('\\', '/')}: ${tag.slice(0, 60)}…`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
