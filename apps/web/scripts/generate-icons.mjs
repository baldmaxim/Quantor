#!/usr/bin/env node
/**
 * Генерация растровых иконок из одного SVG-исходника.
 *
 * PNG руками не правим: любой ручной файл рано или поздно разойдётся с остальными,
 * и заметит это пользователь, у которого на телефоне остался старый ярлык.
 *
 * Запуск: pnpm --filter @quantor/web icons:generate
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const PUBLIC_DIR = join(dirname(dirname(fileURLToPath(import.meta.url))), 'public');
const SOURCE = join(PUBLIC_DIR, 'quantor-favicon.svg');

/** Цвет подложки. Тот же, что background_color манифеста. */
const BACKGROUND = '#1a5fa8';

/**
 * Обычные иконки: рисунок занимает весь квадрат.
 * 120/152/167 нужны старым iPad и iPhone — без них iOS масштабирует 180 сама и мылит.
 */
const PLAIN = [
  { file: 'favicon-32.png', size: 32 },
  { file: 'apple-touch-icon-120.png', size: 120 },
  { file: 'apple-touch-icon-152.png', size: 152 },
  { file: 'apple-touch-icon-167.png', size: 167 },
  { file: 'apple-touch-icon.png', size: 180 },
  { file: 'icon-192.png', size: 192 },
  { file: 'icon-512.png', size: 512 },
];

/** Доля поля с каждой стороны у maskable-иконки: Android обрезает углы под свою форму. */
const MASKABLE_PADDING = 0.1;

const render = async (size) =>
  sharp(SOURCE, { density: 384 })
    .resize(size, size, { fit: 'contain', background: BACKGROUND })
    .flatten({ background: BACKGROUND })
    .png({ compressionLevel: 9 })
    .toBuffer();

const renderMaskable = async (size) => {
  const inner = Math.round(size * (1 - MASKABLE_PADDING * 2));
  const offset = Math.round((size - inner) / 2);

  return sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: BACKGROUND,
    },
  })
    .composite([{ input: await render(inner), top: offset, left: offset }])
    .png({ compressionLevel: 9 })
    .toBuffer();
};

const main = async () => {
  await mkdir(PUBLIC_DIR, { recursive: true });

  for (const { file, size } of PLAIN) {
    await writeFile(join(PUBLIC_DIR, file), await render(size));
    process.stdout.write(`${file} — ${size}×${size}\n`);
  }

  await writeFile(join(PUBLIC_DIR, 'icon-512-maskable.png'), await renderMaskable(512));
  process.stdout.write('icon-512-maskable.png — 512×512, поля 10%\n');
};

await main();
