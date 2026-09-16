# MEP: контракт переиспользования base recognition

v3 PROMPT 01, 2026-09-15. Решения — [ADR-0027](../adr/0027-mep-gipoteza-p-rd-vor-izolirovannyj-eksperiment.md),
[ADR-0028](../adr/0028-mep-semanticheskoe-raspoznavanie-v-scope.md). Проверено по коду репозитория, не по
экспортному ZIP.

## 1. Три контура, которые не смешиваются

| Контур                         | Где живёт                                                                          | Роль для MEP                                           |
| ------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| A. Внутренний pipeline Quantor | этот репозиторий: `apps/api`, `apps/web`, `vision/`, `tools/`                      | неизменяемый вход и инфраструктура — **FROZEN**        |
| B. Экспортный контракт портала | ZIP распознавалки: PDF, `*_blocks.json`, `*_results.md/html`, `*_stamp_audit.json` | формат входа, который Quantor импортирует — **FROZEN** |
| C. MEP Semantic Extraction     | новый код в `vision/` (офлайн) и пространство имён `mep` за флагом                 | создаёт недостающую инженерную семантику — **NEW**     |

Код распознавалки, выпускающей контракт B, в репозитории и соседних проектах каталога не найден.
Её промежуточные артефакты (растры страниц, OCR, кропы) из Quantor недоступны: кропы есть только как
внешние `crop_url`, которые сервер не загружает (ADR-0007). Вывод о её внутреннем составе не делается.

## 2. Что можно читать (контур A)

| Артефакт                   | Точный источник                                                                                                                           | Что даёт                                                            |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| исходный PDF ревизии       | `DocumentRevision.storage_key`, `source_sha256` (`apps/api/app/models/document.py`); `ObjectStorage.iter_stream`                          | байты PDF и хеш входа                                               |
| лист                       | `Sheet` (`apps/api/app/models/sheet.py`): `page_index`, `rotation`                                                                        | выбор страницы; `width_px/height_px` в расчётах не участвуют        |
| области распознавалки      | `Region`: `block_type`, `coords_norm`, `polygon_points`, `raw_content_md`, `legacy_metadata`                                              | текст блока целиком, рамки блоков `text/image/stamp`                |
| сырые файлы пакета         | `RecognitionArtifact` (`apps/api/app/models/artifact.py`): blocks_json, results_md, results_html                                          | исходник для перепроверки импорта                                   |
| геометрия страницы         | `PageGeometry` (`apps/api/app/models/page_geometry.py`): `display_width_pt/height_pt`, `crop_box`, `pdf_rotation`, `geometry_fingerprint` | канонический кадр страницы для растра и метрики                     |
| перевод координат          | `apps/api/app/services/geometry/transform.py`: `normalized_to_pdf_display`, `pdf_display_to_normalized`, `polyline_length_pdf_points`     | normalized ↔ pt, длины                                              |
| валидность многоугольника  | `apps/api/app/services/geometry/validity.py`: `validate_polygon`                                                                          | проверка геометрии GT                                               |
| масштаб                    | `ScaleCalibration` (`apps/api/app/models/scale.py`): `mm_per_pt`, `verification_state`                                                    | метрика только при явной калибровке                                 |
| примитивы разметки         | `Measurement` count/line/polyline/polygon (`apps/api/app/models/takeoff.py`), инструменты `apps/web/src/lib/viewer/tool-machine.ts`       | ручная GT-разметка; не production-вход                              |
| детерминированные величины | `apps/api/app/services/quantity.py`: `count.v1`, `length.v1`, `area.v1`, `area_with_holes.v1`                                             | количества ВОР через адаптер                                        |
| слои просмотрщика          | `apps/web/src/lib/viewer/viewport-layer.ts`, `overlay.ts`, `measurement-overlay.ts`, `coordinates.ts`                                     | образец нового слоя evidence/network                                |
| флаги                      | `apps/api/app/core/features.py` (`mep_rd_hypothesis_v1`), `require_feature` (`api/v1/deps.py`)                                            | закрытие возможности на сервере и в интерфейсе                      |
| задания                    | `Job`, `app/services/jobs.py`, `app/worker/registry.py`                                                                                   | образец; новых типов заданий в `apps/api` без отдельного промта нет |
| тайлы и обратный перевод   | `tools/planswift_gt/planswift_gt/tiles.py`: `TileTransform.tile_to_page`, `grid_origins`, `crop`                                          | тайлинг растра с сохранением перевода в normalized                  |
| геометрия 2D               | `tools/planswift_gt/planswift_gt/geometry2d.py`: `fill_rings`, `simplify`, `phash`                                                        | маски, упрощение линий, дубликаты страниц                           |
| PNG, компоненты, метрики   | `vision/quantor_vision/png.py`, `sam/prompts.py::components`, `slab/metrics.py`                                                           | чтение тайлов, связные компоненты, метрики масок                    |
| протокол прогона           | `vision/quantor_vision/runrecord.py`: `RunRecord`, `sha256_file`, `source_state`                                                          | происхождение прогонов MEP                                          |
| лицензионный гейт          | `vision/licenses/decisions.json`, `vision/quantor_vision/licenses.py`                                                                     | допуск новых зависимостей                                           |
| контракт стадий            | `apps/api/app/contracts/pipeline.py`: `PipelineStage` (OCR_LAYOUT, VECTOR_EXTRACT, SYMBOL_DETECT…)                                        | только словарь стадий; ничего не исполняет                          |

## 3. Что нельзя менять

- импорт legacy-v1: `apps/api/app/services/legacy/` (в т.ч. фильтр расширений архива, игнор `stamp_audit`);
- загрузка и хранилище: `services/uploads.py`, `storage/`;
- `PageGeometry`, `services/geometry/`, калибровка, `Measurement`, `services/quantity.py`, правила `*.v1`;
- типы заданий `JobType` и их обработчики;
- просмотрщик: `pdfjs-backend.ts`, `surface.ts`, `usePageRaster.ts`, существующие слои;
- контур Stage 2B: `tools/planswift_gt/`, `vision/quantor_vision/slab/`, `sam/`, их `TASKS`, датасеты и веса;
- распознавалка контура B и её формат.

Нужна правка любого пункта — отдельное решение владельца, не ради MEP. Расширение списков `TASKS`
(`runrecord.py`, `buildconfig.py`) — тоже правка Stage 2B: MEP заводит свои записи прогона рядом.

## 4. Неизменяемый вход и ссылки на источник

Каждый артефакт MEP хранит ссылку на источник, а не копию:

| Поле                      | Значение                                                     |
| ------------------------- | ------------------------------------------------------------ |
| `source_pdf_sha256`       | `DocumentRevision.source_sha256`                             |
| `revision_id`, `sheet_id` | идентификаторы Quantor                                       |
| `page_index`              | `Sheet.page_index`                                           |
| `geometry_fingerprint`    | `PageGeometry.geometry_fingerprint`                          |
| `package_sha256`          | `source_metadata.package_sha256`, если лист пришёл из пакета |
| `region_ids[]`            | `Region.id`, если сущность опирается на текст блока          |
| `raster_key`              | ключ кеша `PageRasterProvider` (см. гейт, §5)                |
| `scale_calibration_id`    | только при метрических утверждениях                          |

Координаты — нормализованные от левого верхнего угла повёрнутой страницы (ADR-0008); поворот повторно
не применяется.

## 5. Проверка отсутствия побочных эффектов

- тесты флагов: `apps/api/tests/test_meta.py`, `test_control_plane.py`, `test_pilot_flag.py` — флаг
  выключен и из админки не включается;
- полный `pnpm test:api`, `pnpm test:planswift`, `pnpm test:vision` — без изменений результатов;
- `git diff` по путям §3 пуст на каждом промте MEP;
- `test_contracts.py::FORBIDDEN_PACKAGES` и `test_real_job_types_are_named_explicitly` — без правок;
- растр MEP сверяется с `PageGeometry` (размер в pt × плотность) и с `Region.coords_norm` на реальном листе.
