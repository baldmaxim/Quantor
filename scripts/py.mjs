#!/usr/bin/env node
/**
 * Запускает Python из venv бэкенда с рабочим каталогом apps/api.
 * Пример: node scripts/py.mjs -m pytest
 */
import { spawnSync } from 'node:child_process';
import { apiDir, venvExists, venvPython } from './paths.mjs';

if (!venvExists()) {
  console.error(
    '\nОкружение Python не найдено: apps/api/.venv\nЗапустите сначала:  pnpm run setup\n',
  );
  process.exit(1);
}

const result = spawnSync(venvPython(), process.argv.slice(2), {
  cwd: apiDir,
  stdio: 'inherit',
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
