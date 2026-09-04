# Quantor

Портал автоматизированного подсчёта строительных объёмов по проектной документации.

Текущее состояние — **Stage 1, фундамент**: работает каркас портала, API отдаёт версии
контракта и состояние зависимостей, интерфейс показывает страницу проектов. Загрузка файлов,
импорт распознанных пакетов и просмотрщик чертежей — следующие шаги (см. `_prompts/stage1/`).

## Что нужно на машине

| Инструмент | Версия           | Проверка                                                             |
| ---------- | ---------------- | -------------------------------------------------------------------- |
| Node.js    | ≥ 20.9           | `node --version`                                                     |
| pnpm       | ≥ 10             | `pnpm --version`                                                     |
| Python     | 3.12 или 3.13    | `py -3.12 --version` (Windows), `python3.12 --version` (Linux/macOS) |
| Docker     | любой актуальный | `docker --version`, Docker Desktop должен быть **запущен**           |

## Запуск с нуля

```bash
git clone https://github.com/baldmaxim/Quantor.git quantor
cd quantor

pnpm install       # зависимости Node
pnpm run setup     # окружение Python: apps/api/.venv + зависимости

pnpm infra:up      # PostgreSQL/PostGIS и MinIO в Docker
pnpm db:migrate    # миграции базы
pnpm dev           # API на :8000 и веб на :3000
```

Открыть <http://localhost:3000> — произойдёт переход на `/projects`, на странице будет виден
блок «Состояние API» с версией контракта и окружением.

Проверка бэкенда напрямую:

```bash
curl http://localhost:8000/health/live     # {"status":"ok"}
curl http://localhost:8000/health/ready    # состояние базы и хранилища
curl http://localhost:8000/api/v1/meta     # версии и флаги возможностей
```

Документация API: <http://localhost:8000/api/docs>.
Консоль MinIO: <http://localhost:9001> (логин и пароль — из `.env.example`).

## Запуск с другого компьютера

Приложения слушают `0.0.0.0`, поэтому портал доступен по сети. На машине, где запущен портал,
скопируйте `.env.example` в `.env` и укажите адрес хоста:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://192.168.1.50:8000
API_CORS_ORIGINS=http://192.168.1.50:3000
```

Затем перезапустите `pnpm dev`. Без `.env` всё работает на локальных умолчаниях.

## Команды

| Команда                             | Что делает                                           |
| ----------------------------------- | ---------------------------------------------------- |
| `pnpm run setup`                    | создаёт `apps/api/.venv` и ставит зависимости Python |
| `pnpm infra:up` / `pnpm infra:down` | поднимает и останавливает PostgreSQL и MinIO         |
| `pnpm infra:logs`                   | логи контейнеров                                     |
| `pnpm dev`                          | API и веб одновременно                               |
| `pnpm lint`                         | `ruff` для бэкенда, `eslint` для фронтенда           |
| `pnpm typecheck`                    | `mypy` и `tsc`                                       |
| `pnpm test`                         | `pytest` и `vitest`                                  |
| `pnpm test:e2e`                     | Playwright (нужен `pnpm exec playwright install`)    |
| `pnpm build`                        | генерация клиента API и сборка веб-приложения        |
| `pnpm db:migrate`                   | накатывает миграции                                  |
| `pnpm api-client:generate`          | FastAPI → `openapi.json` → TypeScript-клиент         |

## Структура

```text
apps/web              интерфейс: Next.js + React + TypeScript
apps/api              API: FastAPI + SQLAlchemy + Alembic
packages/api-client   сгенерированный TypeScript-клиент (не править руками)
infra                 docker compose: PostgreSQL/PostGIS + MinIO
docs/adr              архитектурные решения
docs/architecture     аудит репозитория и целевая архитектура
_prompts/stage1       пакет промтов этапа и reference-документы
scripts               кроссплатформенные команды разработчика
```

## Если что-то не запускается

| Симптом                               | Причина и что делать                                                             |
| ------------------------------------- | -------------------------------------------------------------------------------- |
| `pnpm run setup` не находит Python    | поставьте 3.12: `winget install Python.Python.3.12`                              |
| `pnpm infra:up` пишет про docker      | запустите Docker Desktop и повторите                                             |
| `/health/ready` отвечает `degraded`   | не подняты контейнеры (`pnpm infra:up`) или заняты порты                         |
| порт 5432 занят локальным PostgreSQL  | в `.env` поставьте `POSTGRES_PORT=5433` и повторите `pnpm infra:up`              |
| порт 9000 занят                       | в `.env` поставьте `S3_PORT=9001` и `S3_ENDPOINT_URL=http://localhost:9001`      |
| «API недоступен» на странице проектов | бэкенд не запущен или в `NEXT_PUBLIC_API_BASE_URL` не тот адрес                  |
| CI падает на `api-client:check`       | контракт изменился: выполните `pnpm api-client:generate` и закоммитьте результат |

## Документация

- [План работ этапа](docs/stage1/ROADMAP.md)
- [Образец дизайна](design-reference.html) — откройте файл в браузере
- [Границы этапа и правила разработки](CLAUDE.md)
- [Архитектурные решения](docs/adr/README.md)
- [Аудит репозитория](docs/architecture/repo-audit-2026-09-04.md)
- [Что сделано на Stage 1](docs/stage1/README.md)
