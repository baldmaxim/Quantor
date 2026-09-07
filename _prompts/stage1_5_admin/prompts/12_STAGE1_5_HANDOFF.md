# PROMPT 12 — Handoff to Stage 2

Не добавляй новую функциональность.

Собери точный handoff после Stage 1.5.

Создай:

```text
docs/stage1_5/HANDOFF_TO_STAGE2.md
```

Включи:

1. что реально работает и проверено;
2. auth flow;
3. roles/permissions matrix;
4. workspace isolation model;
5. Admin Console routes;
6. settings registry and override precedence;
7. feature flag evaluation/override model;
8. TenderHUB canonical binding rules;
9. model provider management contracts;
10. job worker architecture;
11. audit log model;
12. diagnostics endpoints;
13. migrations;
14. API changes;
15. test counts by suite only from actual runs;
16. performance measurements only from actual runs;
17. unresolved issues/blockers;
18. exact extension points Stage 2 must use;
19. ADR list and statuses.

## Stage 2 readiness gate

В конце выдай PASS/FAIL отдельно для:

```text
AUTH
WORKSPACE_ISOLATION
ADMIN_CONTROL_PLANE
SETTINGS
FEATURE_FLAGS
TENDERHUB_GOVERNANCE
JOB_EXECUTION
AUDIT
DIAGNOSTICS
LIVE_VIEWER_REGRESSION
```

Если любой critical gate FAIL — Stage 2 не объявлять ready.

Не включать `takeoff.manual`, `takeoff.ai`, `models.gateway` только ради handoff.

STOP.
