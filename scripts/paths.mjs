import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const apiDir = join(repoRoot, 'apps', 'api');
export const webDir = join(repoRoot, 'apps', 'web');
export const apiClientDir = join(repoRoot, 'packages', 'api-client');
// На Linux-машине разработчика окружение лежит в .venv-linux; .venv — основной вариант.
const LINUX_VENV_DIR = join(apiDir, '.venv-linux');
export const venvDir =
  process.platform !== 'win32' &&
  !existsSync(join(apiDir, '.venv')) &&
  existsSync(LINUX_VENV_DIR)
    ? LINUX_VENV_DIR
    : join(apiDir, '.venv');

/** Путь к интерпретатору внутри venv бэкенда (Windows и POSIX раскладки различаются). */
export const venvPython = () =>
  process.platform === 'win32'
    ? join(venvDir, 'Scripts', 'python.exe')
    : join(venvDir, 'bin', 'python');

export const venvExists = () => existsSync(venvPython());
