# PROMPT 01 — Audit before changes

Проведи read-only аудит текущего QTO Portal для Stage 1.5.

## Проверить

### Backend

- framework и middleware chain;
- как сейчас формируется `workspace_id`;
- все endpoints и места, где workspace фильтруется;
- CORS, cookies, headers, presigned URLs;
- feature flags implementation;
- config/secrets loading;
- TenderHUB integration and failure model;
- OpenAPI generation;
- Job model/job runner;
- logging/error model;
- migrations and transaction patterns.

### Frontend

- Next.js/app router фактическая версия/структура (не предполагай — проверь);
- current portal route groups;
- API client/auth fetch wrapper;
- PWA/service worker impact;
- design system/components/theme;
- where a separate admin app can share components without sharing privileged bundle.

### Tests / CI

- backend auth/security tests currently absent/present;
- API contract drift checks;
- Playwright setup;
- real PostgreSQL/MinIO test harness;
- deploy/start scripts.

## Threat model minimum

Опиши минимум:

- unauthenticated access;
- horizontal workspace access;
- vertical privilege escalation;
- guessed UUID/IDOR;
- compromised admin session;
- leaked TenderHUB/model API secret;
- CSRF/session misuse;
- admin API accidentally exposed to user role;
- stale cached authorization;
- PWA/service-worker caching privileged responses;
- presigned object URL leakage;
- audit log tampering.

## Deliverables

Создай:

- `docs/stage1_5/security-architecture-audit.md`
- ADR: authentication/authorization boundary (номер выбери следующим свободным)
- ADR: admin control-plane deployment boundary

Пока не изменяй runtime-код.

В конце дай exact implementation plan по файлам и migrations.

STOP.
