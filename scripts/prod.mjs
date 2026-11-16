#!/usr/bin/env node
/**
 * Сопровождение боевого Quantor с рабочей машины: `pnpm prod <команда>`.
 *
 * Команды выполняются по ssh внутри работающего контейнера api (`compose.sh exec -T api
 * python -m app.cli ...`, `apps/api/app/services/cad_ops.py`). HTTP-доступа и токенов нет:
 * доступ — у того, у кого есть ssh к серверу. Пишет на сервер только `resolve` / `reopen`.
 *
 *   pnpm prod release                         выкаченный sha и коммиты origin/main сверх него
 *   pnpm prod remarks [--status open|resolved|all] [--project <id>] [--job <id>] [--limit N]
 *   pnpm prod bundle <job_id> [--attempt N] [--no-pdf] [--dest <каталог>]
 *   pnpm prod resolve <remark_id>             замечание исправлено
 *   pnpm prod reopen <remark_id>              замечание снова открыто
 *
 * Выгрузка по умолчанию — в `.quantor-prod/bundles/<job_id>[-a<N>]/` (каталог сам себя
 * исключает из git). Окружение: QUANTOR_SSH (по умолчанию suvpn, ADR-0046).
 */
import { spawn, spawnSync } from 'node:child_process';
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { join, resolve } from 'node:path';
import { repoRoot } from './paths.mjs';

const SSH_HOST = process.env.QUANTOR_SSH || 'suvpn';
const REMOTE_DIR = '/opt/portals/quantor';
const SAFE_ARG = /^[A-Za-z0-9_.:=-]+$/;
const PROD_DIR = join(repoRoot, '.quantor-prod');

function fail(message) {
  console.error(message);
  process.exit(1);
}

function remoteCli(args) {
  for (const arg of args) {
    if (!SAFE_ARG.test(arg)) fail(`Недопустимый аргумент для сервера: ${arg}`);
  }
  return `${REMOTE_DIR}/compose.sh exec -T api python -m app.cli ${args.join(' ')}`;
}

function sshInherit(command) {
  const result = spawnSync('ssh', [SSH_HOST, command], { stdio: 'inherit' });
  if (result.error) fail(`ssh не запустился: ${result.error.message}`);
  return result.status ?? 1;
}

function release() {
  const result = spawnSync('ssh', [SSH_HOST, `cat ${REMOTE_DIR}/RELEASE`], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  if (result.status !== 0) fail('Не удалось прочитать RELEASE на сервере');
  const sha = result.stdout.trim();
  console.log(`Выкачено на ${SSH_HOST}: ${sha}`);
  const log = spawnSync('git', ['-C', repoRoot, 'log', '--oneline', `${sha}..origin/main`], {
    encoding: 'utf8',
  });
  if (log.status !== 0) {
    console.log('Коммита нет в локальной истории: выполните git fetch origin');
    return 0;
  }
  const pending = log.stdout.trim();
  console.log(
    pending ? `В origin/main сверх выкаченного:\n${pending}` : 'origin/main выкачен целиком',
  );
  return 0;
}

function takeOption(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return undefined;
  const value = args[index + 1];
  if (value === undefined) fail(`Нет значения у ${name}`);
  args.splice(index, 2);
  return value;
}

function ensureProdDir() {
  mkdirSync(PROD_DIR, { recursive: true });
  const ignore = join(PROD_DIR, '.gitignore');
  if (!existsSync(ignore)) writeFileSync(ignore, '# Выгрузки с боевого сервера: не в git\n*\n');
}

async function bundle(rawArgs) {
  const args = [...rawArgs];
  const dest = takeOption(args, '--dest');
  const attempt = takeOption(args, '--attempt');
  const noPdf = args.includes('--no-pdf');
  const rest = args.filter((arg) => arg !== '--no-pdf');
  if (rest.length !== 1)
    fail('Использование: pnpm prod bundle <job_id> [--attempt N] [--no-pdf] [--dest <каталог>]');
  const [jobId] = rest;

  ensureProdDir();
  const target = resolve(
    dest ?? join(PROD_DIR, 'bundles', attempt ? `${jobId}-a${attempt}` : jobId),
  );
  if (existsSync(target) && readdirSync(target).length > 0) fail(`Каталог не пуст: ${target}`);
  mkdirSync(target, { recursive: true });

  const cliArgs = ['cad-bundle', jobId];
  if (attempt) cliArgs.push('--attempt', attempt);
  if (noPdf) cliArgs.push('--no-pdf');
  const archive = join(PROD_DIR, `bundle-${process.pid}.tar.gz`);
  const status = await new Promise((done) => {
    const child = spawn('ssh', [SSH_HOST, remoteCli(cliArgs)], {
      stdio: ['ignore', 'pipe', 'inherit'],
    });
    const sink = createWriteStream(archive);
    child.stdout.pipe(sink);
    child.on('error', (error) => fail(`ssh не запустился: ${error.message}`));
    child.on('close', (code) => sink.on('close', () => done(code ?? 1)).end());
  });
  if (status !== 0) {
    rmSync(archive, { force: true });
    fail(`Выгрузка не удалась (код ${status})`);
  }
  const untar = spawnSync('tar', ['-xzf', archive, '-C', target], { stdio: 'inherit' });
  rmSync(archive, { force: true });
  if (untar.status !== 0) fail('Не удалось распаковать архив выгрузки');
  console.log(`Выгрузка: ${target}`);
  return 0;
}

const [command, ...args] = process.argv.slice(2);
let code;
switch (command) {
  case 'release':
    code = release();
    break;
  case 'remarks':
    code = sshInherit(remoteCli(['cad-remarks', ...args]));
    break;
  case 'bundle':
    code = await bundle(args);
    break;
  case 'resolve':
  case 'reopen':
    if (args.length !== 1) fail(`Использование: pnpm prod ${command} <remark_id>`);
    code = sshInherit(
      remoteCli(['cad-remark-status', args[0], command === 'resolve' ? 'resolved' : 'open']),
    );
    break;
  default:
    console.error(
      'Команды: release | remarks | bundle | resolve | reopen (подробно — scripts/prod.mjs)',
    );
    code = command ? 1 : 0;
}
process.exit(code);
