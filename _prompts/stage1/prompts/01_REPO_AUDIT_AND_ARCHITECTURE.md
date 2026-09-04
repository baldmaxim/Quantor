# PROMPT 01 — Repository audit + architecture decisions

Прочитай `00_MASTER_CONTEXT.md` и все reference docs Stage 1.

Цель этого шага — **не писать половину продукта**, а зафиксировать фундаментальные решения до bootstrap.

## 1. Выполни аудит репозитория

Read-only сначала:
- дерево файлов;
- package managers / Python env;
- существующие frontend/backend apps;
- Docker/infra;
- CI;
- existing DB/storage/auth;
- existing CLAUDE.md / AGENTS.md / conventions;
- тесты;
- secrets/config patterns.

Не делай выводов по именам файлов — прочитай ключевые конфиги.

## 2. Выбери целевую форму Stage 1

Если repo пустой, default architecture:

```text
apps/
  web/       Next.js + React + TypeScript
  api/       FastAPI + Pydantic + SQLAlchemy
packages/
  ui/        shared UI primitives where useful
  api-client/ generated from OpenAPI or equivalent
infra/
  docker-compose.yml
docs/
  architecture/
  adr/
scripts/
```

Не создавай `apps/worker` только ради пустого scaffold. Future workers — документированный boundary.

Local dependencies:
- PostgreSQL using PostGIS-capable image;
- MinIO/S3-compatible object storage;
- Redis только если уже нужен текущей реализации. Иначе документируй future boundary и не добавляй idle infrastructure.

## 3. ADR

Создай короткие ADR (или адаптируй существующую систему ADR):

- ADR-001: monorepo/frontend/backend boundaries;
- ADR-002: object storage vs database for binaries;
- ADR-003: immutable Document + DocumentRevision model;
- ADR-004: viewer rendering architecture (`pdf.js base + separate overlay`, future tile backend);
- ADR-005: async Job abstraction now, durable orchestrator later;
- ADR-006: provider-neutral model gateway boundary for local/remote models;
- ADR-007: legacy recognized package v1 import and future manifest-based v2;
- ADR-008: coordinate/provenance conventions.

ADR должны содержать: Context, Decision, Consequences, Alternatives rejected/deferred.

## 4. Project instructions

Если в repo нет `CLAUDE.md`, создай короткий root `CLAUDE.md`. Если есть — не перезаписывай; добавь/обнови только секцию QTO Portal, не ломая существующие инструкции.

В `CLAUDE.md` зафиксируй:
- Stage 1 scope;
- common commands (после bootstrap они будут обновлены);
- architectural boundaries;
- запрет model/QTO implementation на Stage 1;
- rule: inspect before edit, run tests, no autonomous git operations.

## 5. Не делать

На этом шаге не надо:
- поднимать контейнеры;
- строить UI;
- писать importer;
- писать viewer;
- создавать десятки будущих таблиц.

## Acceptance

В конце:
- покажи текущую архитектуру repo;
- список ADR;
- точный рекомендуемый file tree для Prompt 02;
- список решений, которые сознательно отложены;
- если есть blocker, сформулируй **один** минимальный вопрос. Если blocker нет — не задавай вопросов.
