# Деплой Quantor

Выкладка изменений на `quantor.meridianai.ru`. Сборка — только в CI (GitHub Actions → GHCR), на
сервере — `update.sh` с git-sha. Первичная установка сервера, сертификат и `.env` —
[deploy/README.md](deploy/README.md); решения — [ADR-0031](docs/adr/0031-lokalnaya-autentifikaciya-s-odobreniem.md)
(вход), [ADR-0032](docs/adr/0032-boevoe-razvyortyvanie-na-selectel.md) (развёртывание) и
[ADR-0046](docs/adr/0046-pereezd-boevogo-stenda-na-suvpn.md) (переезд на suvpn).

> **С 2026-11-13 боевой Quantor живёт на сервере `suvpn` — деплоить только туда.**
> Старый сервер `quantor` (Selectel) выведен из выкладки: стек остановлен, тома оставлены для отката,
> `update.sh` там — заглушка, отменяющая выкладку (`/opt/portals/quantor/MOVED.txt`). Команды
> `ssh quantor …` из старых заметок и истории не использовать.

## Production

| Что             | Значение                                                                             |
| --------------- | ------------------------------------------------------------------------------------ |
| Портал          | <https://quantor.meridianai.ru>                                                      |
| Админка         | <https://admin.quantor.meridianai.ru>                                                |
| Сервер          | `suvpn`: 4 vCPU / 16 ГБ / 493 ГБ, Ubuntu 24.04 — `ssh suvpn` (адрес только в `~/.ssh/config`) |
| Каталог портала | `/opt/portals/quantor` — compose-проект `quantor`, `.env`, `RELEASE`, скрипты        |
| Вход (ingress)  | `/opt/infra/nginx` — infra-nginx и certbot, сайт в `conf.d/quantor.conf`             |
| Образы          | `ghcr.io/baldmaxim/quantor-{api,web,admin}` с тегом git-sha, зеркало `quantor-minio` |
| Текущий выпуск  | `/opt/portals/quantor/RELEASE`                                                       |
| Резервная копия | cron 03:17 UTC → `/opt/portals/quantor/backups`, база, 7 дней; файлы MinIO не копируются |
| Сертификат      | Let's Encrypt на оба имени, certbot продлевает сам                                   |

## Обычный деплой

1. Изменения закоммичены и запушены в `origin/main`.
2. Собрать образы и дождаться зелёного прогона:

   ```bash
   gh workflow run publish.yml --ref main
   gh run watch "$(gh run list --workflow publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
   ```

3. Выкатить ровно этот коммит:

   ```bash
   ssh suvpn "/opt/portals/quantor/update.sh $(git rev-parse HEAD)"
   ```

   Скрипт: скачивает образы → создаёт бакет, если его нет → накатывает миграции → перезапускает
   api, worker, cad-worker, web, admin → сверяет, что все из одной сборки → ждёт `/health/ready`. Итог —
   строка `готово: <sha>`, выпуск записывается в `RELEASE`. Иначе — `ВЫКЛАДКА НЕ ЧИСТАЯ`,
   `RELEASE` не меняется.

## Деплой без GitHub Actions

Если `publish.yml` не запускается (startup_failure, очередь не двигается), образы собираются на своей
машине и уезжают на сервер по ssh, реестр не нужен:

```bash
deploy/ship-local.sh                 # origin/main
deploy/ship-local.sh <git-ref>       # конкретный коммит; --build-only — только собрать
```

Скрипт берёт чистые `git worktree` Quantor и CAD_engine (по `pins.json`, сверка sha256), собирает
api/web/admin/cad-worker как `publish.yml`, передаёт их `docker save | ssh docker load`, кладёт на
сервер `update.sh` из образа и запускает его с `SKIP_PULL=1`. Нужны docker, jq и клон CAD_engine рядом
с Quantor (`CAD_ENGINE_REPO`). Образов такой сборки в GHCR нет; коммиты раньше появления `SKIP_PULL`
этим путём не выкатываются. Собирать на сервере нельзя: там нет исходников, а сборка должна совпадать с CI.
Сервер по умолчанию — `suvpn` (переменная `QUANTOR_SSH`).

## CAD-исполнитель (PDF → DXF, ADR-0036)

Сервис `cad-worker` (образ `quantor-cad-worker`) берёт только задания `cad_pdf_convert`, по одному.
Образ собирает `publish.yml` (job `build-cad-worker`) поверх `quantor-api` того же коммита; архив
движка скачивается из приватного `baldmaxim/CAD_engine` по `tools/cad_engine/pins.json`
(`engine.repo_ref`, `engine.archive_path`) с проверкой SHA256. Секрет репозитория
**`CAD_ENGINE_DEPLOY_KEY`** — deploy-key только на чтение `CAD_engine`; без него шаг checkout падает.

- Возможность открывает флаг пространства `cad.export` (админка → пространство); без него маршруты отвечают 403.
- Лимиты в `.env` (необязательно): `CAD_MAX_MEMORY_MB` (6144, потолок адресного пространства движка),
  `CAD_WORKER_MEM_LIMIT` (4g), `CAD_WORKER_MEMSWAP_LIMIT` (6g, память + swap), `cpus: 2.0`. Замер 2026-11-09: стр. 81 АР1.1 — пик 465 МБ, 54 с.
- Основной `worker` (импорт, геометрия, паспорт листа): `WORKER_MEM_LIMIT` (4g), `WORKER_MEMSWAP_LIMIT` (6g); до 2026-11-12 было 768m — разбор больших PDF падал по OOM.
- Пределы остальных под 16 ГБ suvpn (2026-11-13): db 2g (`shared_buffers` 1GB, `max_connections` 80), api 2g и
  4 процесса uvicorn (`API_WORKERS`), minio 1g, web 768m, admin 512m. Под 4 ГБ Selectel было вчетверо меньше.
- Если движок не сконфигурирован или не прошёл проверку, контейнер выходит с ошибкой: `compose.sh logs cad-worker`.

## Проверка

```bash
curl -fsS https://quantor.meridianai.ru/health/ready      # 200, все компоненты ok
ssh suvpn '/opt/portals/quantor/compose.sh ps'          # все контейнеры Up
ssh suvpn 'docker ps --format "{{.Names}}"'             # сосед amnezia-awg2 (VPN) на месте
```

В браузере: вход, список проектов, открытие документа, админка.

## Откат

```bash
ssh suvpn 'cat /opt/portals/quantor/RELEASE'                    # что сейчас
ssh suvpn '/opt/portals/quantor/update.sh <предыдущий git-sha>'
```

Откат образа не откатывает миграции: если версия меняла схему базы, откат решается отдельно, по
содержимому миграции.

## Частые операции

```bash
ssh suvpn '/opt/portals/quantor/compose.sh logs --tail 100 api'      # также worker, web, admin
ssh -t suvpn '/opt/portals/quantor/compose.sh run --rm api python -m app.cli create-admin --email <почта>'
ssh -L 9001:127.0.0.1:9001 suvpn                                     # консоль MinIO: http://localhost:9001
ssh suvpn 'ls -lh /opt/portals/quantor/backups'
ssh suvpn 'free -m; df -h /'
```

`create-admin` — первый администратор или восстановление доступа: пароль вводится в терминале,
не аргументом. Ручные команды compose — только через `compose.sh`: он подставляет выпуск из
`RELEASE`.

## Нельзя

- Собирать образы на сервере — там нет исходников, сборка — только CI или `ship-local.sh`.
- Выкатывать на старый сервер `quantor` — портал переехал на `suvpn` (ADR-0046).
- Менять `.env` скриптами или из чата: значения вписывает владелец руками на сервере.
- `docker system prune -a` и `docker compose down -v` — сносят чужие образы и тома с данными.
- Перезагружать nginx без `nginx -t`: вход общий, ошибка в одном файле роняет оба портала.
- Включать `calc.portal` через `FEATURE_FLAGS` — только отдельным решением владельца.

## Соседи на сервере

На `suvpn` рядом с Quantor работает только VPN AmneziaWG (контейнер `amnezia-awg2`, свои интерфейсы
`awg*` и правила ufw). Выкладка Quantor его не трогает: не менять его правила ufw, не трогать
сети `amnezia-*`. infra-nginx на suvpn обслуживает только Quantor.

## Старый сервер `quantor` (до 2026-11-13)

Selectel VDS 2-4-50 с соседями TG_Info, MailHub, ServerControl — они там и остаются, их выкладка
не меняется. От Quantor на нём:

- остановленный стек `quantor-*` и тома `quantor_*` — только для отката, удаление — решением владельца;
- `/opt/portals/quantor/update.sh` — заглушка, отменяющая выкладку; прежний — `update.sh.moved-20261113`;
- сайта Quantor в его infra-nginx больше нет: временный мост на suvpn снят 2026-11-13 после
  переключения DNS (прежние конфиги — `/opt/infra/nginx/quantor.conf.bak-premigrate-20261113` и
  `quantor.conf.bridge-removed-20261113`).
