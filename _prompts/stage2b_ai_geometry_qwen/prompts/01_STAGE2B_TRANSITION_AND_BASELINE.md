# PROMPT 01 — Закрытие Stage 2A и переход в Stage 2B

Сначала прочитай `docs/stage2b/00-entry-audit.md`.

## 1. Baseline до миграций

На поднятом PostgreSQL/MinIO выполни полный релевантный baseline. Не считать DB test suite
зелёным, если обязательные DB-тесты skipped.

Минимум:

```text
pnpm lint
pnpm typecheck
pnpm api-client:check
pnpm test
pnpm build
pnpm benchmark:measurement
alembic check
```

Зафиксируй exit code и фактические counts. Не фильтруй вывод `grep`-ом как заменой exit code.

## 2. Синхронизация документации

Не переписывай историю. Добавь актуальное closing update в Stage 2A docs:

- PASS 15 / FAIL 0;
- реальные live measurement errors;
- оставшийся viewer performance caveat;
- `takeoff.manual` — решение владельца, а не FAIL;
- старое направление Auto Count заменено отдельным решением Stage 2B AI Geometry Lab.

Обнови корневой `CLAUDE.md`: Stage 2A closed, Stage 2B active. Сохрани все инварианты
Measurement Core.

## 3. Feature flags

`takeoff.manual` теперь реализован:

- default=false;
- `workspace_scoped=true`;
- `admin_editable=true`;
- stage/description должны честно говорить «Stage 2A / pilot ready».

Не включай его автоматически ни системно, ни для неизвестного workspace. Владельцу достаточно
будет включить pilot через Admin.

`takeoff.ai` и `models.gateway` остаются default=false и не становятся user-ready сейчас.

## 4. Новые ADR

Зафиксируй минимум:

- направление Stage 2B: AI Geometry Lab instead of Auto Count first;
- offline experiment != production feature;
- prediction candidate separated from accepted Measurement.

Создай `docs/stage2b/01-transition.md` с baseline table.

STOP. Покажи все изменения и не переходи к Prompt 02.
