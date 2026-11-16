# T01. API обмена с TENDER

Прочитай: `docs/adr/0051-quantor-kak-repozitorij-tendernyh-raschyotov.md`, `docs/tender-exchange/01-format.md` (поля — только оттуда), `CLAUDE.md` проекта.

## 1. Права и флаги

- `app/auth/permissions.py`: `TENDER_CALC_READ = "tender.calc.read"` (в `_VIEWER`), `TENDER_CALC_UPLOAD =
  "tender.calc.upload"` (в `_ENGINEER`), `TENDER_BASE_RELEASE = "tender.base.release"` и
  `TENDER_CALC_WITHDRAW = "tender.calc.withdraw"` (в `_WORKSPACE_ADMIN`). Координатор = администратор пространства.
- `app/core/features.py`: `_pilot("tender.exchange", "Обмен расчётами с TENDER", …)` и
  `_pilot("cad.mep_engine", "Трассы ВИС движка", "…выключено — построение и показ трасс ВИС движка закрыты;
  расчёты систем приходят из TENDER")`.
- `cad.mep_engine` выключен → `POST …/mep-routes` и `…/recompute` трасс отвечают 409
  `CAD_MEP_ENGINE_DISABLED` (новый `ErrorCode`). Чтение старых трасс не закрывать (их скрывает интерфейс).
  Существующие тесты трасс — включить флаг в фикстуре, не ослабляя проверок.

## 2. Персональные токены

- Модель `app/models/api_token.py`, таблица `api_tokens`: `id`, `user_id`, `workspace_id`, `name` (≤100),
  `prefix` (первые 12 знаков для показа), `token_hash` (sha256 hex, unique), `scopes` (JSONB, v1 — `["tender"]`),
  `created_at`, `last_used_at`, `expires_at` (null — бессрочно), `revoked_at`.
- Токен `qtk_` + 40 знаков `secrets.token_urlsafe`; в ответе создания — один раз, в базе — только хеш.
- `app/auth/resolver.py`: Bearer, начинающийся с `qtk_`, проверяется в **любом** `AUTH_MODE` (кроме `dev`):
  хеш найден, не отозван, не истёк, пользователь может входить → `CredentialKind.API_TOKEN` (новое значение),
  пространство — из токена (заголовок `X-Workspace-Id`, если есть, обязан совпасть, иначе 403). Права =
  `permissions_for(role) ∩ {WORKSPACE_READ, PROJECT_READ, DOCUMENT_READ, TENDER_CALC_READ, TENDER_CALC_UPLOAD}`.
  CSRF для токена не нужен. `last_used_at` — не чаще раза в минуту. Остальные Bearer — как раньше (oidc).
- Эндпоинты (только сеанс cookie, токеном нельзя): `GET /me/api-tokens`, `POST /me/api-tokens`
  `{name, expires_in_days?: 1..365}`, `DELETE /me/api-tokens/{id}` (отзыв). Под флагом `tender.exchange`.

## 3. Таблицы (миграция `0043_tender_exchange`, down — `0042_sheet_window_levels`, файл `20261116_0043_tender_exchange.py`)

- `tender_base_releases`: `id`, `workspace_id`, `project_id`, `number` (по проекту с 1, unique с project_id),
  `comment`, `released_by`, `released_at`, `include_dxf`, `views` (JSONB: `key, dir, revision_id, page_index,
  view, job_id, dxf_sha256, document_title, label, corps, section, floors`), `package_key`, `package_sha256`,
  `manifest_sha256`, `size_bytes`, `revoked_at`, `revoked_by`.
- `tender_calcs`: `id`, `workspace_id`, `project_id`, `discipline`, `system`, `title`, `created_at`,
  `created_by`; unique `(project_id, discipline, system, title)`.
- `tender_calc_versions`: `id`, `calc_id`, `number` (unique с calc_id), `base_release_id`, `label`, `message`,
  `author`, `uploaded_by`, `uploaded_at`, `producer` JSONB, `fit` JSONB, `package_key`, `package_sha256`
  (unique с calc_id), `views` JSONB (`view_key, revision_id, page_index, view, floors, dxf_sha256, object_key,
  polylines, elements`), `quantities` JSONB (строки ≤ 5000), `questions` JSONB, `warnings` JSONB, `status`
  (`active`|`superseded`|`withdrawn`), `withdrawn_by`, `withdrawn_at`.
- Ключи хранилища: `projects/{project_id}/tender/base/{release_id}.zip`,
  `projects/{project_id}/tender/calcs/{version_id}/package.zip` и `…/views/{revision_id}_{page}_{view}.json`.

## 4. Выпуск базы (`app/services/tender_base.py`)

- Кандидаты — этажи `build_building3d` проекта (тот же список, что «Здание»): ключ вида, документ, подпись,
  корпус, секция, отметки, `offset_mm`, `alignment`. `cad_building3d.py` **не править** (его правит соседняя
  сессия) — только импорт.
- Состав файлов вида — по формату: `view.json` (кадр — как `CadFrameRead` вида; уровни и размещение — из этажа
  здания), `axes.json` (`axes_in_mm`, только принятые), `zones.json` (зоны страницы, попавшие в вид; выясни, в
  каких единицах `cad_zones.points`, и переведи в мм кадра вида тем же способом, что интерфейс отбирает зоны
  вида), `constructions.json` (из `walls.json` последнего успешного `cad_walls` вида + принятые свойства:
  материал, толщина номинала), `risers.json` (`cad_sheet_risers`, если есть), `plan.dxf` (DXF вида из
  артефактов конвертации, только при `include_dxf`). `building.json`, `manifest.json` с sha256 файлов.
- Сборка ZIP — в `asyncio.to_thread`, потоково в хранилище; не больше 400 видов за выпуск.
- `floors` вида: подпись этажа плана (`label`); типового «на N этажей» данных нет — список из одной подписи.

## 5. Приём расчёта (`app/services/tender_calc_import.py`)

Проверки — раздел «Проверки портала» формата, все сразу (ответ 422 — список нарушений с путём файла):
ZIP безопасен (лимиты из формата; переиспользуй защиту из `services/cad_vor_import.py`/импорта legacy),
схемы (Pydantic-контракты `app/contracts/tender_exchange.py`, `extra="forbid"`), sha256 `files`,
проект, выпуск базы не отозван, виды есть в выпуске, запрет цен (рекурсивно ключи и строковые значения),
`fit`. Коды ошибок: `TENDER_PACKAGE_INVALID`, `TENDER_PRICE_FORBIDDEN`, `TENDER_BASE_UNKNOWN`,
`TENDER_VIEW_UNKNOWN`, `TENDER_FIT_TOO_LARGE`, `TENDER_PROJECT_MISMATCH`.
Предупреждения (в `warnings` версии): база устарела (текущий `dxf_sha256` вида ≠ выпуска), `fit > 100 мм`,
`basis = assumption` без вопроса.
Репозиторий ищется/создаётся по `(project, discipline, system, title)`; тот же `package_sha256` → 200 и
существующая версия; иначе новая версия `active`, прежняя активная → `superseded`.

## 6. Эндпоинты (`app/api/v1/tender_exchange.py`, защищённый роутер, `require_feature("tender.exchange")`)

| Метод и путь (`/projects/{p}/tender/…`) | Право |
|---|---|
| `GET base/candidates` | `TENDER_BASE_RELEASE` |
| `POST base/releases` `{view_keys?: list, include_dxf: false, comment}` → 201 | `TENDER_BASE_RELEASE` |
| `GET base/releases`, `GET base/releases/{id}` | `TENDER_CALC_READ` |
| `GET base/releases/{id}/download` (StreamingResponse, `attachment`) | `TENDER_CALC_READ` |
| `POST base/releases/{id}/revoke` | `TENDER_BASE_RELEASE` |
| `POST calcs/upload` (multipart `file`) → 201 / 200 | `TENDER_CALC_UPLOAD` |
| `GET calcs` — репозитории + последняя активная версия | `TENDER_CALC_READ` |
| `GET calcs/{calc_id}/versions` | `TENDER_CALC_READ` |
| `GET calc-versions/{id}` — манифест, объёмы, вопросы, виды (с `base_stale`), предупреждения, `diff` с прошлой версией по `code` (`qty_prev`, `qty`, `delta`, `status`: added/removed/changed/same) | `TENDER_CALC_READ` |
| `GET calc-versions/{id}/views/{revision_id}/{page_index}/{view}` — `floors`, `polylines`, `elements`, `base_stale` | `TENDER_CALC_READ` |
| `GET calc-versions/{id}/package` | `TENDER_CALC_READ` |
| `POST calc-versions/{id}/withdraw` | `TENDER_CALC_WITHDRAW` |
| `GET view-layers?revision_id&page_index&view` — активные версии с этим видом: `version_id, calc_id, discipline, system, title, number, label, polylines, elements, base_stale` | `TENDER_CALC_READ` |
| `GET building-layers` — активные версии и их `view_keys` | `TENDER_CALC_READ` |

Аудит (как у других действий): выпуск, отзыв выпуска, загрузка, отзыв версии, создание и отзыв токена.

## 7. Схемы и проверка

- `app/tender_schemas_export.py`: JSON Schema всех файлов пакетов из контрактов →
  `docs/tender-exchange/schemas/*.schema.json` (запуск `python -m app.tender_schemas_export`).
- Тесты `tests/test_tender_exchange.py`, `tests/test_api_tokens.py`: токен (создание, вход, область —
  запрет чужих прав, отзыв, истечение, токен не создаёт токены), загрузка (успех, повтор, новая версия и
  superseded, цена → 422, traversal → 422, чужой вид, fit, устаревшая база), diff, withdraw, выпуск базы на
  синтетике (виды, зоны в мм вида, sha256 манифеста), 409 трасс движка при выключенном `cad.mep_engine`.
- Потом: `pnpm api-client:generate` (на Linux клиент генерировать вручную — см. память), ruff, mypy, pytest
  затронутого.
