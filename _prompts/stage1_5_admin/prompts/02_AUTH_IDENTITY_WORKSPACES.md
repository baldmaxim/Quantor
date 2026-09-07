# PROMPT 02 — Authentication, identity, workspaces

Реализуй foundation аутентификации и tenant/workspace isolation.

## Архитектурное требование

Использовать стандарт OIDC/OAuth2, не привязывая domain model к конкретному vendor SDK.

Для self-hosted/dev допустимо подготовить documented integration с authentik/Keycloak или другим OIDC IdP, но application contract должен быть OIDC-compatible.

Не писать собственное хранение паролей.

## Реализовать domain entities

Подбери точные имена под текущий стиль проекта. Смысл:

```text
UserIdentity
Workspace
WorkspaceMembership
Role / Permission mapping
```

Если `workspace_id` уже есть во всех Project queries — мигрировать фиксированный workspace в реальную сущность без потери данных.

## Permissions

Сделай permission-first checks. Минимальные permission keys:

```text
system.admin
workspace.read
workspace.manage
workspace.members.manage
project.read
project.create
project.update
project.delete
document.read
document.upload
integration.read
integration.manage
feature_flags.read
feature_flags.manage
settings.read
settings.manage
jobs.read
jobs.manage
models.read
models.manage
audit.read
```

Точные роли могут агрегировать permissions.

## Backend

- deny-by-default для защищённых API;
- auth context формируется на сервере;
- workspace/user/role нельзя доверять из request body;
- object-level access check на каждый Project/Document/Revision/Sheet/Region/Job;
- presigned content URL выдаётся только после authorization;
- platform_admin может переключать workspace только явной админ-операцией;
- безопасная обработка 401 vs 403.

## Frontend

- login/logout/session state;
- portal never flashes unauthorized project data;
- account menu;
- workspace selector только если membership >1;
- обычному пользователю не показывать Admin Console link без права;
- UI permissions не заменяют API checks.

## Admin MFA

Сам портал не реализует MFA. Документировать требование: IdP policy должна требовать MFA для `platform_admin` и желательно `workspace_admin`.

## Testing

Обязательные matrix tests:

- no token/session → 401;
- authenticated user, wrong workspace → 403/404 согласно выбранной policy;
- viewer cannot mutate;
- engineer cannot system-admin;
- workspace_admin cannot access another workspace;
- platform_admin explicit access works;
- guessed Project/Document/Revision/Sheet UUID cannot escape workspace;
- content-url obeys same boundary.

Прогони реальные PostgreSQL API tests.

Обнови OpenAPI/client.

STOP.
