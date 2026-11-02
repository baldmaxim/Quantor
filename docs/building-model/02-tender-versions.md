# M2. Версия тендера: отчёт этапа

Дата: 2026-11-02. Основание: [ADR-0035](../adr/0035-model-zdaniya-i-versiya-tendera.md), план
[00-plan.md](00-plan.md), разделы 3 и 6. Этап не зависит от `plangeom`, модели здания и Revit.

## Что сделано

**База.** Миграция `20261102_0019_tender_versions.py` (ревизия `0019_tender_versions`, после
`0018_local_auth`):

- `tender_versions`: номер (уникален в проекте), подпись, необязательная связь со строкой HUBTender
  (`external_tender_id`, `external_version`), статус `draft` / `frozen`, `manifest_sha256`,
  `frozen_at`, `frozen_by`. Составной внешний ключ `(project_id, workspace_id)` держит согласованность
  пространства. Частичный уникальный индекс: не больше одного черновика на проект. CHECK: замороженная
  версия требует отпечаток и время заморозки;
- `tender_version_documents`: по одной ревизии на документ (уникальность `(версия, документ)`), раздел до
  16 символов, `use_in_model`. Ревизия и документ защищены внешним ключом RESTRICT, состав
  удаляется каскадом только вместе с черновиком;
- триггеры по образцу `calc_rule_versions`: замороженную строку `tender_versions` нельзя менять и
  удалять; состав замороженной версии нельзя добавлять, менять (в том числе «перевесить» на другую версию)
  и удалять. Определения триггеров дублируются в модели (тестовая база строится из метаданных) и в
  миграции; совпадение проверяет `test_schema_matches_migrations`.

**Сервис и API.** Префикс `/api/v1/projects/{project_id}/tender-versions`, весь маршрутизатор закрыт
флагом `tender.versions`. Чтение — `PROJECT_READ`, изменения и заморозка — `PROJECT_UPDATE`; проект
берётся по пространству запроса, чужой — 404. Все изменения пишутся в аудит в одной транзакции с
изменением (шесть новых действий `tender_version_*`).

| Метод и путь | Назначение |
|---|---|
| `GET ""`, `GET /{id}` | список, версия с составом (имя документа, номер ревизии, `source_sha256`) |
| `GET /hub-candidates` | строки HUBTender того же номера (`id`, `version`, `submission_deadline`) |
| `POST ""` | черновик; состав — последние ревизии всех документов проекта |
| `PATCH /{id}` | подпись и связь; присланный `null` у `external_tender_id` снимает связь |
| `PUT /{id}/documents/{document_id}`, `DELETE …` | состав черновика |
| `DELETE /{id}` | только черновик |
| `POST /{id}/freeze` | заморозка и отпечаток |

Отпечаток: `sha256` канонического JSON (`sort_keys`, без пробелов, `ensure_ascii=False`) из
`tender_number` проекта, `external_version` и списка `{document_id, document_revision_id,
source_sha256, section, use_in_model}` по `document_id`. Чистая функция `compute_manifest_sha256` в
`app/services/tender_versions.py`.

Связь с HUBTender: сервер сам читает `get_tender`, сверяет `tender_number` с `project.external_ref`
(иначе `TENDER_VERSION_NUMBER_MISMATCH`) и записывает `version` из ответа. Ручному проекту связь
запрещена (`TENDER_VERSION_LINK_FORBIDDEN`). Ошибки HUBTender идут прежними кодами `TENDERHUB_*`.
Клиент приходит зависимостью `get_optional_tenderhub_client`: при выключенной интеграции это `None`, и
версии работают без HUBTender.

**Один номер — один проект (ADR-0035 п.2).** В `GET /integrations/tenderhub/tenders` у строки с другим
UUID, но с номером, уже занятым проектом пространства, поле `same_number_project_id` ведёт в этот проект.
`POST /integrations/tenderhub/projects` отказывает в создании второго проекта по номеру кодом
`TENDERHUB_NUMBER_TAKEN` (409, `issue.project_id`). Уникальность в базе не менялась, существующие проекты и
версии задним числом не трогались. При дублях номера в старых данных берётся самый ранний проект.

**Интерфейс.** Маршрут `/projects/[projectId]/versions`, ссылка «Версии тендера» на странице проекта
видна только при включённом флаге; при выключенном маршрут отвечает «Страница не найдена». Список
версий, создание черновика, состав с выбором ревизии, разделом и переключателем «В модель», связь с
HUBTender, заморозка с подтверждением и показом начала отпечатка; замороженная версия только для чтения.
В списке тендеров HUBTender вместо «Создать проект» для занятого номера — «Версии проекта». Общее поле с
крестиком `ClearableInput`. Типы — только из сгенерированного `packages/api-client`.

## Файлы

Новые:

- `apps/api/alembic/versions/20261102_0019_tender_versions.py`
- `apps/api/app/models/tender_version.py`, `app/contracts/tender_versions.py`
- `apps/api/app/services/tender_versions.py`, `app/api/v1/tender_versions.py`
- `apps/api/tests/test_tender_versions.py`
- `apps/web/src/lib/tender-versions.ts` (+ `.test.ts`)
- `apps/web/src/components/versions/` (CompositionTable, CreateDraftDialog, DeleteDraftDialog, FreezeDialog,
  HubLinkPanel, TenderVersionsScreen, VersionDetail, VersionList)
- `apps/web/src/components/ui/ClearableInput.tsx` (+ `.test.tsx`)
- `apps/web/src/app/(portal)/projects/[projectId]/versions/page.tsx`

Изменены (добавлены только свои строки):

- `apps/api/app/core/features.py` — флаг `tender.versions`
- `apps/api/app/domain.py`, `app/errors.py` — статус версии, действия аудита, восемь кодов ошибок
- `apps/api/app/models/__init__.py`, `app/api/v1/router.py`, `app/api/v1/deps.py`
- `apps/api/app/api/v1/integrations.py`, `app/services/projects.py`, `app/schemas.py` — один номер — один проект
- `apps/api/tests/test_meta.py`, `tests/test_control_plane.py` — новый ключ в перечнях флагов
- `apps/web/src/lib/errors.ts`, `components/projects/TenderHubDialog.tsx`, страница проекта
- `packages/api-client/openapi.json`, `src/index.ts`, `src/sdk.gen.ts`, `src/types.gen.ts` — генерация

## Проверки

Тесты — на изолированной базе `quantor_tenderver` (`POSTGRES_DB`), без общей тестовой базы.

| Команда | Итог |
|---|---|
| `pytest tests/test_tender_versions.py` | 41 passed |
| `pytest tests` (весь набор API) | 1567 passed |
| `alembic upgrade head` → `downgrade 0018_local_auth` → `upgrade head` → `downgrade base` → `upgrade head`, `alembic check` | без ошибок, «No new upgrade operations detected» |
| `ruff check .`, `ruff format --check .`, `mypy app` | чисто; 242 файла без замечаний |
| `openapi_export` + `openapi-ts` | сгенерировано, добавлены 9 функций SDK, чужих изменений нет |
| `tsc --noEmit`, `eslint` по новым и изменённым файлам | чисто |
| `vitest` (`tender-versions.test.ts`, `ClearableInput.test.tsx`) | 12 passed |

Покрыто тестами API: заморозка и детерминизм отпечатка (эталонное значение и перестановка состава),
триггеры мимо сервиса (изменение, удаление, состав замороженной версии, CHECK, единственный черновик,
RESTRICT ревизии), чужая ревизия, второй черновик, чужое пространство, роль читателя, флаг закрывает все
девять маршрутов, несовпадение номера тендера, отказ во втором проекте по номеру, аудит.

## Проверка в браузере

2026-11-02, Playwright, стенд локальный: база `quantor_m2check`, фейковый HUBTender с синтетикой, настоящий
HUBTender запросов не получал. Сценарий — выключенный флаг, черновик, состав, подпись, связь, заморозка,
запись в замороженную версию мимо интерфейса, диалог тендеров, отказ HUBTender, удаление.

| Прогон | Итог |
|---|---|
| Chromium, 1440×900 | 66 проверок, FAIL 0 |
| WebKit, размер iPhone 12, создание и заморозка | 9 проверок, FAIL 0; приближение к Safari, не Safari |
| 360, 390, 430, 768, 1280, 1440 px × светлая и тёмная тема × 4 состояния | горизонтального скролла нет, диалоги в окне, длинное имя переносится |

Первый прогон нашёл четыре дефекта, все исправлены:

- список ревизий вылезал за карточку и обрезался (на 360 px — у любого документа);
- черновик удалялся без подтверждения — добавлен `DeleteDraftDialog`;
- после удаления интерфейс перезапрашивал удалённую версию и получал 404 — `invalidationAfterDelete`,
  покрыто тестом;
- причина недоступности «Создать черновик» была только в `title` — теперь текстом под кнопкой.

Не исправлено, общее для портала, а не только для M2:

- от 768 px контролы 32 px и шрифт полей 13 px, на iPad это нарушает правила `Odintsov/CLAUDE.md`
  (цель ≥ 44 px, поле ≥ 16 px): так устроены токены и общий `Button`;
- крошки `TopBar` на телефоне высотой 18,6 px;
- контраст отключённых кнопок 2,4–3,9:1, WCAG для них порога не требует.

Не проверено: настоящий Safari, живые iPhone, iPad и Android (`position: fixed` с клавиатурой), установка PWA.

## Не сделано и почему

- Принадлежность ревизии документу проверяет сервис, но не база: составной внешний ключ потребовал бы
  уникального индекса на `document_revisions`, а изменения в документах вне задачи.
- Параллельные запросы защищены блокировками строк (проект — для номера и единственного черновика, версия
  — для состава и заморозки) и частичным уникальным индексом, но отдельного теста на гонку нет.
- Настоящий Safari и живые устройства не проверены, см. раздел «Проверка в браузере».
- Перепривязка проекта (`tenderhub_binding.rebind`) по-прежнему проверяет конфликт только по UUID тендера и
  не сверяет номер: правило «один номер — один проект» действует на создание проекта, не на перепривязку.

## Стыки для приёмки

1. Номер ревизии (`revision_number`) считается как место ревизии среди ревизий документа по
   `(created_at, id)`; тот же порядок использует `GET /documents/{id}/revisions`, поэтому в выпадающем списке
   интерфейса «№N» совпадает с ответом версии.
2. У `DocumentRevision.source_sha256` ограничение NOT NULL, поэтому ошибка `TENDER_VERSION_REVISION_NO_HASH`
   на практике недостижима: проверка защитная, покрыта тестом чистой функции отпечатка.
3. `GET /hub-candidates` доступен праву просмотра проекта (как сказано в ТЗ): читатель может вызвать
   чтение HUBTender через ключ портала. Если это нежелательно — заменить на `INTEGRATION_READ`.
4. Поиск HUBTender нестрогий, поэтому кандидаты фильтруются по точному `tender_number`; архивные строки
   (`is_archived=false` в клиенте) в список не попадают.
5. В `GET /integrations/tenderhub/tenders` добавлено обязательное поле `same_number_project_id`
   (может быть `null`): клиенты, которые строят `TenderBriefRead` руками, должны его передавать.
6. Перечни флагов в `test_meta.py` и `test_control_plane.py` пополнены ключом `tender.versions`; других
   действующих тестов, ожидавших прежнего поведения, не нашлось.
7. Номер версии HUBTender записывается при связывании и не обновляется: если в HUBTender версия строки
   поменяется позже, замороженный отпечаток от этого не изменится.
