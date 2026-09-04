import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const apiDir = join(repoRoot, 'apps', 'api');
export const webDir = join(repoRoot, 'apps', 'web');
export const apiClientDir = join(repoRoot, 'packages', 'api-client');
export const venvDir = join(apiDir, '.venv');

/** Путь к интерпретатору внутри venv бэкенда (Windows и POSIX раскладки различаются). */
export const venvPython = () =>
  process.platform === 'win32'
    ? join(venvDir, 'Scripts', 'python.exe')
    : join(venvDir, 'bin', 'python');

export const venvExists = () => existsSync(venvPython());
