#!/usr/bin/env node
/**
 * Обёртка над docker compose: единый compose-файл, корень репозитория как project directory,
 * поэтому необязательный корневой .env подхватывается автоматически.
 */
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { repoRoot } from './paths.mjs';

const composeFile = join(repoRoot, 'infra', 'docker-compose.yml');
const args = [
  'compose',
  '-f',
  composeFile,
  '--project-directory',
  repoRoot,
  ...process.argv.slice(2),
];

const result = spawnSync('docker', args, {
  cwd: repoRoot,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

if (result.error) {
  console.error(
    '\nНе удалось выполнить docker.\nПроверьте, что Docker Desktop установлен и запущен.\n',
  );
  process.exit(1);
}
process.exit(result.status ?? 1);
