# Target architecture — shell now, QTO later

## Принцип

Портал не должен быть «одним Next.js приложением, внутри которого вызывается AI». UI, хранение документов, viewer, processing jobs, model inference и quantity engine должны быть разделены контрактами.

```text
Browser
  |
  v
Web UI (Next.js/React)
  |
  v
API/BFF (FastAPI)
  |--------------------- PostgreSQL/PostGIS (metadata, geometry later)
  |--------------------- S3-compatible object storage (PDF/ZIP/artifacts)
  |--------------------- Redis/cache/queue boundary (future workers)
  |
  +--> Job Orchestrator boundary ------------------+
                                                    |
       +----------------+----------------+----------+----------+
       |                |                |                     |
       v                v                v                     v
 PDF/Layout future   CV future      Model Gateway future   QTO Engine future
                                                    |
                                           local or remote models
```

## Recommended Stage 1 stack

Use latest stable versions compatible with one another; avoid canary releases.

Frontend:
- Next.js, React, TypeScript strict;
- Tailwind + shadcn/Radix primitives;
- TanStack Query for server state;
- Zustand only for ephemeral viewer/workspace state;
- Zod at UI boundaries;
- pdfjs-dist directly, loaded only in workspace;
- PixiJS/WebGL overlay layer, also lazy loaded;
- Playwright + Vitest/Testing Library.

Backend:
- Python 3.12+;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2 async;
- Alembic;
- PostgreSQL with PostGIS-capable image;
- S3-compatible storage abstraction, MinIO for local dev;
- structured logging;
- pytest.

Repository:
- pnpm workspaces; do not add Turborepo unless it brings clear value to existing repo;
- one root Makefile/justfile/task runner for common commands;
- Docker Compose for local dependencies;
- OpenAPI-generated TS client or a similarly single-source API contract. Do not hand-maintain duplicate DTOs.

## Current Stage 1 runtime

Only these pieces are real:

```text
Project CRUD-lite
Recognized ZIP upload
Safe legacy import
Document/Revision/Sheet/Region metadata
PDF access via object storage / ranged URL
Workspace shell
PDF page rendering
Region debug overlay
Job/status shell
```

Everything else is disabled placeholder or interface.

## Future service boundaries to reserve

### Recognition pipeline
`ingest -> classify sheets -> OCR/layout -> vector extraction -> CV -> normalize -> verify`

### Model Gateway
A provider-neutral service. Expected future adapters:
- local OpenAI-compatible endpoints (vLLM, SGLang, llama.cpp, etc.);
- remote OpenAI-compatible endpoints;
- Anthropic API;
- OpenAI API;
- custom HTTP/VLM endpoints.

Provider metadata should later include capabilities rather than provider names hardcoded into business code: text, vision, structured output, tool calling, context limit, max image size, latency class, price class, concurrency.

### Orchestrator
Cursor/Claude Code are **development tools**, not runtime dependencies. Runtime orchestration must be server-side and durable. In Stage 1 define only a `JobService`/state contract. Do not introduce Temporal/Celery before there is a real workload; leave an ADR explaining upgrade paths.

### Quantity domain
Future entities:
- MeasurementGroup;
- Measurement (count/linear/area/volume);
- QuantityItem;
- Evidence;
- CalculationRuleVersion;
- TakeoffRun;
- VerificationIssue.

Do not create full persistence for them in Stage 1. Define domain contracts/docs only.

## Revit/Navisworks
RVT/NWC/NWD/IFC must be accepted conceptually as document sources or companion files, but Stage 1 should not parse them. Store them immutably and mark processor capability as `not_available` or `pending_adapter`.

## Performance architecture

1. Never put raw binary PDF/ZIP in PostgreSQL.
2. Never proxy a 50–500 MB PDF through React/Next server memory if a presigned/range URL can be used.
3. Browser viewer must load only active pages/tiles; never render all 77 pages full-resolution.
4. Thumbnails must be virtualized/lazy.
5. `pdfjs-dist` and PixiJS must be separate lazy chunks.
6. High-frequency pan/zoom must not cause whole React tree rerenders.
7. Overlay coordinates are canonical in normalized page space; transform only at render time.
8. Future large overlays (>10k primitives/page) use WebGL + spatial index, not thousands of DOM/SVG nodes.
9. Long-running processing is asynchronous and idempotent.
10. Every immutable artifact has SHA-256 and schema version.

## Kreo-like workflow principles, without cloning Kreo

Use as UX inspiration only:
- Projects as top-level unit;
- multi-file project;
- file/page manager;
- quick-access open pages;
- central drawing workspace;
- grouped layers/measurements on the left;
- inspector/context panel on the right;
- manual and AI operations eventually coexist;
- async AI jobs with visible progress;
- live reports later linked to measurements;
- drawing comparison/revisions later.

Do not copy Kreo branding, assets, proprietary text, or pixel-perfect layout.
