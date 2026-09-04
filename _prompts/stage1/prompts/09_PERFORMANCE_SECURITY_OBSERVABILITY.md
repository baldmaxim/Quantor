# PROMPT 09 — Performance, security, observability hardening

Цель: убрать типичные причины «лагов и глюков» до Stage 2.

## Performance audit

Профилируй, не угадывай.

Frontend:
- inspect bundle/chunks;
- pdf.js/Pixi only lazy in workspace;
- no accidental server/client duplication;
- no all-sheets eager thumbnails;
- virtualize long page/region lists;
- memoize only where measured/useful;
- avoid giant Zustand subscriptions;
- cancel stale network/render tasks;
- cache with explicit bounds;
- prevent duplicate fetches via TanStack Query keys.

Backend:
- uploads bounded-memory;
- ZIP processing bounded and safe;
- pagination/indexes verified;
- no N+1 for project/doc/sheet lists;
- presigned URLs rather than proxying binaries where possible;
- DB transactions scoped;
- timeouts configured;
- object storage retries bounded.

## Practical performance acceptance fixture

Using the user's real package if locally available:
- upload ~50 MB ZIP;
- import 77 pages/383 regions;
- open first sheet without eager rendering remaining 76 pages;
- switch pages repeatedly;
- toggle 383-region overlay;
- UI remains interactive.

Do not promise FPS without measurement. Capture actual trace/profiler notes and list bottlenecks.

## Security

Threat-model Stage 1:
- ZIP slip/bomb;
- malicious filenames;
- MIME mismatch;
- malicious Markdown/HTML;
- SSRF via crop URL;
- object storage path traversal;
- presigned URL lifetime;
- cross-project IDOR;
- oversize uploads;
- error leakage;
- CORS/CSRF based on actual auth mode;
- dependency vulnerabilities.

Implement practical mitigations and tests. Do not fetch legacy crop URL automatically.

`results.html` must never be rendered unsandboxed as trusted HTML.

## Observability

Add:
- request ID/correlation ID;
- structured backend logs;
- job ID in logs;
- duration and error code for import;
- frontend error boundary;
- simple client logging hook;
- health/readiness includes DB/storage checks with safe output;
- optional OpenTelemetry integration boundary, but do not add a giant stack unless already used.

## Error taxonomy

Create stable safe codes, e.g.:
- `UPLOAD_TOO_LARGE`;
- `UNSUPPORTED_FILE_TYPE`;
- `ARCHIVE_UNSAFE_PATH`;
- `ARCHIVE_LIMIT_EXCEEDED`;
- `LEGACY_SCHEMA_UNSUPPORTED`;
- `LEGACY_BLOCKS_INVALID`;
- `PDF_RENDER_FAILED`;
- `STORAGE_UNAVAILABLE`.

UI maps these to Russian user-facing messages.

## Tests/build

Run full:
- lint;
- typecheck;
- unit/integration;
- frontend build;
- backend tests;
- Playwright smoke;
- migration from clean DB.

Fix root cause, not warnings by disabling rules.

## Acceptance

Produce `docs/stage1/performance-security-report.md` with:
- what was measured;
- current limits/config;
- known bottlenecks;
- security controls;
- what is deferred to Stage 2/production deployment.
