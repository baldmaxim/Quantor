# PROMPT 06 — TenderHUB admin governance

Используй существующую интеграцию TenderHUB, не переписывай её без необходимости.

## Admin page

Показывать:

- integration enabled/configured;
- last successful connectivity check;
- last error class/message safe for admin;
- endpoint/base target only if non-secret and safe;
- credential status `configured / missing / invalid`, raw key never;
- sync statistics only if реально измеряются;
- explicit “Test connection” server action.

## Canonical binding

Для `Project.source=tenderhub`:

```text
provider = tenderhub
external_id = stable tender id
external_ref = human-readable reference
```

Уникальность связи определить и закрепить migration/index: как минимум workspace + source + external_id.

## Synced fields

Номер/название/заказчик должны иметь provenance `TenderHUB` и обновляться предсказуемо.

Если портал допускает локальный display alias — хранить его отдельно, не перетирать canonical name молча.

## Rebind/unlink

Отдельные admin endpoints/actions:

- preview operation;
- conflict detection;
- explicit confirmation;
- full audit event old→new;
- no cascading delete of QTO project data.

Обычный Project update endpoint не должен менять `source/external_id`.

## Failure isolation

TenderHUB outage не должен ломать просмотр уже импортированных документов/проектов.

## Tests

- duplicate external tender binding rejected or idempotently resolves according to ADR;
- normal user cannot rebind;
- admin rebind audited;
- secret never in API/logs;
- TenderHUB outage yields integration-specific code;
- existing local project remains available.

STOP.
