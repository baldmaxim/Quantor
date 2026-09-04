# PROMPT 03 — Domain, storage and API shell

Прочитай master context, ADR и `reference/DOMAIN_CONTRACTS.md`.

Цель: заложить минимальные правильные сущности и API, необходимые оболочке и legacy import. Не строить quantity domain глубже контрактов.

## Data model

Реализуй migrations/models для:
- Project;
- Document;
- DocumentRevision;
- Sheet;
- RecognitionArtifact;
- Region;
- Job.

Требования:
- timestamps timezone-aware;
- FK + indexes на основные lookups;
- project boundary в каждом query;
- source artifacts immutable;
- JSONB только там, где schema действительно меняется/legacy payload;
- raw binary никогда не в DB;
- Regions не путать с будущими Measurements.

Не создавай сейчас tables для quantities/estimates/material libraries.

## Storage abstraction

Сделай интерфейс `ObjectStorage` и S3/MinIO implementation:
- streaming upload;
- `put_stream`/multipart strategy для больших файлов;
- stat/head;
- delete только через явную service method;
- presigned GET URL;
- deterministic/safe object keys using UUID, not raw filename as path;
- retain original filename as metadata, Unicode-safe.

Добавь SHA-256 calculation streaming during upload or immediately after in a bounded-memory way.

## API v1

Минимум:

```text
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
GET    /api/v1/projects/{project_id}/documents
GET    /api/v1/documents/{document_id}
GET    /api/v1/documents/{document_id}/revisions
GET    /api/v1/revisions/{revision_id}/sheets
GET    /api/v1/sheets/{sheet_id}/regions
GET    /api/v1/revisions/{revision_id}/content-url
GET    /api/v1/jobs/{job_id}
```

Upload/import endpoint можно зарезервировать, но полную логику реализуем Prompt 05/06.

Пагинация обязательна для list endpoints. Не возвращай 50k Regions без pagination/filtering; sheet regions endpoint может иметь `type`, `status`, `page_size` filters.

## Job state

Реализуй только durable DB record + service transitions with invariants:
`queued -> running -> succeeded|failed|cancelled`.

Не внедряй Celery/Temporal. Импорт на Stage 1 может выполняться через controlled background execution позже, но API/DB state уже должен быть корректным.

## Auth boundary

Если auth уже есть — используй его.
Если auth нет — не строй полноценный OAuth. Введи dev workspace/organization context abstraction так, чтобы позже можно было добавить tenant auth без переписывания каждой таблицы. Явно документируй временный dev mode.

## Tests

- DB model constraints;
- CRUD services;
- object storage interface with local/fake test implementation;
- API happy paths + 404/boundary cases;
- Unicode filenames;
- pagination.

## Acceptance

После Prompt 03 frontend ещё может быть простым. Главное: API/data/storage foundation устойчив, миграции воспроизводимы, binary paths корректны, future quantity domain не вшит в Region.
