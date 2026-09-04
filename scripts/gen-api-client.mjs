#!/usr/bin/env node
/**
 * Единый источник правды по API: FastAPI -> openapi.json -> TypeScript-клиент.
 * С флагом --check дополнительно проверяет, что сгенерированное совпадает с закоммиченным (drift-check).
 */
import { spawnSync } from 'node:child_process';
import { apiClientDir, apiDir, repoRoot, venvExists, venvPython } from './paths.mjs';

const check = process.argv.includes('--check');

const run = (cmd, args, options = {}) => {
  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...options,
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
};

const runWithRetry = (cmd, args, options = {}) => {
  const attempt = spawnSync(cmd, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...options,
  });
  if (attempt.status === 0) return;
  console.log('> повтор генерации после сбоя доступа к файлам');
  run(cmd, args, options);
};

if (!venvExists()) {
  console.error(
    '\nОкружение Python не найдено: apps/api/.venv\nЗапустите сначала:  pnpm run setup\n',
  );
  process.exit(1);
}

console.log('> экспорт OpenAPI из FastAPI');
run(venvPython(), ['-m', 'app.openapi_export'], { cwd: apiDir, shell: false });

console.log('> генерация TypeScript-клиента');
// Генератор очищает каталог src перед записью; на Windows это иногда упирается в временную
// блокировку файла индексатором или антивирусом, поэтому одна повторная попытка.
runWithRetry('pnpm', ['exec', 'openapi-ts'], { cwd: apiClientDir });

if (check) {
  console.log('> проверка расхождений (drift-check)');
  run('git', ['diff', '--exit-code', '--', 'packages/api-client'], { cwd: repoRoot });
  console.log('OpenAPI и TypeScript-клиент синхронны.');
}
