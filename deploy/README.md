# Выкладка Quantor на Selectel

Решение и границы — [ADR-0032](../docs/adr/0032-boevoe-razvyortyvanie-na-selectel.md); вход — [ADR-0031](../docs/adr/0031-lokalnaya-autentifikaciya-s-odobreniem.md).

Сервер — отдельный Selectel VDS (2 vCPU / 4 ГБ / 50 ГБ, Ubuntu 24.04), SSH-алиас `quantor`
в `~/.ssh/config`. Адрес сервера в репозитории не хранится.

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
workflow): `ghcr.io/baldmaxim/quantor-{api,web,admin}` с тегами git-sha и `latest`, плюс
зеркало MinIO `quantor-minio` (реестр Chainguard с сервера недоступен).

## Первая выкладка

### 0. DNS

Две A-записи на IP сервера: `quantor.meridianai.ru` и `admin.quantor.meridianai.ru`.
Проверка: `dig +short quantor.meridianai.ru admin.quantor.meridianai.ru` возвращает адрес
сервера, а не фронт-прокси зоны.

### 1. Сервер

Docker, compose, swap 2 ГБ, ufw (22, 80, 443), часовой пояс Asia/Almaty — уже настроено
при подготовке сервера. Проверка: `ssh quantor 'docker compose version; swapon --show; ufw status'`.

### 2. Ingress и сертификат

```bash
ssh quantor 'docker network create infra_web; mkdir -p /opt/infra/nginx/conf.d /opt/portals/quantor/backups'
scp deploy/nginx/docker-compose.yml deploy/nginx/nginx.conf quantor:/opt/infra/nginx/
scp deploy/nginx/conf.d/00-acme.conf quantor:/opt/infra/nginx/conf.d/
ssh quantor 'cd /opt/infra/nginx && docker compose up -d'

# Сертификат на оба имени. Почта не передаётся.
ssh quantor 'cd /opt/infra/nginx && docker compose run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot --agree-tos --register-unsafely-without-email \
  -d quantor.meridianai.ru -d admin.quantor.meridianai.ru'

scp deploy/nginx/quantor.conf quantor:/opt/infra/nginx/conf.d/
ssh quantor 'docker exec infra-nginx nginx -t && docker exec infra-nginx nginx -s reload'
```

До запуска портала nginx на HTTPS отвечает 502 — это нормально.

### 3. Каталог портала и переменные

```bash
scp deploy/docker-compose.yml deploy/update.sh deploy/compose.sh deploy/backup.sh \
  deploy/quantor.env.example quantor:/opt/portals/quantor/
```

`.env` создаёт и заполняет **владелец на сервере**, скрипты его не меняют:

```bash
ssh quantor
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
gh auth token | ssh quantor 'docker login ghcr.io -u baldmaxim --password-stdin'
```

### 5. Запуск

```bash
ssh quantor '/opt/portals/quantor/update.sh <git-sha>'
```

Скрипт скачивает образы, создаёт бакет, накатывает миграции, поднимает стек и ждёт
`/health/ready`. Итог — строка `готово: <sha>`; выпуск записывается в `RELEASE`.
Ручные команды compose дальше — через `./compose.sh`: он подставляет тот же выпуск.

### 6. Первый администратор

Пароль вводится в терминале сервера без эха, не аргументом:

```bash
ssh -t quantor '/opt/portals/quantor/compose.sh run --rm api \
  python -m app.cli create-admin --email <почта владельца> --name "<Имя>"'
```

Администратор получает роль администратора платформы и `workspace_admin` в пространстве
`default`. Повторный вызов с той же почтой — восстановление доступа (новый пароль).

### 7. Резервные копии базы

```bash
ssh quantor 'cat > /etc/cron.d/quantor-backup <<"EOF"
17 3 * * * root /opt/portals/quantor/backup.sh
EOF'
```

Файлы MinIO в тестовом режиме не копируются — они на том же диске (ADR-0032).

## Проверка после выкладки

```bash
curl -sS https://quantor.meridianai.ru/health/ready          # 200, schema_revision = head
curl -sS -o /dev/null -w '%{http_code}\n' https://quantor.meridianai.ru/api/docs   # 404
curl -sS -o /dev/null -w '%{http_code}\n' -X PUT https://quantor.meridianai.ru/quantor-files/x  # 403
ssh quantor '/opt/portals/quantor/compose.sh ps; free -m; df -h /'
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
ssh quantor '/opt/portals/quantor/update.sh <новый git-sha>'
ssh quantor '/opt/portals/quantor/update.sh <предыдущий git-sha>'   # откат
```

Миграции вперёд откат образа не отменяет: если новая версия меняла схему, откат кода
требует и `alembic downgrade` — решается отдельно, по содержимому миграции.

## Обслуживание

```bash
ssh quantor 'docker logs --tail 100 quantor-api'
ssh quantor 'docker logs --tail 100 quantor-worker'
ssh -L 9001:127.0.0.1:9001 quantor        # консоль MinIO: http://localhost:9001
ssh quantor 'ls -lh /opt/portals/quantor/backups'
```

Флаги возможностей включаются в админке. `calc.portal` не включается ни там, ни в
`FEATURE_FLAGS` — только отдельным решением владельца после инженерного гейта.
