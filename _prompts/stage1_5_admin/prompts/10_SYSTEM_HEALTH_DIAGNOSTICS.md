# PROMPT 10 — System health / diagnostics

Сделай Admin Console полезным эксплуатационным инструментом, а не только CRUD настроек.

## Components

Показывать фактическое состояние:

```text
Web build/version
API build/version
PostgreSQL connectivity + migration head
ObjectStorage connectivity
Job worker heartbeat
TenderHUB status
OIDC discovery/issuer status
Feature flag provider status
Model provider health summaries (если configured)
```

## Principles

- diagnostics endpoint admin-only where data sensitive;
- public `/health/live` remains minimal;
- `/health/ready` returns machine-oriented health, no secrets;
- admin diagnostics can give actionable remediation but no credentials;
- timeout every dependency probe;
- one dead optional integration must not hang whole page;
- parallel bounded probes;
- last-known status distinguished from live probe.

## UI

Status categories:

```text
healthy
degraded
unavailable
not_configured
unknown
```

Timestamp last check and source of status.

Add explicit refresh, do not poll aggressively by default.

## Tests

Simulate DB/storage/TenderHUB/worker failures independently and verify page remains usable.

STOP.
