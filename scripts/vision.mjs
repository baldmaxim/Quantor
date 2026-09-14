#!/usr/bin/env node
/**
 * ML-контур vision/: запуск интерпретатором vision/.venv-train (иначе venv бэкенда) с рабочим
 * каталогом vision. Контур не часть apps/api (ADR-0021).
 *
 *   node scripts/vision.mjs check            # ruff, mypy, pytest каркаса и лицензионный гейт
 *   node scripts/vision.mjs licenses-check   # только лицензионный гейт по манифестам репозитория
 *   node scripts/vision.mjs environment      # любая команда vision
 */
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { venvExists, venvPython } from './paths.mjs';

const visionDir = join(fileURLToPath(new URL('..', import.meta.url)), 'vision');

// Окружение обучения vision/.venv-train (torch: CUDA на GPU-машине, CPU на машине разработки).
// Без него — venv бэкенда: лицензионный гейт и команды без torch работают, проверка типов — нет.
const trainPython = join(
  visionDir,
  '.venv-train',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const python = existsSync(trainPython) ? trainPython : venvExists() ? venvPython() : null;
if (python === null) {
  console.error(
    '\nНет ни vision/.venv-train, ни apps/api/.venv. Инструкция — docs/stage2b/gpu-runbook.md, § 5а\n',
  );
  process.exit(1);
}

const run = (args) => {
  const result = spawnSync(python, args, { cwd: visionDir, stdio: 'inherit' });
  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  return result.status ?? 1;
};

const args = process.argv.slice(2);
if (args[0] === 'check') {
  if (python !== trainPython) {
    console.error(
      '\nПроверка vision требует vision/.venv-train с torch (CPU достаточно): gpu-runbook.md, § 5а\n',
    );
    process.exit(1);
  }
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
