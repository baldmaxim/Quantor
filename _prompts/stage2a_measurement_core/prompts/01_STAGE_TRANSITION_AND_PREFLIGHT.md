# PROMPT 01 — Stage transition + preflight fixes

Цель: перед QTO убрать известные долги границы Stage 1.5 и официально переключить проект на Stage 2A.

## 1. Сначала докажи текущее состояние

Запусти доступные:

```bash
pnpm lint
pnpm typecheck
pnpm api-client:check
pnpm test
```

Если инфраструктура доступна — полный тест на PostgreSQL/PostGIS + MinIO. Если нет — не писать
«PASS»: явно перечислить skipped/blocked и команды для живого стенда.

Проверь наличие regression-теста viewer, который гарантирует, что две задачи pdf.js render
не живут одновременно на одном canvas. Если фикса в коде есть, а теста нет — добавить тест.

Синхронизируй handoff Stage 1.5 с фактическим live viewer status, если он устарел.

## 2. Исправь Job scope до новых JobType

Текущий `project_id=NULL` не должен автоматически означать «видно любому workspace».

Спроектируй явный scope. Предпочтительная семантика:

```text
workspace job: workspace_id NOT NULL, project_id optional
project job:   workspace_id NOT NULL, project_id NOT NULL
system job:    workspace_id NULL, project_id NULL, доступ только system.admin
```

Можно выбрать эквивалентную схему, но обязательно:

- migration с безопасным backfill существующих project jobs;
- обычный `/jobs/{id}` никогда не выдаёт system job workspace-пользователю;
- admin API различает system/workspace scope явно;
- worker claim не ломается;
- regression tests cross-workspace/system;
- публичный `JobRead` не ломать без необходимости; если контракт надо расширить — OpenAPI regenerate.

## 3. Platform admin bootstrap/system context

Воспроизведи кейс `platform_admin` без workspace membership. System-level admin endpoints должны
работать без случайного tenant context. Workspace-scoped operations должны требовать явный
`X-Workspace-Id` или другой уже принятый механизм.

Не назначай admin молча в первый попавшийся workspace.

Добавь regression tests только после воспроизведения текущего поведения.

## 4. Уточни ADR-0004

Не переписывай Canvas2D. Выпусти новый ADR или amend/superseding ADR:

- Stage 1/2A recognition + measurement overlays могут быть Canvas2D;
- WebGL — решение после измеренного threshold;
- base PDF render и overlays остаются независимыми;
- spatial index/LOD допускаются позже.

## 5. Обнови корневой CLAUDE.md

Он больше не должен говорить «работа по stage1» и запрещать scale/QTO полностью.

Разреши **только Stage 2A**:

- canonical PDF geometry;
- manual scale calibration;
- manual Count/Line/Polyline/Polygon;
- deterministic count/length/area;
- benchmark.

Продолжай запрещать:

- AI/CV/VLM inference и Auto Measure/Auto Count;
- автоматическое определение масштаба;
- BIM parsing;
- ProjectGraph;
- semantic construction rules;
- volume/mass/cost;
- production ВОР;
- revision compare.

Обнови ссылки документации на `_prompts/stage2a_measurement_core/`.

## Acceptance этого промта

- migrations/tests green в доступной среде;
- Stage 1.5 functionality не сломана;
- `CLAUDE.md` больше не конфликтует со Stage 2A;
- system job tenant leak закрыт;
- platform admin system context покрыт тестом;
- Canvas2D/ADR согласованы.

Сделай отчёт с реальными test counts. STOP.
