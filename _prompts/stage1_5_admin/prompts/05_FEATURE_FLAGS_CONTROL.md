# PROMPT 05 — Feature flags control plane

Текущие feature flags уже существуют через `/api/v1/meta` и `FEATURE_FLAGS`.

Расширь их управляемо, не меняя принцип Stage 1: flag показывает только действительно существующую функцию.

## Цели

- typed flag registry in code;
- global/system override;
- workspace override where explicitly allowed;
- emergency/deployment override support;
- reason/provenance visible;
- audit trail;
- backend is source of truth.

## Preserve existing flags

Минимум:

```text
projects
documents
uploads
legacy_import
viewer
integrations.tenderhub
takeoff.manual
takeoff.ai
models.gateway
reports
bim.import
drawing.compare
```

Не включать Stage 2 flags просто потому что появилась админка.

## OpenFeature-compatible boundary

Не обязательно внедрять внешний flag service. Но application-facing evaluation API желательно оформить provider-neutral, чтобы позже можно было использовать OpenFeature/OFREP или свой provider без переписывания business code.

## Safety

- dangerous/unfinished flags may be marked `admin_editable=false` until readiness gate passed;
- portal should gracefully degrade when flag off;
- frontend visibility is derived from backend flag evaluation;
- no client-provided flag override;
- cache invalidation deterministic.

## UI

Table:

```text
Flag | Effective | Default | System override | Workspace | Readiness | Description | Changed by
```

Actions only where allowed.

## Tests

- precedence;
- non-admin denial;
- unfinished flag cannot be enabled if registry disallows;
- workspace A override does not affect B;
- `/api/v1/meta` reflects effective flags for current context;
- audit events.

STOP.
