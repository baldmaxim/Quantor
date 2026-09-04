#!/usr/bin/env node
/**
 * Готовит окружение Python для apps/api: находит интерпретатор 3.12+, создаёт venv, ставит зависимости.
 * Node-зависимости ставит pnpm install (см. README).
 */
import { spawnSync } from 'node:child_process';
import { apiDir, venvDir, venvExists, venvPython } from './paths.mjs';

const MIN = [3, 12];
const MAX_EXCLUSIVE = [3, 14]; // 3.14 пока опережает бинарные колёса драйверов БД

const candidates =
  process.platform === 'win32'
    ? [
        ['py', ['-3.13']],
        ['py', ['-3.12']],
        ['python', []],
      ]
    : [
        ['python3.13', []],
        ['python3.12', []],
        ['python3', []],
        ['python', []],
      ];

const probe = (cmd, args) => {
  // shell: false — иначе Windows-оболочка ломает аргументы, а `py` и `python` и так лежат в PATH.
  const res = spawnSync(cmd, [...args, '--version'], { encoding: 'utf8' });
  if (res.status !== 0) return null;
  const match = /(\d+)\.(\d+)\.\d+/.exec(`${res.stdout ?? ''}${res.stderr ?? ''}`);
  if (!match) return null;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  const value = major * 100 + minor;
  if (value < MIN[0] * 100 + MIN[1]) return null;
  if (value >= MAX_EXCLUSIVE[0] * 100 + MAX_EXCLUSIVE[1]) return null;
  return `${major}.${minor}`;
};

const run = (cmd, args, options = {}) => {
  const res = spawnSync(cmd, args, { stdio: 'inherit', ...options });
  if (res.error) {
    console.error(res.error.message);
    process.exit(1);
  }
  if (res.status !== 0) process.exit(res.status ?? 1);
};

if (!venvExists()) {
  let chosen = null;
  for (const [cmd, args] of candidates) {
    const version = probe(cmd, args);
    if (version) {
      chosen = { cmd, args, version };
      break;
    }
  }

  if (!chosen) {
    console.error(
      `\nНе найден Python ${MIN.join('.')}–3.13.\n` +
        'Установите Python 3.12 или 3.13 и повторите: pnpm run setup\n' +
        'Windows: winget install Python.Python.3.12\n',
    );
    process.exit(1);
  }

  console.log(`> Python ${chosen.version} (${chosen.cmd} ${chosen.args.join(' ')}) -> ${venvDir}`);
  run(chosen.cmd, [...chosen.args, '-m', 'venv', venvDir]);
}

console.log('> обновление pip');
run(venvPython(), ['-m', 'pip', 'install', '--quiet', '--upgrade', 'pip']);

console.log('> установка зависимостей apps/api');
run(venvPython(), ['-m', 'pip', 'install', '--editable', '.[dev]'], { cwd: apiDir });

console.log(
  '\nГотово. Дальше:\n  pnpm up          # postgres + minio в Docker\n  pnpm db:migrate  # миграции\n  pnpm dev         # api + web\n',
);
