#!/usr/bin/env node
/**
 * Замер измерительного ядра Stage 2A: одна команда на обе стороны.
 *
 * Арифметику считает Python, слой отрисовки — настоящий браузер. Результаты сводятся в
 * один JSON и один отчёт для чтения глазами. Числа в отчёт попадают только из JSON: две
 * независимые записи одних и тех же величин однажды разойдутся, и заметит это никто.
 *
 * Замер не подменяется прогоном тестов. Тест отвечает «сломано или нет», замер — «сколько
 * это стоит»; вывод pytest показывает время своего прогона, а не время расчёта.
 *
 * ```bash
 * pnpm benchmark:measurement            # с разделом живой базы, если она поднята
 * pnpm benchmark:measurement --skip-api # только то, что не требует стенда
 * ```
 */

import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const OUT_DIR = join(ROOT, 'docs', 'stage2a');
const JSON_PATH = join(OUT_DIR, 'benchmark-results.json');
const REPORT_PATH = join(OUT_DIR, 'benchmark-report.md');

const skipApi = process.argv.includes('--skip-api');

/** Запускает часть замера и возвращает разобранный результат либо причину пропуска. */
const runPython = () => {
  const target = join(tmpdir(), `quantor-bench-${process.pid}.json`);
  const args = ['../../scripts/py.mjs', '-m', 'benchmarks.measurement_bench', '--out', target];
  if (skipApi) args.push('--skip-api');

  const result = spawnSync(process.execPath, args, {
    cwd: join(ROOT, 'apps', 'api'),
    encoding: 'utf8',
    stdio: ['ignore', 'inherit', 'inherit'],
  });

  try {
    const payload = JSON.parse(readFileSync(target, 'utf8'));
    return { payload, code: result.status ?? 1 };
  } catch (error) {
    return { payload: { error: String(error) }, code: result.status ?? 1 };
  } finally {
    rmSync(target, { force: true });
  }
};

const runWeb = () => {
  const result = spawnSync(process.execPath, ['benchmarks/run.mjs'], {
    cwd: join(ROOT, 'apps', 'web'),
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'inherit'],
  });

  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    return { sections: { overlay: { status: 'skipped', reason: String(error) } } };
  }
};

// --- отчёт для чтения глазами ---

const nsToUs = (value) => (value / 1000).toFixed(2);
const fixed = (value, digits) => (typeof value === 'number' ? value.toFixed(digits) : '—');

const mathTable = (section) => {
  const rows = section.cases.map((item) => {
    const timing = item.timing;
    const geometry = timing.geometry_median_ns;
    return `| \`${item.case_id}\` | ${item.vertices} | ${item.actual.value ?? '—'} | ${
      item.actual.unit
    } | ${item.absolute_error ?? '—'} | ${item.passed ? 'да' : '**нет**'} | ${
      item.repeatable ? 'да' : '**нет**'
    } | ${nsToUs(timing.median_ns)} | ${geometry === null ? '—' : nsToUs(geometry)} |`;
  });

  return [
    '| Случай | Вершин | Величина | Ед. | Ошибка | В допуске | Воспроизводим | Медиана, мкс | Из них геометрия, мкс |',
    '| --- | ---: | ---: | --- | ---: | --- | --- | ---: | ---: |',
    ...rows,
  ].join('\n');
};

const overlayTable = (overlay) => {
  const overhead = overlay.overhead?.medianMs ?? 0;
  const rows = overlay.draw.map((item, index) => {
    const hit = overlay.hitTest[index];
    return `| ${item.primitives} | ${item.vertices} | ${fixed(item.medianMs, 1)} | ${fixed(
      item.p95Ms,
      1,
    )} | ${fixed(item.medianMs - overhead, 1)} | ${fixed(hit?.medianMs, 2)} | ${fixed(
      hit?.p95Ms,
      2,
    )} |`;
  });

  return [
    '| Фигур | Вершин | Кадр, медиана мс | Кадр, p95 мс | За вычетом пустого кадра, мс | Попадание, медиана мс | Попадание, p95 мс |',
    '| ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ...rows,
  ].join('\n');
};

const bundleTable = (bundle) =>
  [
    '| Модуль | Минифицировано, байт | Gzip, байт |',
    '| --- | ---: | ---: |',
    ...bundle.modules.map(
      (item) => `| \`${item.entry}\` | ${item.minifiedBytes} | ${item.gzippedBytes} |`,
    ),
  ].join('\n');

const skippedBlock = (title, section) =>
  [
    `## ${title}`,
    '',
    `**Пропущено.** ${section.reason ?? 'причина не указана'}`,
    '',
    ...(section.commands?.length
      ? ['Чтобы получить числа:', '', '```bash', ...section.commands, '```']
      : []),
  ].join('\n');

const buildReport = (report) => {
  const math = report.sections.math;
  const api = report.sections.api;
  const overlay = report.sections.overlay;
  const bundle = report.sections.bundle;
  const env = report.environment;
  const dataset = report.dataset;

  const lines = [
    '# Замер измерительного ядра Stage 2A',
    '',
    '<!-- Файл создаётся командой `pnpm benchmark:measurement`. Руками не правится: числа',
    '     в нём и в benchmark-results.json обязаны совпадать, а две независимые записи',
    '     одних и тех же величин однажды разойдутся. -->',
    '',
    `Снято: ${report.generatedAt}`,
    '',
    '## Среда',
    '',
    '| Что | Значение |',
    '| --- | --- |',
    `| Python | ${env.python} (${env.implementation}) |`,
    `| Node | ${report.web?.environment?.node ?? '—'} |`,
    `| Система | ${env.platform} |`,
    `| Процессор | ${env.processor ?? env.machine} |`,
    `| Коммит | ${env.git_commit ?? '—'} |`,
    `| Разрешение таймера | ${fixed(env.timer_resolution_ns, 1)} нс |`,
    `| Браузер | ${overlay?.userAgent ?? '—'} |`,
    '',
    '## Датасет',
    '',
    `\`${dataset.path}\`, ${dataset.id} ${dataset.version}, случаев: ${dataset.cases}.`,
    `Отпечаток: \`${dataset.sha256.slice(0, 16)}…\``,
    '',
    'Сравнивать замеры, снятые на разных отпечатках датасета, нельзя: это разные наборы случаев.',
    '',
    '## Арифметика величин',
    '',
    `Случаев: ${math.summary.total}, в допуске: ${math.summary.passed}, воспроизводимы: ${
      math.summary.total - math.summary.unrepeatable.length
    }.`,
    '',
    mathTable(math),
    '',
    math.summary.failed.length
      ? `**Разошлись с датасетом:** ${math.summary.failed.join(', ')}`
      : 'Все случаи в допуске.',
    '',
  ];

  if (overlay?.status === 'ok') {
    lines.push(
      '## Слой измерений',
      '',
      `Холст ${overlay.canvas.cssWidth}×${overlay.canvas.cssHeight} CSS-пикселей,` +
        ` devicePixelRatio ${overlay.devicePixelRatio}, кадров на замер: ${overlay.draw[0]?.frames ?? '—'}.`,
      `Пустой кадр (очистка и чтение пикселя): ${fixed(overlay.overhead?.medianMs, 2)} мс.`,
      '',
      overlayTable(overlay),
      '',
      'Числа сняты в headless-браузере на программной растеризации: это верхняя оценка' +
        ' времени кадра, на машине с аппаратным ускорением кадр дешевле. Цели вида' +
        ' «60 кадров в секунду» здесь нет — сначала измеренная база, вывод потом.',
      '',
    );
  } else if (overlay) {
    lines.push(skippedBlock('Слой измерений', overlay), '');
  }

  if (bundle?.status === 'ok') {
    lines.push('## Вес слоя', '', bundleTable(bundle), '', bundle.note, '');
  } else if (bundle) {
    lines.push(skippedBlock('Вес слоя', bundle), '');
  }

  if (api?.status === 'ok') {
    const metrics = api.metrics;
    lines.push(
      '## Сервисный слой на живой базе',
      '',
      `Измерений на листе: ${api.measurements_seeded}.`,
      '',
      '| Операция | Медиана, мс | p95, мс | Повторов |',
      '| --- | ---: | ---: | ---: |',
      ...Object.entries(metrics)
        .filter(([key]) => key !== 'queries')
        .map(
          ([key, value]) =>
            `| \`${key}\` | ${fixed(value.median_ms, 2)} | ${fixed(value.p95_ms, 2)} | ${
              value.iterations
            } |`,
        ),
      '',
      `Запросов на список измерений: ${metrics.queries.list_for_sheet}, на список строк обмера: ${metrics.queries.list_items}.`,
      metrics.queries.n_plus_one
        ? '**Найден N+1:** число запросов больше одного на операцию списка.'
        : 'N+1 нет: список — один запрос независимо от числа измерений.',
      '',
    );
  } else if (api) {
    lines.push(skippedBlock('Сервисный слой на живой базе', api), '');
  }

  return `${lines.join('\n').replace(/\n{3,}/g, '\n\n')}\n`;
};

// --- запуск ---

const python = runPython();
const web = runWeb();

const report = {
  schema: 'quantor.benchmark.v1',
  generatedAt: new Date().toISOString(),
  environment: python.payload.environment ?? {},
  dataset: python.payload.dataset ?? {},
  web: { environment: web.environment ?? {} },
  sections: {
    math: python.payload.sections?.math ?? {
      status: 'skipped',
      reason: 'Python-часть не дала результата',
    },
    api: python.payload.sections?.api ?? {
      status: 'skipped',
      reason: 'Python-часть не дала результата',
    },
    overlay: web.sections?.overlay ?? { status: 'skipped', reason: 'Web-часть не дала результата' },
    bundle: web.sections?.bundle ?? { status: 'skipped', reason: 'Web-часть не дала результата' },
  },
};

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(JSON_PATH, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
writeFileSync(REPORT_PATH, buildReport(report), 'utf8');

process.stdout.write(`Результаты: ${JSON_PATH}\n`);
process.stdout.write(`Отчёт: ${REPORT_PATH}\n`);

// Ненулевой код только за расхождение арифметики с датасетом. Пропущенный раздел — это
// честно отсутствующее измерение, а не провал: падать из-за неподнятого стенда значило бы
// приучать не смотреть на код возврата.
process.exit(report.sections.math.status === 'ok' ? 0 : 1);
