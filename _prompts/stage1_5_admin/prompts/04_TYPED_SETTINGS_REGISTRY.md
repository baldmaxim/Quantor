# PROMPT 04 — Typed runtime settings

Реализуй управляемые настройки сайта/портала без превращения в CMS.

## Не делать

Не делай arbitrary `key -> JSON` editor, который позволяет администратору сломать любое поведение.

## SettingDefinition registry

Definitions принадлежат коду и version control. Для каждой настройки минимум:

```text
key
title
description
type
category
default_value
allowed_scopes
validation
is_secret=false
restart_required
requires_permission
```

Runtime DB хранит только validated override + provenance.

## Scope precedence

Зафиксировать и протестировать. Рекомендуемая модель:

```text
code default
  < system DB override
  < workspace DB override
  < explicit deployment emergency override (если предусмотрен)
```

Не добавлять project scope, если нет реальной Stage 1.5 настройки, требующей его; подготовить enum/contract к расширению.

## Категории Stage 1.5

Только реальные общесистемные настройки, например:

- default locale;
- default units/measurement system (пока не QTO algorithms);
- upload limits, если они runtime-editable и безопасны;
- allowed upload types, если server validation поддерживает;
- default UI preferences that are truly system/workspace defaults;
- retention/display settings, если реально реализованы.

Не переносить deployment infrastructure settings (DB URL, S3 credentials, OIDC secret) в обычную settings table.

## API

Admin-only endpoints under `/api/v1/admin/settings` (или текущий versioned convention):

- list definitions with resolved value/provenance;
- update allowed override;
- delete override → fallback;
- validation errors machine-readable;
- no secret values.

Каждое изменение → audit event.

## UI

Settings page строится из registry metadata, но не является generic JSON form.

Показывать:

- effective value;
- source: default/system/workspace/deployment;
- edited by / time;
- restart required indicator;
- reset to inherited/default.

## Tests

- invalid type rejected;
- scope not permitted rejected;
- unknown key rejected;
- normal user rejected;
- override precedence exact;
- delete override returns inherited;
- audit recorded;
- secret-like deployment config never leaks.

STOP.
