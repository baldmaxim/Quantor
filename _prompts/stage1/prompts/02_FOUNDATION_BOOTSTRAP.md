# PROMPT 02 — Foundation bootstrap

Прочитай master context и ADR из Prompt 01. Следуй существующему repo, если он уже имеет зрелую структуру.

Цель: получить минимальный production-shaped skeleton, который запускается одной понятной командой и пока не содержит QTO-бизнес-логики.

## Frontend

Создай/настрой `apps/web`:
- latest stable Next.js + React;
- TypeScript strict;
- App Router, если это совместимо с repo;
- Tailwind;
- Radix/shadcn primitives по необходимости;
- TanStack Query;
- Zustand только как viewer/workspace ephemeral store dependency, без сложного state пока;
- Zod;
- ESLint + Prettier/formatter согласно repo;
- Vitest/Testing Library;
- Playwright config.

Не подключай pdf.js/PixiJS глобально в root layout. Они будут lazy workspace dependencies.

## Backend

Создай/настрой `apps/api`:
- Python 3.12+;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2 async;
- Alembic;
- async PostgreSQL driver;
- S3 client behind interface;
- pytest;
- structured JSON-capable logging;
- config via environment, typed settings.

Endpoints пока:
- `GET /health/live`;
- `GET /health/ready`;
- `GET /api/v1/meta` with API/schema version.

## Infrastructure

Local dev:
- PostgreSQL/PostGIS-capable Docker image;
- MinIO;
- health checks;
- named volumes;
- `.env.example` без секретов;
- no hardcoded production credentials.

Если Redis не используется Stage 1 кодом — не добавляй его только «на будущее».

## API contract

Настрой single-source contract:
- FastAPI OpenAPI;
- reproducible generation of TypeScript API client/types into `packages/api-client` or equivalent;
- CI/test должен находить drift generated client при необходимости.

Не дублируй Pydantic DTO вручную в TypeScript.

## Developer UX

Добавь root-level commands (`Makefile`, `justfile`, npm scripts — выбери то, что соответствует repo):
- `dev`;
- `up` / `down` for dependencies;
- `lint`;
- `typecheck`;
- `test`;
- `build`;
- `api-client-generate`;
- `db-migrate`.

README: 5–10 минут от clone до running shell.

## CI

Минимально:
- frontend lint/typecheck/test/build;
- backend lint/typecheck if selected + pytest;
- migration sanity;
- generated client drift check if practical.

Не усложняй matrix без причины.

## UI на этом шаге

Только `/` -> `/projects` и очень простой placeholder page. Настоящую оболочку делаем в Prompt 04.

## Acceptance

- clean install succeeds;
- local services start;
- API health endpoints pass;
- web opens;
- OpenAPI -> TS generation works;
- lint/typecheck/test/build green;
- no AI/QTO code.

В конце дай команды, которыми пользователь может воспроизвести запуск.
