# Control Plane — целевая архитектура

## Почему не “скрытая страница”

Скрытый URL — UX-деталь, не механизм безопасности. Административные действия должны быть защищены identity + server-side authorization.

## Почему отдельное приложение

Рекомендуемая целевая граница:

```text
apps/web    -> пользовательский QTO portal
apps/admin  -> platform control plane
apps/api    -> единый versioned backend API
```

Преимущества:

- admin JS не попадает в обычный bundle;
- можно отдельный host/subdomain/CSP/network policy;
- проще ограничить доступ корпоративной сетью/VPN позже;
- независимый deployment при необходимости;
- общий API client/design tokens можно переиспользовать через packages.

## Что управляется из Admin Console

### Identity & access
Users, memberships, roles, workspace boundaries.

### Runtime settings
Только типизированные product settings.

### Feature flags
Controlled rollout/visibility; readiness still belongs to code/test gate.

### Integrations
TenderHUB health, binding governance, safe connection diagnostics.

### Model provider registry
Local/API model endpoints/capabilities/privacy classification, но Stage 1.5 без inference.

### Jobs & operations
Background job visibility, retries where safe, worker health.

### System health
DB/storage/migrations/workers/integrations.

### Audit
Who changed what and when.

## Что НЕ управляется как обычная setting

- DB password/URL;
- S3 secret/access key;
- OIDC client secret;
- raw model API token;
- arbitrary Python/JS expressions;
- arbitrary SQL;
- arbitrary frontend HTML/CSS;
- QTO calculation rules Stage 2+.

## Recommended role vs permission principle

Business code checks permissions, not role names. Roles are convenient permission bundles.

## TenderHUB provenance

```text
Project.source = tenderhub
Project.external_id = canonical remote tender id
Project.external_ref = user-facing external number/reference
synced name/customer = external provenance
local alias = optional separate field
```

Changing the binding is an administrative domain event, not ordinary Project editing.
