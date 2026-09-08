# PROMPT 16 — Final audit Stage 2A + handoff to Stage 2B

Проведи независимую приёмку, не доверяя предыдущим отчётам без кода/прогонов.

## Сверь 15 gates

Используй `reference/STAGE2A_ACCEPTANCE_GATES.md`. Для каждого:

```text
PASS / FAIL / BLOCKED
Evidence
Command/test/document
```

Нельзя превращать BLOCKED в PASS.

## Full verification

В доступной live-среде:

```bash
pnpm lint
pnpm typecheck
pnpm api-client:check
pnpm test
pnpm build
pnpm benchmark:measurement   # фактическое имя команды из Prompt 13
```

Проверь migrations up/down/check и live worker if available.

## Architecture audit

Докажи:

- `units_per_normalized` удалён/superseded из рабочего контракта;
- raster width не участвует в physical QTO;
- rotation не применяется дважды;
- multiple scale data model безопасна;
- Measurement отдельна от Region;
- quantities deterministic/versioned;
- no AI/network model invocation exists;
- no cross-revision magic aggregation;
- no tenant leaks;
- Canvas/WebGL decision основано на benchmark.

## Feature gate

Только если все blocking gates PASS:

- перевести `takeoff.manual` в реально готовую возможность;
- включение по умолчанию решить согласно существующей feature-flag policy;
- не включать `takeoff.ai`;
- обновить `/meta` и UI readiness.

Если есть FAIL/BLOCKED — оставить `takeoff.manual` выключенным и перечислить точный остаток.

## Handoff

Создай `docs/stage2a/HANDOFF_TO_STAGE2B.md`:

- что реально работает;
- schema/migrations;
- endpoints;
- permissions;
- keyboard/UX;
- benchmark numbers;
- live acceptance;
- known limitations;
- точка расширения для AI;
- запреты Stage 2B не обходить.

### Stage 2B пока только направление

Следующий этап после отдельного пакета владельца:

```text
Auto Count only
→ Model Gateway runtime
→ local/API vision models
→ detector/VLM comparison
→ AI creates ordinary MeasurementSource.AI
→ verifier/human correction
```

Не начинай Stage 2B сейчас.

STOP.
