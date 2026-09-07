# PROMPT 00 — Master context Stage 1.5

Ты работаешь в существующем QTO Portal после завершённого Stage 1.

## Режим работы

1. Сначала полностью прочитай корневой `CLAUDE.md`.
2. Полностью прочитай все существующие `docs/adr/*` и Stage 1 handoff/known limitations.
3. Не отменяй действующие ADR молча. Если решение необходимо изменить — создай новый ADR с supersedes/superseded-by и объяснением.
4. Не переписывай работающую архитектуру ради эстетики.
5. Не делай QTO/AI функциональность Stage 2.
6. Все числа в отчёте должны быть измерены реальным запуском.
7. Все критические изменения проверяй на живом стенде, а не только на mocks.
8. OpenAPI остаётся единственным контрактом API, TypeScript client генерируется.
9. `Region` остаётся recognition evidence. Не превращать его в measurement/takeoff entity.
10. `DocumentRevision` остаётся immutable.
11. Бинарные файлы остаются в ObjectStorage, не в PostgreSQL.
12. TenderHUB не является источником QTO-количеств/цен данного портала.

## Repository identity gate — ОБЯЗАТЕЛЬНО

Ожидаемая структура QTO Portal по handoff:

```text
apps/api/app/
apps/web/src/
packages/api-client/
docs/adr/
CLAUDE.md
```

Если вместо этого открыт репозиторий вида `apps/rag-api`, `apps/rag-ui`, `apps/mcp-server` или другая структура — STOP.

Не вноси изменений. Выведи:

- абсолютный/относительный root репозитория;
- фактически найденные top-level директории;
- почему это не соответствует QTO Portal;
- какой репозиторий ожидается.

## Цель Stage 1.5

Построить отдельный административный контур (Control Plane) и безопасность платформы до начала тяжёлого QTO.

Целевая логика:

```text
                    Identity Provider (OIDC)
                           |
                  AuthN / session / JWT
                           |
              +------------+-------------+
              |                          |
       QTO User Portal              Admin Console
          apps/web                    apps/admin
              |                          |
              +------------+-------------+
                           |
                      API /api/v1
                           |
                 authorization layer
                           |
       +-------------------+-------------------+
       |                   |                   |
   domain API          /admin API         integrations
       |                   |                   |
   PostgreSQL         settings/audit        TenderHUB
       |
  ObjectStorage / workers
```

## Ключевая идея

Admin Console — не “скрытая страница” и не CMS-конструктор. Это отдельная поверхность управления платформой. Секретность URL не является защитой. Все административные API требуют серверной авторизации.

## Роли — базовая модель

Не обязательно хранить их как hardcoded forever, но Stage 1.5 должен поддержать минимум:

- `platform_admin` — управление всей инсталляцией;
- `workspace_admin` — управление своим workspace и его пользователями/настройками;
- `engineer` — рабочие действия с проектами;
- `reviewer` — просмотр/проверка будущих результатов;
- `viewer` — чтение;
- `service` — machine-to-machine identity, если реально понадобится.

Backend проверяет permission на каждом запросе. Frontend visibility — только UX, не security boundary.

## Настройки должны быть типизированными

Не создавай бесконтрольную таблицу `settings(key,value)` без registry/validation.

Нужно разделить:

1. deploy-time config — окружение/инфраструктура;
2. runtime product settings — типизированный registry + overrides;
3. feature flags — отдельная система;
4. secrets — отдельный secret channel/reference; raw secret не возвращается UI;
5. user preferences — не смешивать с system settings.

## Scope настроек

Подготовить возможность уровней:

```text
SYSTEM
  ↓ override
WORKSPACE
  ↓ в будущем при необходимости
PROJECT
```

Но на Stage 1.5 не надо давать каждому параметру все уровни. Scope разрешается definition-ом настройки.

## TenderHUB

Для проекта `source=tenderhub`:

- `external_id` является канонической связью с тендером;
- номер/название/заказчик считаются синхронизируемыми внешними атрибутами;
- нельзя тихо отвязать/перепривязать обычным редактированием Project;
- rebind/unlink — отдельная privileged admin operation;
- действие должно попадать в audit log;
- никакие чужие BOQ/цены не выдавать за QTO портала.

## Работа после выполнения этого промта

Этот промт только фиксирует контекст и проводит identity gate.

Не реализуй ничего.

Выведи кратко:

- подтверждён ли нужный репозиторий;
- какие Stage 1 ADR/ограничения прочитаны;
- какие существующие точки расширения будут использованы;
- потенциальные конфликты Stage 1.5 с текущей архитектурой.

STOP. Не переходи к Prompt 01.
