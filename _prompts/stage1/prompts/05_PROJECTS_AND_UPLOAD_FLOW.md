# PROMPT 05 — Projects dashboard + upload flow

Цель: сделать первый рабочий user journey:
`Projects -> Create project -> upload -> status -> project overview`.

Не реализовывай распознавание. Upload — это доставка immutable artifacts в storage и создание job/status.

## Projects page

Реализуй:
- list/grid with pagination or incremental loading;
- search by name;
- sort recent/name;
- empty state;
- status badges;
- create project action.

## Create Project

Wizard/modal/page — выбери наиболее чистый UX с текущим shell.

Fields:
- project name required;
- drag/drop files;
- supported now:
  - `.zip` recognized package;
  - `.pdf` raw document storage;
- accepted for storage only / future processor:
  - `.rvt`, `.nwd`, `.nwc`, `.ifc`;
- reject unexpected executables/archives types not supported.

UI ясно показывает capability:
- ZIP recognized package: “Импортировать”;
- PDF: “Сохранить, распознавание будет на следующем этапе”;
- RVT/NWD/NWC/IFC: “Сохранить, обработчик пока не подключён”.

## Upload implementation

Требования:
- browser uses multipart/form-data or signed multipart flow, no base64;
- show real upload progress if stack permits; otherwise honest indeterminate state, не fake percent;
- backend streams to object storage with bounded memory;
- filename sanitized for display/path safety but original name preserved;
- MIME sniff/extension validation;
- file size limits configurable;
- SHA-256 stored;
- retry does not create silent duplicate revisions if idempotency key is reused.

API design may be:

```text
POST /projects/{id}/uploads/init
POST /projects/{id}/uploads/complete
```

or a streaming multipart endpoint for Stage 1. Choose the simpler correct implementation for current stack and document migration to direct-to-S3 multipart for very large production uploads.

Do not overengineer direct multipart if it would delay Stage 1, but do not read 500 MB into RAM.

## Processing status

After recognized ZIP upload, create `Job(type=legacy_import)` as queued and trigger importer in Prompt 06. Until then UI can show queued.

For raw PDF/RVT/NWD, create DocumentRevision status `unprocessed`/`processor_unavailable` without pretending recognition exists.

## Project overview

Show:
- documents;
- revision/status;
- type;
- size;
- page count if known;
- import job state;
- “Открыть рабочую область” only when a renderable PDF revision exists.

## Error UX

Safe user-facing codes/messages:
- file too large;
- unsupported type;
- corrupt archive;
- import failed;
- storage unavailable.

Do not surface stack traces or storage credentials.

## Tests

- Russian Unicode filename;
- 0-byte / invalid file;
- duplicate upload idempotency;
- large streaming path uses bounded reads (unit/integration proxy test);
- UI upload states;
- project refresh after completion.

## Acceptance

User can create project and upload a package/document without AI. No viewer internals yet.
