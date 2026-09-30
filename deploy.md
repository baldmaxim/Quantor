# Деплой Quantor

Выкладка изменений на `quantor.meridianai.ru`. Сборка — только в CI (GitHub Actions → GHCR), на
сервере — `update.sh` с git-sha. Первичная установка сервера, сертификат и `.env` —
[deploy/README.md](deploy/README.md); решения — [ADR-0031](docs/adr/0031-lokalnaya-autentifikaciya-s-odobreniem.md)
(вход) и [ADR-0032](docs/adr/0032-boevoe-razvyortyvanie-na-selectel.md) (развёртывание).

## Production

| Что             | Значение                                                                             |
| --------------- | ------------------------------------------------------------------------------------ |
| Портал          | <https://quantor.meridianai.ru>                                                      |
| Админка         | <https://admin.quantor.meridianai.ru>                                                |
| Сервер          | Selectel VDS 2-4-50, Ubuntu 24.04 — `ssh quantor` (адрес только в `~/.ssh/config`)   |
| Каталог портала | `/opt/portals/quantor` — compose-проект `quantor`, `.env`, `RELEASE`, скрипты        |
| Вход (ingress)  | `/opt/infra/nginx` — infra-nginx и certbot, сайт в `conf.d/quantor.conf`             |
| Образы          | `ghcr.io/baldmaxim/quantor-{api,web,admin}` с тегом git-sha, зеркало `quantor-minio` |
| Текущий выпуск  | `/opt/portals/quantor/RELEASE`                                                       |
| Резервная копия | cron 03:17 → `/opt/portals/quantor/backups`, база, 7 дней; файлы MinIO не копируются |
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
   ssh quantor "/opt/portals/quantor/update.sh $(git rev-parse HEAD)"
   ```

   Скрипт: скачивает образы → создаёт бакет, если его нет → накатывает миграции → перезапускает
   api, worker, web, admin → сверяет, что все из одной сборки → ждёт `/health/ready`. Итог —
   строка `готово: <sha>`, выпуск записывается в `RELEASE`. Иначе — `ВЫКЛАДКА НЕ ЧИСТАЯ`,
   `RELEASE` не меняется.

## Проверка

```bash
curl -fsS https://quantor.meridianai.ru/health/ready      # 200, все компоненты ok
ssh quantor '/opt/portals/quantor/compose.sh ps'          # все контейнеры Up
ssh quantor 'docker ps --format "{{.Names}}"'             # соседи tginfo-* на месте
```

В браузере: вход, список проектов, открытие документа, админка.

## Откат

```bash
ssh quantor 'cat /opt/portals/quantor/RELEASE'                    # что сейчас
ssh quantor '/opt/portals/quantor/update.sh <предыдущий git-sha>'
```

Откат образа не откатывает миграции: если версия меняла схему базы, откат решается отдельно, по
содержимому миграции.

## Частые операции

```bash
ssh quantor '/opt/portals/quantor/compose.sh logs --tail 100 api'      # также worker, web, admin
ssh -t quantor '/opt/portals/quantor/compose.sh run --rm api python -m app.cli create-admin --email <почта>'
ssh -L 9001:127.0.0.1:9001 quantor                                     # консоль MinIO: http://localhost:9001
ssh quantor 'ls -lh /opt/portals/quantor/backups'
ssh quantor 'free -m; df -h /'
```

`create-admin` — первый администратор или восстановление доступа: пароль вводится в терминале,
не аргументом. Ручные команды compose — только через `compose.sh`: он подставляет выпуск из
`RELEASE`.

## Нельзя

- Собирать образы на сервере — там нет ни исходников, ни места в памяти.
- Менять `.env` скриптами или из чата: значения вписывает владелец руками на сервере.
- `docker system prune -a` и `docker compose down -v` — сносят чужие образы и тома с данными.
- Перезагружать nginx без `nginx -t`: вход общий, ошибка в одном файле роняет оба портала.
- Включать `calc.portal` через `FEATURE_FLAGS` — только отдельным решением владельца.

## Соседи на сервере

TG_Info (`pulse.meridianai.ru`) — compose-проект `tginfo` в `/opt/portals/tg-info`, своя база, свой
файл `conf.d/tginfo.conf` в общем infra-nginx. Выкладка Quantor его не трогает, и наоборот.
Памяти на двоих впритык: если `free -m` показывает меньше 500 МБ доступной, пора менять тариф на
4-8-80 — без переезда.
