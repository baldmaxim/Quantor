# Передача на Stage 2

Фактическое состояние портала после первого этапа. Только то, что есть в коде: без планов,
намерений и оценок. Планы следующего этапа пишутся отдельно и здесь не предвосхищаются.

## Что работает

```text
Создать проект → загрузить пакет распознавалки → импорт → открыть чертёж
→ увидеть распознанные области → выбрать область → посмотреть её свойства
```

Расчёта объёмов, распознавания и обращений к моделям нет.

## Данные

Миграция `0001_domain_stage1`, семь таблиц:

| Таблица                 | Ключевое                                                                                                          |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `projects`              | `workspace_id` — граница арендатора, пока фиксированная                                                           |
| `documents`             | `document_kind`: pdf, recognized_package, revit, navisworks, ifc, other                                           |
| `document_revisions`    | неизменяема; `source_sha256`, `storage_key`, `processing_status`, `source_metadata`                               |
| `sheets`                | `page_index` с нуля, `width_px`, `height_px`, `rotation`, уникальность по ревизии и странице                      |
| `recognition_artifacts` | blocks_json, results_md, results_html, package_zip; `sha256`, `schema_version`                                    |
| `regions`               | `coords_norm` `[x0,y0,x1,y1]` в `normalized_page_top_left`, `polygon_points`, `raw_content_md`, `legacy_metadata` |
| `jobs`                  | `queued → running → succeeded \| failed \| cancelled`, `idempotency_key`, `payload`                               |

Перечисления лежат значениями (`active`, не `ACTIVE`) с CHECK-ограничением. Бинарных данных
в базе нет.

Таблиц для `Measurement`, `QuantityItem` и `ScaleCalibration` нет намеренно — их типы
объявлены в `app/contracts/quantities.py`. `Region` в них не превращается.

## API

```text
GET    /health/live                                 без зависимостей
GET    /health/ready                                база и хранилище
GET    /api/v1/meta                                 версии и флаги возможностей

GET    /api/v1/projects                             поиск, сортировка, пагинация, последнее задание
POST   /api/v1/projects
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
GET    /api/v1/projects/{id}/documents
GET    /api/v1/projects/{id}/jobs
POST   /api/v1/projects/{id}/uploads                multipart, потоковый приём
GET    /api/v1/projects/{id}/upload-capabilities    что портал делает с каждым типом

GET    /api/v1/documents/{id}
GET    /api/v1/documents/{id}/revisions
GET    /api/v1/revisions/{id}
GET    /api/v1/revisions/{id}/artifacts
GET    /api/v1/revisions/{id}/sheets
GET    /api/v1/revisions/{id}/content-url           временная ссылка в хранилище
GET    /api/v1/sheets/{id}/regions                  фильтры по типу и статусу
GET    /api/v1/jobs/{id}
```

Контракт один — OpenAPI. TypeScript-клиент генерируется из него, drift-check в CI падает
при расхождении.

## Интерфейсы для расширения

| Что             | Где                                  | Реализации сейчас                  |
| --------------- | ------------------------------------ | ---------------------------------- |
| `ObjectStorage` | `app/storage/base.py`                | S3 (MinIO локально)                |
| `RenderBackend` | `apps/web/src/lib/viewer/backend.ts` | pdf.js; тайловый — место свободно  |
| `ModelProvider` | `app/contracts/models.py`            | ни одной, и это проверяется тестом |
| `JobScheduler`  | `app/services/job_runner.py`         | фоновая задача в процессе API      |
| Шаги конвейера  | `app/contracts/pipeline.py`          | реален только `legacy_import`      |

## Импорт пакета `legacy-v1`

Вход: ZIP с одним PDF, `*_blocks.json`, `*_results.md` и необязательным `*_results.html`.
Ожидается `schema_version = 1` и `coordinate_space = normalized_page_top_left`.

Выход: `Document(pdf)` с ревизией на извлечённый PDF, листы по числу страниц, области
по числу блоков и артефакты на файлы пакета. Пакет остаётся отдельным неизменяемым
документом.

Идентификаторы производных объектов выводятся из идентификатора ревизии пакета через
`uuid5`, поэтому повторный импорт ничего не дублирует.

`crop_url` сохраняется метаданными и никогда не загружается сервером.

## Флаги возможностей

`/api/v1/meta` отдаёт набор; интерфейс берёт его оттуда и своей копии не держит.
Включено: `projects`, `documents`, `uploads`, `legacy_import`. Выключено: `viewer`
(просмотрщик работает, флаг остаётся выключенным до приёмки на реальном пакете),
`takeoff.manual`, `takeoff.ai`, `models.gateway`, `reports`, `bim.import`,
`drawing.compare`.

Переопределяются переменной `FEATURE_FLAGS`.

## Тесты

| Набор                          | Что покрывает                                             |
| ------------------------------ | --------------------------------------------------------- |
| `tests/test_api_projects.py`   | список, поиск, пагинация, границы рабочего пространства   |
| `tests/test_api_documents.py`  | документы, ревизии, листы, области, ссылка на файл        |
| `tests/test_uploads.py`        | типы, сигнатуры, пределы, идемпотентность                 |
| `tests/test_legacy_archive.py` | безопасность архива и разбор схемы, без базы              |
| `tests/test_legacy_import.py`  | сквозной импорт, идемпотентность, отказы, эталонный архив |
| `tests/test_jobs_service.py`   | переходы состояний                                        |
| `tests/test_contracts.py`      | границы этапа как проверяемое свойство                    |
| `tests/test_performance.py`    | отсутствие роста числа запросов                           |
| `tests/test_errors.py`         | безопасные ответы при отказах                             |
| `src/lib/viewer/*.test.ts`     | координаты, камера, слой областей                         |
| `e2e/smoke.spec.ts`            | оболочка, диалоги, рабочая область, ленивость pdf.js      |

Тесты базы данных пропускаются там, где нет PostgreSQL; в CI пропуск считается ошибкой.
Тест на эталонном архиве запускается, только если архив лежит в
`_prompts/stage1/fixtures/legacy/`.

## Намеренные долги

- аутентификации нет, работает фиксированный `workspace_id`;
- импорт выполняется внутри процесса API;
- ревизии документа нельзя сравнивать;
- миниатюр страниц нет, есть список листов;
- поиска по распознанному тексту нет — нужен индекс на стороне API;
- ленты активности нет: без аутентификации автора действия записать нечем;
- образы MinIO не закреплены по версии.

## Где что лежит

```text
apps/api/app/models         таблицы
apps/api/app/services       вся работа с данными
apps/api/app/services/legacy импорт пакета
apps/api/app/contracts      границы Stage 2, без реализаций
apps/web/src/lib/viewer     координаты, камера, слой областей, отрисовщик
apps/web/src/components     интерфейс
docs/adr                    архитектурные решения
docs/stage1                 отчёты этапа
_prompts/stage1             исходный пакет промтов
```
