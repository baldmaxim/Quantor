#!/usr/bin/env node
/**
 * Офлайн-импортёр PlanSwift (tools/planswift_gt): запуск интерпретатором venv бэкенда, но с рабочим
 * каталогом инструмента — он не часть apps/api и зависимостей API не импортирует.
 *
 *   node scripts/planswift.mjs check              # ruff, mypy, pytest на синтетике
 *   node scripts/planswift.mjs inspect <каталог>  # любая команда импортёра
 */
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { venvExists, venvPython } from './paths.mjs';

const toolDir = join(fileURLToPath(new URL('..', import.meta.url)), 'tools', 'planswift_gt');

if (!venvExists()) {
  console.error(
    '\nОкружение Python не найдено: apps/api/.venv\nЗапустите сначала:  pnpm run setup\n',
  );
  process.exit(1);
}

const run = (args) => {
  const result = spawnSync(venvPython(), args, { cwd: toolDir, stdio: 'inherit' });
  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  return result.status ?? 1;
};

const args = process.argv.slice(2);
if (args[0] === 'check') {
  const steps = [
    ['-m', 'ruff', 'check', '.'],
    ['-m', 'ruff', 'format', '--check', '.'],
    ['-m', 'mypy', 'planswift_gt', 'tests'],
    ['-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
  ];
  for (const step of steps) {
    const code = run(step);
    if (code !== 0) process.exit(code);
  }
  process.exit(0);
}

process.exit(run(['-m', 'planswift_gt', ...args]));
