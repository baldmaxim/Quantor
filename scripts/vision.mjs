#!/usr/bin/env node
/**
 * ML-контур vision/: запуск интерпретатором venv бэкенда с рабочим каталогом vision. Контур не часть
 * apps/api (ADR-0021); тяжёлые extras (torch, SAM, Transformers) ставятся только на GPU-хосте.
 *
 *   node scripts/vision.mjs check            # ruff, mypy, pytest каркаса и лицензионный гейт
 *   node scripts/vision.mjs licenses-check   # только лицензионный гейт по манифестам репозитория
 *   node scripts/vision.mjs environment      # любая команда vision
 */
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { venvExists, venvPython } from './paths.mjs';

const visionDir = join(fileURLToPath(new URL('..', import.meta.url)), 'vision');

if (!venvExists()) {
  console.error(
    '\nОкружение Python не найдено: apps/api/.venv\nЗапустите сначала:  pnpm run setup\n',
  );
  process.exit(1);
}

const run = (args) => {
  const result = spawnSync(venvPython(), args, { cwd: visionDir, stdio: 'inherit' });
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
    ['-m', 'mypy', 'quantor_vision', 'tests'],
    ['-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
    ['-m', 'quantor_vision', 'licenses-check'],
  ];
  for (const step of steps) {
    const code = run(step);
    if (code !== 0) process.exit(code);
  }
  process.exit(0);
}

process.exit(run(['-m', 'quantor_vision', ...args]));
