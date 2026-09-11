/**
 * Оболочка замера просмотрщика: поднимает Vite, открывает стенд в настоящем Chromium и
 * вызывает разделы по одному. Результат — JSON в stdout; отчёт собирает
 * `scripts/benchmark-viewer.mjs`.
 *
 * Память холстов в куче JS не видна, поэтому рядом с `performance.memory` снимается память
 * процессов браузера средствами ОС — рабочее множество и частные байты всего дерева процессов.
 * Если ОС их не отдаёт, раздел честно остаётся пустым.
 */

import { execFile } from 'node:child_process';
import { readFileSync } from 'node:fs';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));

const configIndex = process.argv.indexOf('--config');
if (configIndex < 0) throw new Error('нужен аргумент --config с JSON конфигурации');
const config = JSON.parse(readFileSync(process.argv[configIndex + 1], 'utf8'));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Раздаёт PDF замера тем же сервером, что и стенд: запросы pdf.js не уходят в сторону. */
const pdfPlugin = (sources) => ({
  name: 'viewer-bench-pdf',
  configureServer(server) {
    const files = new Map(sources.map((source) => [source.id, readFileSync(source.path)]));
    server.middlewares.use((request, response, next) => {
      const match = /^\/bench-pdf\/([\w-]+)\.pdf$/.exec(request.url ?? '');
      const body = match ? files.get(match[1]) : undefined;
      if (!body) return next();
      response.setHeader('Content-Type', 'application/pdf');
      response.setHeader('Content-Length', String(body.length));
      response.end(body);
    });
  },
});

const readProcesses = () =>
  new Promise((resolve) => {
    if (process.platform === 'win32') {
      execFile(
        'powershell',
        [
          '-NoProfile',
          '-Command',
          'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,WorkingSetSize,PrivatePageCount | ConvertTo-Json -Compress',
        ],
        { maxBuffer: 32 * 1024 * 1024, windowsHide: true },
        (error, stdout) => {
          if (error) return resolve(null);
          try {
            resolve(
              JSON.parse(stdout).map((row) => ({
                pid: row.ProcessId,
                ppid: row.ParentProcessId,
                workingSet: Number(row.WorkingSetSize ?? 0),
                privateBytes: Number(row.PrivatePageCount ?? 0),
              })),
            );
          } catch {
            resolve(null);
          }
        },
      );
      return;
    }
    execFile('ps', ['-A', '-o', 'pid=,ppid=,rss='], (error, stdout) => {
      if (error) return resolve(null);
      resolve(
        stdout
          .trim()
          .split('\n')
          .map((line) => line.trim().split(/\s+/).map(Number))
          .map(([pid, ppid, rss]) => ({ pid, ppid, workingSet: rss * 1024, privateBytes: null })),
      );
    });
  });

/** Память дерева процессов браузера: корень и все потомки, включая рендереры и GPU. */
const sampleTree = async (rootPid) => {
  const rows = await readProcesses();
  if (!rows) return null;
  const children = new Map();
  for (const row of rows) {
    if (!children.has(row.ppid)) children.set(row.ppid, []);
    children.get(row.ppid).push(row);
  }
  const root = rows.find((row) => row.pid === rootPid);
  if (!root) return null;

  let workingSet = 0;
  let privateBytes = 0;
  let count = 0;
  const queue = [root];
  while (queue.length) {
    const current = queue.shift();
    workingSet += current.workingSet;
    privateBytes += current.privateBytes ?? 0;
    count += 1;
    queue.push(...(children.get(current.pid) ?? []));
  }
  return {
    workingSetMiB: workingSet / (1024 * 1024),
    privateMiB: privateBytes / (1024 * 1024),
    processes: count,
  };
};

const main = async () => {
  const { createServer } = await import('vite');
  const { default: react } = await import('@vitejs/plugin-react');
  const { chromium } = await import('@playwright/test');

  const server = await createServer({
    root: WEB_ROOT,
    configFile: false,
    logLevel: 'error',
    plugins: [react(), pdfPlugin(config.sources)],
    resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
    server: { port: 0, strictPort: false },
    appType: 'mpa',
  });

  // Сервер браузера, а не обычный запуск: только у него есть идентификатор процесса,
  // по которому снимается память дерева процессов.
  const browserServer = await chromium.launchServer({ args: ['--enable-precise-memory-info'] });
  const browser = await chromium.connect(browserServer.wsEndpoint());
  const browserPid = browserServer.process().pid;

  // Разделы можно выбрать для прогона по частям; по умолчанию — все.
  const sections = new Set(config.sections ?? ['sizing', 'consistency', 'pan']);

  const report = {
    schema: 'quantor.benchmark.viewer.v1',
    generatedAt: new Date().toISOString(),
    environment: {
      node: process.version,
      platform: `${process.platform} ${process.release.name} ${os.release()}`,
      cpu: os.cpus()[0]?.model ?? null,
      logicalCpus: os.cpus().length,
      totalMemoryGiB: os.totalmem() / 1024 ** 3,
      browser: `Chromium ${browser.version()} (headless)`,
    },
    config,
    sizing: [],
    allocation: [],
    pdfRender: [],
    overlay: null,
    hitTest: null,
    consistency: [],
    pan: [],
  };

  try {
    await server.listen();
    const base = server.resolvedUrls?.local?.[0];
    if (!base) throw new Error('Vite не сообщил адрес dev-сервера');
    const origin = base.replace(/\/$/, '');
    const pdfUrl = (source) => `${origin}/bench-pdf/${source.id}.pdf`;

    const open = async (ratio) => {
      const context = await browser.newContext({
        viewport: { width: 1700, height: 1100 },
        deviceScaleFactor: ratio,
      });
      const page = await context.newPage();
      page.setDefaultTimeout(1_800_000);
      await page.goto(`${origin}/benchmarks/viewer-bench.html`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.__benchReady === true);
      return { context, page };
    };

    /**
     * Раздел в свежем контексте. Гигантский холст может уронить вкладку — тогда раздел
     * записывается с ошибкой, а замер идёт дальше: падение на 400 % — тоже результат.
     */
    const section = async (ratio, run) => {
      const { context, page } = await open(ratio);
      try {
        return { value: await run(page), error: null };
      } catch (error) {
        return {
          value: null,
          error: error instanceof Error ? error.message.split('\n')[0] : String(error),
        };
      } finally {
        await context.close().catch(() => undefined);
      }
    };

    // Холсты, выделение, отрисовка pdf.js и слой — одна группа: слою нужна геометрия листа.
    for (const ratio of sections.has('sizing') ? config.ratios : []) {
      for (const source of config.sources) {
        const sizing = await section(ratio, (page) =>
          page.evaluate(
            ([url, pageIndex, zooms, viewport]) =>
              window.__viewerBench.measureSizing(url, pageIndex, zooms, viewport),
            [pdfUrl(source), source.pageIndex, config.zooms, config.viewport],
          ),
        );
        report.sizing.push({
          source: source.id,
          ratio,
          ...(sizing.value ?? { rows: [] }),
          error: sizing.error,
        });

        // Выделение по одному масштабу за раз: падение на крупном не отменяет мелкие.
        const allocationRows = [];
        for (const row of sizing.value?.rows ?? []) {
          const attempt = await section(ratio, (page) =>
            page.evaluate((rows) => window.__viewerBench.measureAllocation(rows), [row]),
          );
          allocationRows.push(
            attempt.value?.[0] ?? {
              zoom: row.zoom,
              single: { ok: false, ms: 0, error: attempt.error },
              stack: { ok: false, ms: 0, error: attempt.error },
            },
          );
        }
        report.allocation.push({ source: source.id, ratio, rows: allocationRows });

        const renderRows = [];
        let pageCount = null;
        let warmupMs = null;
        for (const zoom of config.zooms) {
          const attempt = await section(ratio, (page) =>
            page.evaluate(
              ([url, pageIndex, zooms]) =>
                window.__viewerBench.measurePdfRender(url, pageIndex, zooms),
              [pdfUrl(source), source.pageIndex, [zoom]],
            ),
          );
          pageCount = attempt.value?.pageCount ?? pageCount;
          warmupMs = warmupMs ?? attempt.value?.warmupMs ?? null;
          renderRows.push(
            attempt.value?.rows[0] ?? {
              zoom,
              devicePixelRatio: ratio,
              canvas: null,
              ms: null,
              error: attempt.error,
            },
          );
        }
        report.pdfRender.push({ source: source.id, ratio, pageCount, warmupMs, rows: renderRows });
      }

      if (ratio === config.overlay.ratio) {
        const primary = report.sizing.find(
          (item) => item.source === config.sources[0].id && item.ratio === ratio && item.geometry,
        );
        if (primary) {
          const geometry = { width: primary.geometry.width, height: primary.geometry.height };
          const overlay = await section(ratio, (page) =>
            page.evaluate(
              ([sheet, sizes, zoom, viewport, frames]) =>
                window.__viewerBench.measureOverlay(sheet, sizes, zoom, viewport, frames),
              [
                geometry,
                config.overlay.sizes,
                config.overlay.zoom,
                config.viewport,
                config.overlay.frames,
              ],
            ),
          );
          report.overlay = {
            ratio,
            zoom: config.overlay.zoom,
            rows: overlay.value ?? [],
            error: overlay.error,
          };
          const hit = await section(ratio, (page) =>
            page.evaluate(
              ([sheet, sizes, zoom, frames]) =>
                window.__viewerBench.measureHitTest(sheet, sizes, zoom, frames),
              [geometry, config.overlay.sizes, config.overlay.zoom, config.overlay.hitFrames],
            ),
          );
          report.hitTest = {
            ratio,
            zoom: config.overlay.zoom,
            rows: hit.value ?? [],
            error: hit.error,
          };
        }
      }
    }

    // Резкая часть против того же куска листа целиком — побитно, на каждом листе.
    for (const check of sections.has('consistency') ? config.consistency : []) {
      for (const source of config.sources) {
        const attempt = await section(check.ratio, (page) =>
          page.evaluate(
            ([url, pageIndex, zoom, viewport]) =>
              window.__viewerBench.measureRasterConsistency(url, pageIndex, zoom, viewport),
            [pdfUrl(source), source.pageIndex, check.zoom, config.viewport],
          ),
        );
        report.consistency.push({
          source: source.id,
          ratio: check.ratio,
          zoom: check.zoom,
          result: attempt.value,
          error: attempt.error,
        });
      }
    }

    for (const scenario of sections.has('pan') ? config.pan : []) {
      const source = config.sources.find((item) => item.id === scenario.source);
      const { context, page } = await open(scenario.ratio);
      const memory = [];
      let sampling = true;
      const started = Date.now();
      const sampler = (async () => {
        while (sampling) {
          const sample = await sampleTree(browserPid);
          if (sample) memory.push({ seconds: (Date.now() - started) / 1000, ...sample });
          await sleep(1500);
        }
      })();

      const evaluateStartedSeconds = (Date.now() - started) / 1000;
      try {
        const result = await page.evaluate((options) => window.__viewerBench.measurePan(options), {
          url: pdfUrl(source),
          pageIndex: source.pageIndex,
          zoom: scenario.zoom,
          measurements: scenario.measurements,
          regions: scenario.regions,
          durationMs: scenario.durationMs,
          settleMs: config.settleMs,
        });
        report.pan.push({ ...scenario, evaluateStartedSeconds, result, memory });
      } catch (error) {
        const message = error instanceof Error ? error.message.split('\n')[0] : String(error);
        report.pan.push({
          ...scenario,
          evaluateStartedSeconds,
          result: { error: message },
          memory,
        });
      } finally {
        sampling = false;
        await sampler;
        await context.close();
      }
    }
  } finally {
    await browser.close();
    await browserServer.close();
    await server.close();
  }

  process.stdout.write(`${JSON.stringify(report)}\n`);
};

await main();
