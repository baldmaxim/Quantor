import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Изоляция бандла проверяется по зависимостям, а не по результату сборки.
 *
 * Разделение кода можно нечаянно сломать одним импортом, и заметить это по размеру
 * чанка трудно. Отсутствие зависимости сломать нечаянно нельзя — этот тест упадёт.
 */

// От корня пакета: в jsdom-окружении import.meta.url не файловый адрес.
const manifest = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8')) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
};

const FORBIDDEN = ['pdfjs-dist', 'zustand', '@formkit/auto-animate'];

describe('бандл контура управления', () => {
  it('не тянет просмотрщик и его окружение', () => {
    const all = { ...manifest.dependencies, ...manifest.devDependencies };
    for (const name of FORBIDDEN) {
      expect(all, `${name} не должен попадать в админку`).not.toHaveProperty(name);
    }
  });

  it('переиспользует общий пакет, а не копирует примитивы', () => {
    expect(manifest.dependencies).toHaveProperty('@quantor/ui');
    expect(manifest.dependencies).toHaveProperty('@quantor/api-client');
  });
});
