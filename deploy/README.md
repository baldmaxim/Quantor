# Выкладка Quantor на сервер suvpn

Решение и границы — [ADR-0032](../docs/adr/0032-boevoe-razvyortyvanie-na-selectel.md) и
[ADR-0046](../docs/adr/0046-pereezd-boevogo-stenda-na-suvpn.md) (переезд); вход — [ADR-0031](../docs/adr/0031-lokalnaya-autentifikaciya-s-odobreniem.md).

Сервер — `suvpn` (4 vCPU / 16 ГБ / 493 ГБ, swap 8 ГБ, Ubuntu 24.04), SSH-алиас `suvpn`
в `~/.ssh/config`. Адрес сервера в репозитории не хранится. С 2026-11-13 Quantor работает только
здесь; прежний сервер `quantor` (Selectel) выведен из выкладки — см. «Старый сервер» в [deploy.md](../deploy.md).
Сосед на suvpn — VPN AmneziaWG (`amnezia-awg2`): его правила ufw и сети `amnezia-*` не трогать.

```
браузер ─ HTTPS ─► infra-nginx (/opt/infra/nginx, Let's Encrypt)
  quantor.meridianai.ru        /                → quantor-web:3000
                               /api/, /health/  → quantor-api:8000
                               /quantor-files/  → quantor-minio:9000   (подписанные ссылки, только чтение)
  admin.quantor.meridianai.ru  /                → quantor-admin:3001
quantor-worker, quantor-db (PostGIS 17), quantor-minio — внутренняя сеть, портов наружу нет
```

## Файлы

| Файл                                                                   | Где живёт на сервере                   |
| ---------------------------------------------------------------------- | -------------------------------------- |
| `deploy/docker-compose.yml`, `update.sh`, `compose.sh`, `backup.sh`    | `/opt/portals/quantor/`                |
| `deploy/quantor.env.example` → `.env` (chmod 600, заполняется вручную) | `/opt/portals/quantor/.env`            |
| `deploy/nginx/docker-compose.yml`, `nginx.conf`, `conf.d/00-acme.conf` | `/opt/infra/nginx/`                    |
| `deploy/nginx/quantor.conf` — после выпуска сертификата                | `/opt/infra/nginx/conf.d/quantor.conf` |

Образы собирает [publish.yml](../.github/workflows/publish.yml) (Actions → publish → Run
workflow): `ghcr.io/baldmaxim/quantor-{api,web,admin,cad-worker}` с тегами git-sha и `latest`, плюс
зеркало MinIO `quantor-minio` (реестр Chainguard с сервера недоступен).

## Первая выкладка

### 0. DNS

Две A-записи на IP сервера: `quantor.meridianai.ru` и `admin.quantor.meridianai.ru`.
Проверка: `dig +short quantor.meridianai.ru admin.quantor.meridianai.ru` возвращает адрес
сервера, а не фронт-прокси зоны.

### 1. Сервер

Docker, `docker-compose-v2`, `rsync`, swap 8 ГБ, ufw (22, 80/tcp, 443/tcp, 8443/udp для HTTP/3) —
настроено при переезде 2026-11-13; часовой пояс — UTC. Проверка: `ssh suvpn 'docker compose version; swapon --show; ufw status'`.

### 2. Ingress и сертификат

```bash
ssh suvpn 'docker network create infra_web; mkdir -p /opt/infra/nginx/conf.d /opt/portals/quantor/backups'
scp deploy/nginx/docker-compose.yml deploy/nginx/nginx.conf suvpn:/opt/infra/nginx/
scp deploy/nginx/conf.d/00-acme.conf suvpn:/opt/infra/nginx/conf.d/
ssh suvpn 'cd /opt/infra/nginx && docker compose up -d'

# Сертификат на оба имени. Почта не передаётся.
ssh suvpn 'cd /opt/infra/nginx && docker compose run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot --agree-tos --register-unsafely-without-email \
  -d quantor.meridianai.ru -d admin.quantor.meridianai.ru'

scp deploy/nginx/quantor.conf suvpn:/opt/infra/nginx/conf.d/
ssh suvpn 'docker exec infra-nginx nginx -t && docker exec infra-nginx nginx -s reload'
```

До запуска портала nginx на HTTPS отвечает 502 — это нормально.

### 3. Каталог портала и переменные

```bash
scp deploy/docker-compose.yml deploy/update.sh deploy/compose.sh deploy/backup.sh \
  deploy/quantor.env.example suvpn:/opt/portals/quantor/
```

`.env` создаёт и заполняет **владелец на сервере**, скрипты его не меняют:

```bash
ssh suvpn
cd /opt/portals/quantor && cp quantor.env.example .env && chmod 600 .env
openssl rand -hex 24   # дважды: для POSTGRES_PASSWORD и S3_SECRET_ACCESS_KEY
nano .env
```

Секреты в репозиторий и переписку не попадают. Тег выпуска в `.env` не пишется: его ведёт
`update.sh` в файле `RELEASE`.

### 4. Доступ к образам

Пакеты GHCR (`quantor-api`, `quantor-web`, `quantor-admin`, `quantor-minio`) остаются
закрытыми: в `quantor-minio` лежит сборка MinIO (AGPL-3.0), публично её не распространяем.
Серверу нужен вход — токен с `read:packages` создаёт и вводит владелец:

```bash
gh auth refresh -h github.com -s read:packages
gh auth token | ssh suvpn 'docker login ghcr.io -u baldmaxim --password-stdin'
```

### 5. Запуск

```bash
ssh suvpn '/opt/portals/quantor/update.sh <git-sha>'
```

Скрипт скачивает образы, создаёт бакет, накатывает миграции, поднимает стек и ждёт
`/health/ready`. Итог — строка `готово: <sha>`; выпуск записывается в `RELEASE`.
Ручные команды compose дальше — через `./compose.sh`: он подставляет тот же выпуск.

### 6. Первый администратор

Пароль вводится в терминале сервера без эха, не аргументом:

```bash
ssh -t suvpn '/opt/portals/quantor/compose.sh run --rm api \
  python -m app.cli create-admin --email <почта владельца> --name "<Имя>"'
```

Администратор получает роль администратора платформы и `workspace_admin` в пространстве
`default`. Повторный вызов с той же почтой — восстановление доступа (новый пароль).

### 7. Резервные копии базы

```bash
ssh suvpn 'cat > /etc/cron.d/quantor-backup <<"EOF"
17 3 * * * root /opt/portals/quantor/backup.sh
EOF'
```

Файлы MinIO в тестовом режиме не копируются — они на том же диске (ADR-0032).

## CAD-исполнитель (ADR-0036)

`cad-worker` — отдельный сервис и образ `quantor-cad-worker` (код `apps/api` + движок PDF → DXF в своём
venv; PyMuPDF и Shapely есть только в нём). Команда `python -m app.cad_worker`, одно задание за раз,
`cpus: 1.0`. Образ собирает job `build-cad-worker` в `publish.yml` после образов портала; `update.sh`
скачивает и перезапускает его вместе с остальными.

- Секрет репозитория GitHub **`CAD_ENGINE_DEPLOY_KEY`** — приватная часть deploy-key `quantor-publish-read`
  (только чтение `baldmaxim/CAD_engine`). `publish.yml` забирает им архив в контекст сборки; в образ ключ не попадает.
- Закрепление движка — `tools/cad_engine/pins.json`: `engine.repo_ref` (коммит), `engine.archive_path`,
  `engine.archive_sha256` (сверяется при сборке и runner'ом при старте).
- Возможность включает владелец флагом `cad.export` на пространство (админка); пилот — отдельное
  пространство. Для калибровки масштаба листа в нём же нужен `takeoff.manual`.
- Переменные лимитов в `.env` (по умолчанию в compose): `CAD_MAX_MEMORY_MB=6144`,
  `CAD_WORKER_MEM_LIMIT=1536m`, `CAD_WORKER_MEMSWAP_LIMIT=3g` (замер: пик 465 МБ на плане этажа). На сервере 2 vCPU / 4 ГБ: лимиты
  уточняются замером на пилотном листе.
- Проверка: `./compose.sh logs --tail 50 cad-worker` — первая строка JSON с версией движка; ошибка
  `CAD_ENGINE_UNAVAILABLE` — архив или окружение не прошли проверку.

## Проверка после выкладки

```bash
curl -sS https://quantor.meridianai.ru/health/ready          # 200, schema_revision = head
curl -sS -o /dev/null -w '%{http_code}\n' https://quantor.meridianai.ru/api/docs   # 404
curl -sS -o /dev/null -w '%{http_code}\n' -X PUT https://quantor.meridianai.ru/quantor-files/x  # 403
ssh suvpn '/opt/portals/quantor/compose.sh ps; free -m; df -h /'
```

В браузере:

1. Регистрация второго пользователя — «заявка ожидает одобрения».
2. В `admin.quantor.meridianai.ru` → «Пользователи и доступ» — одобрение с пространством и ролью.
3. Вход, загрузка PDF, воркер разбирает геометрию, просмотрщик открывает файл
   (запрос `/quantor-files/...` отвечает 206).
4. В DevTools у cookie `quantor_session` стоят `Secure` и `Domain=quantor.meridianai.ru`.
5. Телефон: вход, список проектов, установка PWA.

## Обновление и откат

```bash
ssh suvpn '/opt/portals/quantor/update.sh <новый git-sha>'
ssh suvpn '/opt/portals/quantor/update.sh <предыдущий git-sha>'   # откат
```

Миграции вперёд откат образа не отменяет: если новая версия меняла схему, откат кода
требует и `alembic downgrade` — решается отдельно, по содержимому миграции.

## Обслуживание

```bash
ssh suvpn 'docker logs --tail 100 quantor-api'
ssh suvpn 'docker logs --tail 100 quantor-worker'
ssh -L 9001:127.0.0.1:9001 suvpn        # консоль MinIO: http://localhost:9001
ssh suvpn 'ls -lh /opt/portals/quantor/backups'
```

Флаги возможностей включаются в админке. `calc.portal` не включается ни там, ни в
`FEATURE_FLAGS` — только отдельным решением владельца после инженерного гейта.
