import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Локальность тяжёлых зависимостей просмотрщика.
 *
 * `pdfjs-dist` весит больше всего остального приложения вместе взятого. Один статический
 * импорт в общем модуле утащит его на список проектов, где PDF никто не открывает, —
 * и заметить это можно только по времени загрузки, то есть поздно.
 *
 * Проверка читает исходники, а не собранный бандл: собранный показал бы последствие, а
 * не причину, и сообщение об ошибке звучало бы как «бандл вырос на 800 КБ».
 */

const SRC = join(process.cwd(), 'src');

const sourceFiles = (directory: string): string[] => {
  const entries = readdirSync(directory, { withFileTypes: true });
  const found: string[] = [];

  for (const entry of entries) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) {
      found.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith('.test.ts')) {
      found.push(full);
    }
  }

  return found;
};

const read = (path: string): string => readFileSync(path, 'utf8');

/** Спецификаторы статических импортов файла. Динамические сюда намеренно не попадают. */
const staticImports = (source: string): string[] => {
  const found: string[] = [];
  const pattern = /(?:^|\n)\s*import\s+(?:type\s+)?[^;'"]*from\s+['"]([^'"]+)['"]/g;

  let match = pattern.exec(source);
  while (match !== null) {
    if (match[1]) found.push(match[1]);
    match = pattern.exec(source);
  }

  return found;
};

const MEASUREMENT_LAYER = [
  'lib/viewer/measurement.ts',
  'lib/viewer/measurement-overlay.ts',
  'lib/viewer/tool-machine.ts',
  'lib/viewer/tool-controller.ts',
];

describe('локальность тяжёлых зависимостей', () => {
  it('pdfjs-dist статически импортируется ровно в одном модуле', () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => staticImports(read(path)).some((item) => item.startsWith('pdfjs-dist')))
      .map((path) => path.replace(SRC, '').replaceAll('\\', '/'));

    expect(offenders).toEqual(['/lib/viewer/pdfjs-backend.ts']);
  });

  it('сам модуль pdf.js подключается только динамическим импортом', () => {
    // Статическая ссылка на него из любого модуля, попавшего в общий чанк, свела бы
    // предыдущую проверку на нет: тяжесть переехала бы вместе с оболочкой.
    const offenders = sourceFiles(SRC)
      .filter((path) => !path.endsWith('pdfjs-backend.ts'))
      .filter((path) => staticImports(read(path)).some((item) => item.includes('pdfjs-backend')))
      .map((path) => path.replace(SRC, '').replaceAll('\\', '/'));

    expect(offenders).toEqual([]);
  });

  it('слой измерений не тянет ни одной внешней библиотеки', () => {
    // Он грузится вместе с рабочей областью, но обязан оставаться дешёвым сам по себе:
    // это чистая геометрия, и любая внешняя зависимость здесь — повод спросить зачем.
    for (const relative of MEASUREMENT_LAYER) {
      const external = staticImports(read(join(SRC, relative))).filter(
        (item) => !item.startsWith('@/') && !item.startsWith('.'),
      );

      expect({ module: relative, external }).toEqual({ module: relative, external: [] });
    }
  });

  it('слой измерений не знает про pdf.js', () => {
    // Геометрия измерения выражена в долях листа и не зависит от того, чем лист нарисован.
    for (const relative of MEASUREMENT_LAYER) {
      expect(read(join(SRC, relative))).not.toContain('pdfjs');
    }
  });
});
