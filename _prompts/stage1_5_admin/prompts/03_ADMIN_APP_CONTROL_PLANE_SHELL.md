# PROMPT 03 — Separate Admin Console shell

Создай отдельное административное frontend-приложение/поверхность управления.

## Предпочтительная граница

Если текущий monorepo позволяет без ломки:

```text
apps/admin/
```

с отдельным build/runtime bundle и возможностью размещения на:

```text
admin.<domain>
```

или отдельном internal host.

Можно переиспользовать `packages/api-client` и вынесенный shared UI package. Не импортировать code из user portal через хрупкие relative paths.

Если реальная структура делает отдельное приложение неоправданно дорогим — зафиксируй альтернативу ADR до реализации. Но не делай security через “неизвестный /admin URL”.

## Navigation Stage 1.5

Сделай shell и пустые/диагностические страницы:

```text
Dashboard
Workspaces
Users & Access
Settings
Feature Flags
Integrations
Model Providers
Jobs & Workers
Storage / System Health
Audit Log
```

`Model Providers` пока только management shell/contracts, никакого model runtime/QTO.

## Dashboard

Показывать только подтверждённые backend-данные:

- API health;
- DB migration state;
- ObjectStorage health;
- worker/job executor health;
- TenderHUB configured/healthy state;
- active feature flags count;
- failed/retrying jobs;
- build/version metadata.

Не подменять отсутствующие метрики фиктивными числами.

## UX

- desktop-first professional control plane;
- responsive, но не жертвовать таблицами администрирования;
- clear destructive confirmation;
- loading/empty/error states;
- no raw secrets;
- no debug stack traces in UI;
- light/dark theme compatible with portal;
- admin pages should not preload PDF.js/viewer code.

## Access

Вход в admin app разрешён только `platform_admin`; страницы workspace-level management могут позже расшириться на `workspace_admin`, но API permissions уже должны это позволять.

Для unauthorized — не рендерить shell и не отдавать privileged data.

## Tests

Playwright минимум:

- non-admin blocked;
- platform_admin shell loads;
- no portal viewer bundle on admin dashboard;
- navigation works;
- error states;
- mobile does not expose impossible actions accidentally.

STOP.
