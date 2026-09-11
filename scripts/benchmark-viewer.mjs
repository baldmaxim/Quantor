#!/usr/bin/env node
/**
 * Замер просмотрщика Stage 2B (промт 02): одна команда, один JSON, один отчёт.
 *
 * ```bash
 * pnpm benchmark:viewer
 * ```
 *
 * Листов два. Синтетический A1 есть всегда и делает замер воспроизводимым на любой машине.
 * Эталонный лист Stage 2A — частный пакет вне git; если он лежит там же, где его ищет живой
 * тест геометрии, меряется и он. Путь можно задать явно: VIEWER_BENCH_PDF (PDF) или
 * VIEWER_BENCH_PACKAGE (ZIP-пакет), номер листа — VIEWER_BENCH_PAGE (с единицы, умолчание 71).
 *
 * Для итераций — часть разделов: VIEWER_BENCH_ONLY=pan,consistency (из sizing, consistency,
 * pan), сценарии панорамы по номерам VIEWER_BENCH_PAN=0,3 и их длительность
 * VIEWER_BENCH_PAN_SECONDS. Такой прогон печатает отчёт в stdout и файлы в docs не трогает;
 * JSON — по пути из VIEWER_BENCH_JSON, если он задан.
 *
 * В отчёт попадают размеры, отпечаток и номер листа, но не имя клиентского файла.
 */

import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const OUT_DIR = join(ROOT, 'docs', 'stage2b');
const JSON_PATH = join(OUT_DIR, 'viewer-benchmark-results.json');
const REPORT_PATH = join(OUT_DIR, 'viewer-benchmark-report.md');
const WORK = join(tmpdir(), `quantor-viewer-bench-${process.pid}`);

const REFERENCE_CANDIDATES = [
  '_prompts/stage2a_measurement_core/fixtures/live',
  '_prompts/stage1/fixtures/legacy',
];

const sha256 = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');

/** Самый крупный PDF из ZIP-пакета. Имя члена архива в путь записи не попадает. */
const extractPdf = (archive, target) => {
  const code = [
    'import shutil, sys, zipfile',
    'with zipfile.ZipFile(sys.argv[1]) as z:',
    '    names = [n for n in z.namelist() if n.lower().endswith(".pdf")]',
    '    if not names: sys.exit(3)',
    '    names.sort(key=lambda n: z.getinfo(n).file_size, reverse=True)',
    '    with z.open(names[0]) as src, open(sys.argv[2], "wb") as dst:',
    '        shutil.copyfileobj(src, dst)',
  ].join('\n');
  const result = spawnSync(
    process.execPath,
    ['../../scripts/py.mjs', '-c', code, archive, target],
    {
      cwd: join(ROOT, 'apps', 'api'),
      stdio: ['ignore', 'inherit', 'inherit'],
    },
  );
  return result.status === 0 && existsSync(target);
};

const findReference = () => {
  const page = Number(process.env.VIEWER_BENCH_PAGE ?? 71);
  if (process.env.VIEWER_BENCH_PDF) return { path: process.env.VIEWER_BENCH_PDF, page };

  const archives = process.env.VIEWER_BENCH_PACKAGE
    ? [process.env.VIEWER_BENCH_PACKAGE]
    : REFERENCE_CANDIDATES.map((dir) => join(ROOT, dir))
        .filter((dir) => existsSync(dir))
        .flatMap((dir) =>
          readdirSync(dir)
            .filter((name) => /\.(zip|pdf)$/i.test(name))
            .map((name) => join(dir, name)),
        );

  for (const archive of archives) {
    if (/\.pdf$/i.test(archive)) return { path: archive, page };
    const target = join(WORK, 'reference.pdf');
    if (extractPdf(archive, target)) return { path: target, page };
  }
  return null;
};

// --- отчёт ---

const f = (value, digits = 1) => (typeof value === 'number' ? value.toFixed(digits) : '—');
const pct = (zoom) => `${Math.round(zoom * 100)} %`;

const table = (header, rows) =>
  [
    `| ${header.join(' | ')} |`,
    `| ${header.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${row.join(' | ')} |`),
  ].join('\n');

const buildReport = (report) => {
  const sourceName = (id) => report.sources.find((item) => item.id === id)?.label ?? id;
  const lines = [
    '# Замер просмотрщика Stage 2B',
    '',
    '<!-- Файл создаётся командой `pnpm benchmark:viewer`. Руками не правится: числа в нём и в',
    '     viewer-benchmark-results.json обязаны совпадать. -->',
    '',
    `Снято: ${report.generatedAt}. Коммит: \`${report.commit ?? '—'}\`${report.dirty ? ' и незафиксированные изменения рабочего дерева поверх него' : ''}.`,
    '',
    '## Среда',
    '',
    table(
      ['Что', 'Значение'],
      [
        ['Браузер', report.environment.browser],
        [
          'Процессор',
          `${report.environment.cpu ?? '—'}, ${report.environment.logicalCpus} потоков`,
        ],
        ['Память', `${f(report.environment.totalMemoryGiB)} ГиБ`],
        ['Система', report.environment.platform],
        ['Node', report.environment.node],
      ],
    ),
    '',
    'Chromium без GPU рисует программно: числа времени — верхняя оценка, на машине с аппаратным',
    'ускорением кадр дешевле. Размеры холстов и память от ускорения не зависят.',
    '',
    '## Листы',
    '',
    table(
      ['Лист', 'Страница', 'Размер, pt', 'Поворот', 'Отпечаток PDF'],
      report.sources.map((source) => {
        const sizing = report.sizing.find((item) => item.source === source.id && item.geometry);
        const geometry = sizing?.geometry;
        return [
          source.label,
          String(source.pageIndex + 1),
          geometry ? `${f(geometry.width, 0)} × ${f(geometry.height, 0)}` : '—',
          geometry ? String(geometry.rotation) : '—',
          `\`${source.sha256.slice(0, 16)}…\``,
        ];
      }),
    ),
    '',
    '## Холсты и память',
    '',
    'Модель прежней архитектуры — точка отсчёта для ADR-0024. Холст страницы — формула',
    'pdf.js-отрисовщика; слой — рабочий `resizeOverlay`. Стопка — страница и три слоя во весь лист,',
    'как держал их DrawingViewport до промта 03. Слой по области просмотра — 1600 × 1000',
    'CSS-пикселей. Что держит рабочий компонент сейчас, видно в разделе панорамы.',
    '',
  ];

  for (const sizing of report.sizing) {
    lines.push(`### ${sourceName(sizing.source)}, DPR ${sizing.ratio}`, '');
    if (sizing.error) lines.push(`**Раздел не выполнен:** ${sizing.error}`, '');
    const allocation = report.allocation.find(
      (item) => item.source === sizing.source && item.ratio === sizing.ratio,
    );
    lines.push(
      table(
        [
          'Масштаб',
          'Холст страницы',
          'Мп',
          'RGBA, МиБ',
          'Стопка ×4, МиБ',
          'Слой по области, МиБ',
          'Выделение холста',
          'Выделение стопки',
        ],
        sizing.rows.map((row, index) => {
          const attempt = allocation?.rows[index];
          const mark = (item) =>
            item ? (item.ok ? `да, ${f(item.ms, 0)} мс` : `**нет**: ${item.error}`) : '—';
          return [
            pct(row.zoom),
            `${row.page.width} × ${row.page.height}`,
            f(row.page.megapixels),
            f(row.page.rgbaMiB, 0),
            f(row.stackRgbaMiB, 0),
            f(row.viewportOverlay.rgbaMiB, 1),
            mark(attempt?.single),
            mark(attempt?.stack),
          ];
        }),
      ),
      '',
    );
  }

  lines.push('## Отрисовка страницы pdf.js', '');
  for (const render of report.pdfRender) {
    lines.push(
      `### ${sourceName(render.source)}, DPR ${render.ratio}`,
      '',
      `Каждый масштаб — в свежей вкладке с прогревом при 25 % (первый прогрев: ${f(render.warmupMs, 0)} мс).`,
      '',
    );
    lines.push(
      table(
        ['Масштаб', 'Холст', 'Мп', 'Время, мс', 'Ошибка'],
        render.rows.map((row) => [
          pct(row.zoom),
          row.canvas ? `${row.canvas.width} × ${row.canvas.height}` : '—',
          row.canvas ? f(row.canvas.megapixels) : '—',
          f(row.ms, 0),
          row.error ?? '—',
        ]),
      ),
      '',
    );
  }

  if (report.overlay) {
    lines.push(
      '## Слой измерений: холст во весь лист против холста по области',
      '',
      `DPR ${report.overlay.ratio}, масштаб ${pct(report.overlay.zoom)}. Рисуются все фигуры, без отсечения: разница — цена размера холста.`,
      '',
      ...(report.overlay.error ? [`**Раздел оборван:** ${report.overlay.error}`, ''] : []),
      table(
        ['Фигур', 'Холст', 'Мп', 'Кадр, медиана мс', 'Кадр, p95 мс', 'Кадров'],
        report.overlay.rows.map((row) => [
          String(row.primitives),
          row.mode === 'viewport'
            ? `по области ${row.canvas.width} × ${row.canvas.height}`
            : `во весь лист ${row.canvas.width} × ${row.canvas.height}`,
          f(row.canvas.megapixels),
          f(row.draw.median),
          f(row.draw.p95),
          String(row.draw.count),
        ]),
      ),
      '',
    );
  }

  if (report.hitTest) {
    lines.push(
      '## Попадание (линейный перебор)',
      '',
      ...(report.hitTest.error ? [`**Раздел оборван:** ${report.hitTest.error}`, ''] : []),
      table(
        ['Фигур', 'Медиана, мс', 'p95, мс', 'Максимум, мс'],
        report.hitTest.rows.map((row) => [
          String(row.primitives),
          f(row.hit.median, 2),
          f(row.hit.p95, 2),
          f(row.hit.max, 2),
        ]),
      ),
      '',
    );
  }

  if (report.consistency?.length) {
    lines.push(
      '## Резкая часть против листа целиком',
      '',
      'Резкая часть (ADR-0025) рисуется pdf.js со сдвигом и сверяется попиксельно с тем же куском растра',
      'во весь лист. «Всего» — пиксели, где хоть один канал разошёлся больше чем на 2 из 255,',
      '«заметно» — больше чем на 64. Проба «сдвиг на пиксель» — то же сравнение с куском листа на пиксель',
      'левее: так выглядел бы шов. Skia растеризует тонкий штрих в разных местах холста не бит в бит,',
      'поэтому мерило выравнивания — разница между двумя столбцами, а не ноль.',
      '',
      table(
        [
          'Лист',
          'DPR',
          'Масштаб',
          'Растр листа',
          'Резкая часть',
          'Угол, px',
          'Совпадение: заметно / всего',
          'Сдвиг на пиксель: заметно / всего',
          'Лист, мс',
          'Часть, мс',
        ],
        report.consistency.map((item) => {
          const r = item.result;
          if (!r) {
            return [
              sourceName(item.source),
              String(item.ratio),
              pct(item.zoom),
              `**не выполнено:** ${item.error}`,
              '—',
              '—',
              '—',
              '—',
              '—',
              '—',
            ];
          }
          return [
            sourceName(item.source),
            String(item.ratio),
            pct(item.zoom),
            `${r.page.width} × ${r.page.height}`,
            `${r.region.width} × ${r.region.height}`,
            `${r.offset.x}, ${r.offset.y}`,
            `${r.aligned.visible} / ${r.aligned.differing}`,
            `${r.offByOnePixel.visible} / ${r.offByOnePixel.differing}`,
            f(r.pageMs, 0),
            f(r.regionMs, 0),
          ];
        }),
      ),
      '',
    );
  }

  lines.push(
    '## Панорама настоящего DrawingViewport',
    '',
    'Камера двигается каждый кадр по фигуре Лиссажу в пределах листа. Длинная задача — дольше 50 мс',
    'на главном потоке. Память процессов — рабочее множество и частные байты всего дерева',
    'процессов Chromium по данным ОС. Слои после панорамы сверяются побитно с перерисовкой целиком',
    'при той же камере.',
    '',
  );
  for (const pan of report.pan) {
    const r = pan.result;
    lines.push(
      `### ${sourceName(pan.source)}: ${pct(pan.zoom)}, DPR ${pan.ratio}, ${pan.measurements} измерений, ${pan.regions} областей, ${pan.durationMs / 1000} с`,
      '',
    );
    if (r.error) {
      lines.push(`**Не выполнено:** ${r.error}`, '');
      continue;
    }
    const phase = (ms) => (typeof ms === 'number' ? pan.evaluateStartedSeconds + ms / 1000 : null);
    const inRange = (from, to) =>
      pan.memory.filter(
        (m) => from !== null && m.seconds >= from && (to === null || m.seconds <= to),
      );
    const panMemory = inRange(phase(r.phases.panStarted), phase(r.phases.panEnded));
    const beforePan = inRange(0, phase(r.phases.panStarted));
    const memoryRow = (samples) =>
      samples.length
        ? `${f(samples[0].workingSetMiB, 0)} → ${f(samples[samples.length - 1].workingSetMiB, 0)} (макс. ${f(Math.max(...samples.map((m) => m.workingSetMiB)), 0)})`
        : '—';
    const panEnd = r.phases.panEnded;
    const afterPan = (r.renders ?? []).filter(
      (item) => typeof panEnd === 'number' && item.startedAt >= panEnd,
    );
    const renderKind = (item) =>
      `${item.kind === 'region' ? 'часть' : 'лист'} ${item.canvas.width} × ${item.canvas.height} при ${pct(item.scale)}, ${f(item.ms, 0)} мс${item.completed ? '' : ' (оборвана)'}`;
    lines.push(
      table(
        ['Что', 'Значение'],
        [
          [
            'Холсты',
            r.canvases
              .map(
                (c) =>
                  `${c.role ? `${c.role}: ` : ''}${c.width} × ${c.height}${c.visible ? '' : ' (скрыт)'}`,
              )
              .join('; '),
          ],
          ['Память холстов, RGBA', `${f(r.stackRgbaMiB, 0)} МиБ`],
          ['Отрисовка в этом масштабе', `${f(r.zoomRenderMs, 0)} мс`],
          [
            'Интервал кадра: медиана / p95 / максимум',
            `${f(r.frameIntervals.median)} / ${f(r.frameIntervals.p95)} / ${f(r.frameIntervals.max)} мс`,
          ],
          ['Кадров в секунду (среднее)', f(r.framesPerSecond)],
          [
            'Длинные задачи во время панорамы',
            `${r.longTasks.count}, всего ${f(r.longTasks.totalMs, 0)} мс, самая длинная ${f(r.longTasks.maxMs, 0)} мс`,
          ],
          ['Перерисовок страницы за панораму', String(r.rendersDuringPan)],
          [
            'Перерисовок и длинных задач после остановки',
            `${r.rendersAfterPan}; ${r.longTasksAfterPan.count} задач, ${f(r.longTasksAfterPan.totalMs, 0)} мс`,
          ],
          [
            'Отрисовки после остановки',
            afterPan.length ? afterPan.map(renderKind).join('; ') : '—',
          ],
          ...(r.layerConsistency ?? []).map((c) => [
            `Слой ${c.layer} после панорамы против перерисовки целиком`,
            `закрашено ${c.inked} из ${c.pixels}; после панорамы — заметно ${c.afterPan.visible}, всего ${c.afterPan.differing}; порог шума (один сдвиг) — заметно ${c.singleShift.visible}, всего ${c.singleShift.differing}; сдвиг на пиксель — заметно ${c.offByOnePixel.visible}, всего ${c.offByOnePixel.differing}`,
          ]),
          [
            'Куча JS, МиБ (раз в секунду)',
            r.heapUsedMiB.length
              ? `${f(r.heapUsedMiB[0])} → ${f(r.heapUsedMiB[r.heapUsedMiB.length - 1])}`
              : 'недоступна',
          ],
          ['Рабочее множество процессов до панорамы, МиБ', memoryRow(beforePan)],
          ['Рабочее множество процессов во время панорамы, МиБ', memoryRow(panMemory)],
        ],
      ),
      '',
    );
  }

  return `${lines.join('\n').replace(/\n{3,}/g, '\n\n')}\n`;
};

// --- запуск ---

mkdirSync(WORK, { recursive: true });
try {
  const { buildSyntheticDrawing } = await import(
    pathToFileURL(join(ROOT, 'apps', 'web', 'benchmarks', 'synthetic-drawing.mjs')).href
  );
  const syntheticPath = join(WORK, 'synthetic-a1.pdf');
  writeFileSync(syntheticPath, buildSyntheticDrawing());

  const sources = [];
  const reference = findReference();
  if (reference) {
    sources.push({
      id: 'reference',
      label: 'Эталонный лист Stage 2A (частный пакет, вне git)',
      path: reference.path,
      pageIndex: reference.page - 1,
    });
  }
  sources.push({ id: 'synthetic', label: 'Синтетический A1', path: syntheticPath, pageIndex: 0 });
  const primary = sources[0].id;
  // Быстрый прогон проверяет, что стенд вообще работает. Числа из него в отчёт не пишутся.
  const quick = Boolean(process.env.VIEWER_BENCH_QUICK);

  const fullConfig = {
    sources: sources.map((source) => ({ ...source, sha256: sha256(source.path) })),
    viewport: { width: 1600, height: 1000 },
    zooms: [1, 2.66, 4],
    ratios: [1, 1.5, 2],
    settleMs: 2000,
    overlay: {
      ratio: 1.5,
      zoom: 2.66,
      sizes: [1000, 5000, 10000, 25000],
      frames: { viewport: 30, fullPage: 8 },
      hitFrames: 60,
    },
    // Резкая часть против листа целиком: обычная плотность и сценарий живой приёмки.
    consistency: [
      { ratio: 1, zoom: 2 },
      { ratio: 1.5, zoom: 2.66 },
    ],
    // Сценарий живой приёмки (266 %, DPR 1,5) и соседние: другая плотность и вписанный лист.
    pan: [
      {
        source: primary,
        ratio: 1.5,
        zoom: 2.66,
        measurements: 5000,
        regions: 400,
        durationMs: 30_000,
      },
      {
        source: primary,
        ratio: 1,
        zoom: 2.66,
        measurements: 5000,
        regions: 400,
        durationMs: 30_000,
      },
      {
        source: primary,
        ratio: 1.5,
        zoom: 1,
        measurements: 5000,
        regions: 400,
        durationMs: 10_000,
      },
      { source: primary, ratio: 1.5, zoom: 2.66, measurements: 0, regions: 0, durationMs: 15_000 },
    ],
  };
  // Часть разделов (VIEWER_BENCH_ONLY=pan,consistency) — для итераций: отчёт в stdout, файлы
  // в docs не трогаются, потому что неполный замер не может заменить полный.
  const only = process.env.VIEWER_BENCH_ONLY
    ? process.env.VIEWER_BENCH_ONLY.split(',').map((item) => item.trim())
    : null;
  // Сценарии панорамы по номерам (с нуля) и длительность — тоже только для итераций.
  const panIndices = process.env.VIEWER_BENCH_PAN?.split(',').map(Number) ?? null;
  const panSeconds = Number(process.env.VIEWER_BENCH_PAN_SECONDS ?? 0);
  const selected = only
    ? {
        ...fullConfig,
        sections: only,
        pan: fullConfig.pan
          .filter((_, index) => !panIndices || panIndices.includes(index))
          .map((scenario) =>
            panSeconds > 0 ? { ...scenario, durationMs: panSeconds * 1000 } : scenario,
          ),
      }
    : fullConfig;
  const config = quick
    ? {
        ...selected,
        zooms: [1, 2.66],
        ratios: [1.5],
        overlay: {
          ...fullConfig.overlay,
          sizes: [1000],
          frames: { viewport: 3, fullPage: 2 },
          hitFrames: 5,
        },
        consistency: [{ ratio: 1, zoom: 2 }],
        pan: [{ ...fullConfig.pan[0], durationMs: 3000 }],
        settleMs: 500,
      }
    : selected;
  const configPath = join(WORK, 'config.json');
  writeFileSync(configPath, JSON.stringify(config));

  const run = spawnSync(process.execPath, ['benchmarks/viewer-run.mjs', '--config', configPath], {
    cwd: join(ROOT, 'apps', 'web'),
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  if (run.status !== 0) {
    process.stderr.write(`Замер не выполнен: код ${run.status}\n`);
    process.exit(run.status ?? 1);
  }

  const measured = JSON.parse(run.stdout.trim().split('\n').pop());
  const commit = spawnSync('git', ['rev-parse', 'HEAD'], {
    cwd: ROOT,
    encoding: 'utf8',
  }).stdout.trim();
  // Замер обычно снимается до коммита, в который войдёт: отчёт честно говорит, что код новее хеша.
  const dirty =
    spawnSync('git', ['status', '--porcelain', '--', 'apps/web', 'scripts'], {
      cwd: ROOT,
      encoding: 'utf8',
    }).stdout.trim().length > 0;
  const report = {
    ...measured,
    commit: commit || null,
    dirty,
    // Пути к файлам в отчёт не попадают: у эталона это путь к частным данным.
    sources: config.sources.map(({ path: _path, ...rest }) => rest),
    config: { ...measured.config, sources: undefined },
  };

  if (quick || only) {
    if (process.env.VIEWER_BENCH_JSON) {
      writeFileSync(process.env.VIEWER_BENCH_JSON, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    }
    process.stdout.write(buildReport(report));
  } else {
    mkdirSync(OUT_DIR, { recursive: true });
    writeFileSync(JSON_PATH, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    writeFileSync(REPORT_PATH, buildReport(report), 'utf8');
    process.stdout.write(`Результаты: ${JSON_PATH}\nОтчёт: ${REPORT_PATH}\n`);
  }
} finally {
  rmSync(WORK, { recursive: true, force: true });
}
