# PROMPT 09 — Administrative audit log

Реализуй append-oriented audit trail административных и security-sensitive действий.

## События минимум

- login/session security events if available from app boundary;
- workspace create/update;
- membership/role changes;
- settings overrides;
- feature flag overrides;
- TenderHUB rebind/unlink/test failures where relevant;
- model provider config changes;
- job retry/cancel admin actions;
- credential rotation status action (без secret value).

## Event fields

```text
id
timestamp
actor identity
actor role/context
workspace_id nullable
action
resource_type
resource_id
before_summary safe
after_summary safe
request/correlation id
source ip/user agent only if privacy policy allows
result success/failure
```

Не хранить raw secrets, access tokens, whole uploaded docs, full prompts.

## Tamper resistance

Обычные admin APIs не должны редактировать/delete audit records. Retention/export — отдельная future policy.

## UI

Фильтры:

- date;
- actor;
- workspace;
- action;
- resource;
- result.

Детальная карточка показывает безопасный diff.

## Tests

- audited actions create event;
- failed privileged actions can be logged appropriately;
- secret redaction;
- normal user cannot read audit;
- workspace_admin sees only permitted scope if such access enabled;
- no update/delete endpoint for audit events.

STOP.
