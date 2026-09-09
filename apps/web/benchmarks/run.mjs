/**
 * Оболочка замера слоя измерений: поднимает dev-сервер Vite, открывает страницу в
 * настоящем Chromium и снимает числа.
 *
 * Браузер настоящий намеренно. jsdom не растеризует ничего, и полученное на нём число
 * описывало бы скорость обхода массивов, а не скорость слоя.
 *
 * Если браузер не установлен, раздел честно помечается пропущенным: выдумывать сюда
 * значения нельзя — на этих числах стоит решение «Canvas2D или WebGL» (ADR-0015).
 */

import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const SIZES = [1000, 5000, 10000];
const FRAMES = 60;

/** Модули слоя измерений: их вес и есть добавка к бандлу рабочей области. */
const LAYER_MODULES = [
  'src/lib/viewer/measurement-overlay.ts',
  'src/lib/viewer/tool-machine.ts',
  'src/lib/viewer/tool-controller.ts',
  'src/lib/viewer/measurement.ts',
];

const aliasConfig = () => ({
  '@': fileURLToPath(new URL('../src', import.meta.url)),
});

/** Собирает модуль в одиночку и возвращает вес после минификации и сжатия. */
const measureBundle = async (build, entry) => {
  const output = await build({
    root: WEB_ROOT,
    logLevel: 'error',
    configFile: false,
    resolve: { alias: aliasConfig() },
    build: {
      write: false,
      minify: true,
      target: 'es2022',
      lib: { entry, formats: ['es'], fileName: 'bundle' },
    },
  });

  const chunks = (Array.isArray(output) ? output[0].output : output.output).filter(
    (item) => item.type === 'chunk',
  );
  const code = chunks.map((chunk) => chunk.code).join('');
  const raw = Buffer.byteLength(code, 'utf8');

  return {
    entry,
    minifiedBytes: raw,
    gzippedBytes: gzipSync(Buffer.from(code, 'utf8'), { level: 9 }).length,
    sha256: createHash('sha256').update(code).digest('hex').slice(0, 16),
  };
};

const runInBrowser = async (chromium, url, sizes, frames) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
    page.setDefaultTimeout(600_000);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.__benchReady === true);

    // Прогон запускается отсюда, а не самой страницей: так у него нет крайнего срока
    // загрузки и видно, что именно упало, если упало.
    return await page.evaluate(
      ([requested, count]) => window.__runBench(requested, count),
      [sizes, frames],
    );
  } finally {
    await browser.close();
  }
};

const main = async () => {
  const report = {
    schema: 'quantor.benchmark.overlay.v1',
    generatedAt: new Date().toISOString(),
    environment: {
      node: process.version,
      platform: `${process.platform} ${process.arch}`,
    },
    sections: {},
  };

  const { createServer, build } = await import('vite');

  // Вес слоя измеряется всегда: он не зависит ни от браузера, ни от машины.
  try {
    const bundles = [];
    for (const entry of LAYER_MODULES) {
      bundles.push(await measureBundle(build, entry));
    }
    report.sections.bundle = {
      status: 'ok',
      note: 'Каждый модуль собран отдельно и минифицирован. Общие зависимости попадают в каждую сборку, поэтому сумма — верхняя оценка, а не точный вес слоя.',
      modules: bundles,
    };
  } catch (error) {
    report.sections.bundle = { status: 'skipped', reason: String(error) };
  }

  let chromium;
  try {
    ({ chromium } = await import('@playwright/test'));
  } catch (error) {
    report.sections.overlay = {
      status: 'skipped',
      reason: `Playwright не установлен: ${String(error)}`,
      commands: ['pnpm install', 'pnpm --filter @quantor/web exec playwright install chromium'],
    };
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return;
  }

  const server = await createServer({
    root: WEB_ROOT,
    configFile: false,
    logLevel: 'error',
    resolve: { alias: aliasConfig() },
    server: { port: 0, strictPort: false },
    appType: 'mpa',
  });

  try {
    await server.listen();
    const base = server.resolvedUrls?.local?.[0];
    if (!base) throw new Error('Vite не сообщил адрес dev-сервера');

    const url = `${base.replace(/\/$/, '')}/benchmarks/overlay-bench.html`;
    report.sections.overlay = {
      status: 'ok',
      ...(await runInBrowser(chromium, url, SIZES, FRAMES)),
    };
  } catch (error) {
    report.sections.overlay = {
      status: 'skipped',
      reason: String(error),
      commands: ['pnpm --filter @quantor/web exec playwright install chromium'],
    };
  } finally {
    await server.close();
  }

  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
};

await main();
