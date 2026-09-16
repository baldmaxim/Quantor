# MEP: гейт semantic gap

v3 PROMPT 01, 2026-09-15. Контракт входа — [BASE_RECOGNITION_REUSE_CONTRACT.md](BASE_RECOGNITION_REUSE_CONTRACT.md).

## Вердикт

**`READY_TO_DEFINE_LABELS`** — по инфраструктуре.

- Пригодный вход есть: исходный PDF с хешем, лист, канонический кадр страницы, перевод координат,
  калибровка. Растр страницы разрешён владельцем (Р-MEP-9 = ALLOW) через `PageRasterProvider`.
- Изменение замороженного base не требуется.
- Конкретный label schema (PROMPT 02) фиксируется **только после передачи реального комплекта стадии П**
  выбранной пилотной системы. До этого — PROMPT 05 (контракты, discipline-agnostic ядро).
- Альбом `ПД-00542664-ОВ0-1_V1` — пример формата экспорта; ontology из него не выводится, как датасет не
  используется.

## 1. Что реально есть внутри репозитория

- Загрузка и хранение: `Document`, `DocumentRevision` (`source_sha256`, `storage_key`), `ObjectStorage` на S3/MinIO.
- Импорт пакета: `Sheet`, `Region`, `RecognitionArtifact` (blocks_json, results_md, results_html).
- `PageGeometry` на pypdf: размер, поворот, рамки; переводы normalized ↔ pt; валидность многоугольника.
- `ScaleCalibration` (только ручная), `TakeoffItem`, `Measurement` (count/line/polyline/polygon, `source`
  manual/ai/imported), правила `*.v1`.
- Задания `legacy_import`, `pdf_geometry_extract`; флаги с проверкой на сервере.
- Просмотрщик pdf.js (растр только в браузере), Canvas2D-слои, инструменты разметки.
- Офлайн: тайлы и обратный перевод, геометрия 2D, PNG, связные компоненты, метрики, `RunRecord`,
  лицензионный гейт. Растры — только из TIFF PlanSwift.
- Только контракты, без реализации: `PipelineStage` (OCR_LAYOUT, VECTOR_EXTRACT, SYMBOL_DETECT, SEMANTIC_LINK),
  `ModelProvider`; `PredictionCandidate` — только в ADR-0022.

**Нет в репозитории:** серверного рендера PDF, OCR, извлечения текстового и векторного слоя PDF,
инференса, экспорта (ZIP/отчётов), project-heldout split (в Stage 2B — within-project grouped holdout).

## 2. Что есть только в экспорте портала

| Файл экспорта        | Что содержит                                                                       | Что берёт Quantor                                      |
| -------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `*.pdf`              | исходный документ                                                                  | хранится как `DocumentRevision(pdf)`                   |
| `*_blocks.json`      | страницы (`width_px/height_px/rotation`), блоки text/image/stamp, bbox, `crop_url` | `Sheet`, `Region`; `crop_url` — строка, не загружается |
| `*_results.md`       | текст TEXT-блоков, описания IMAGE-блоков (Summary/Description/Entities)            | секция в `Region.raw_content_md`                       |
| `*_results.html`     | то же в HTML                                                                       | хранится, не разбирается                               |
| `*_stamp_audit.json` | поля штампа: стадия, лист, организация, подписи                                    | **не читается**                                        |
| кропы по `crop_url`  | фрагменты листа на внешнем сервисе                                                 | не загружаются (ADR-0007)                              |

Внутренние артефакты распознавалки (растры, OCR-спаны, вектор) в экспорт не входят. Описания IMAGE-блоков
написаны моделью распознавалки — для MEP это не observed-evidence.

## 3. Что переиспользуется

| Шаг MEP              | Переиспользуется                                                                |
| -------------------- | ------------------------------------------------------------------------------- |
| изображение страницы | исходный PDF + `PageGeometry` как эталон кадра → новый `PageRasterProvider`     |
| тайлы для модели     | `tiles.py::TileTransform`, `grid_origins`, `crop` через адаптер растра          |
| текст                | `Region(text).raw_content_md` + `coords_norm` (уровень блока)                   |
| перевод координат    | `services/geometry/transform.py`                                                |
| метрика              | `ScaleCalibration`, `length.v1`/`count.v1` через адаптер                        |
| GT-разметка          | примитивы `Measurement` и инструменты просмотрщика — только в dev/benchmark     |
| overlay              | `ViewportLayer` + новый painter рядом с существующими                           |
| датасет и прогоны    | `QUANTOR_DATASET_ROOT`, отказ писать в git, `RunRecord`, `sha256_file`, `phash` |
| зависимости          | лицензионный гейт `vision/licenses`                                             |
| инференс             | нет готового; интерфейсы `Predictor`/`Segmenter` — образец                      |

Дублирования нет: растр создаётся потому, что серверного рендера не существует (Р-MEP-9).

## 4. Что создаётся специально для MEP

| Данные / модуль                            | Зачем                                                         | Когда                          |
| ------------------------------------------ | ------------------------------------------------------------- | ------------------------------ |
| `PageRasterProvider` + кеш растров         | вход детектора                                                | v3 03 (план — §5)              |
| system profile + class schema              | специфика ВК/ОВ поверх discipline-agnostic ядра               | 05 (механизм), 02 (содержание) |
| `MepEvidenceGraph`, `MepNetworkGraph` v0.3 | контракты observed / generated                                | 05                             |
| label schema и GT-разметка по реальным П   | обучение и валидация экстрактора                              | 02, после данных               |
| текст с позицией внутри блока              | привязка диаметров и марок к символам; в экспорте только блок | решение — 02/03                |
| символы, стояки, приборы, линии, связи     | в base отсутствуют полностью                                  | 03 baseline, 04                |
| project-heldout split                      | защита от утечки по проекту                                   | 02                             |
| парные П↔РД и RD NetworkGraph targets      | генератор                                                     | 06, Р-MEP-3                    |
| исторические строки ВОР                    | расценка                                                      | 10, Р-MEP-3                    |
| `MepRunRecord`                             | происхождение прогонов MEP без правки `TASKS` Stage 2B        | 03                             |

Позиционный текст решён Р-MEP-15: векторный текстовый слой исходного PDF читается read-only в MEP-слое
(`SourceType.PDF_TEXT_LAYER`); нет слоя — `unavailable`, не блокер. OCR не добавляется.

## 5. План `PageRasterProvider`

Существующего backend raster API нет (`apps/api` — только pypdf; `vision/`, `tools/` — только TIFF).
Реализация — в v3 03, не сейчас.

**Место:** `vision/quantor_vision/mep/raster/` — офлайн-контур (ADR-0021). `apps/api` и pdf.js не меняются.
Когда появится доверенный исполнитель инференса (Stage 2B, промт 20), он использует тот же провайдер.

**Библиотека:** `pypdfium2` (Apache-2.0 / BSD-3, PDFium BSD-3). Сейчас в `decisions.json` — `conditional`;
перед добавлением: описать лицензии bundled PDFium, перевести решение для офлайн-scope MEP, объявить
extra `mep-raster`. PyMuPDF запрещён (AGPL, ADR-0016).

**Интерфейс:**

```text
RasterSpec(dpi | max_side, max_pixels, colorspace="gray", crop_norm=None)
PageRasterProvider.render(pdf_path, source_pdf_sha256, page_index, spec, geometry) -> PageRaster
PageRaster(key, png_path, png_sha256, width_px, height_px, px_per_pt, crop_norm,
           renderer="pypdfium2", renderer_version, spec, geometry_fingerprint)
```

**Правила:**

- только рендер: без OCR, классификации, разметки, улучшения изображения;
- кадр = display box `PageGeometry` (CropBox ∩ MediaBox, `/Rotate` применён); `x_norm = x_px / width_px`
  без повторного поворота; несовпадение размера с `display_*_pt × px_per_pt` — отказ;
- детерминизм: закреплённая версия, фиксированные флаги рендера, grayscale, стабильная запись PNG;
  тест — повторный рендер даёт тот же `png_sha256`;
- кеш: `key = sha256(source_pdf_sha256, page_index, renderer, renderer_version, spec)`; хранение
  `${QUANTOR_DATASET_ROOT}/mep/rasters/<key>.png` + `<key>.json`; в git и `apps/api` — нет;
- память: лимит пикселей (листы до 14560×6869 при 300 DPI), `crop_norm` для частичного рендера;
- тайлы — через `TileTransform` с записью формулы обратного перевода;
- проверки: синтетический PDF в `tmp_path` (линии в известных pt, поворот 90°, CropBox ≠ MediaBox),
  совпадение нормализованных координат с `transform.py`; сверка с `Region.coords_norm` на реальном листе —
  вне git.

## 6. Блокеры

| Блокер                                       | Касается       | Статус                   |
| -------------------------------------------- | -------------- | ------------------------ |
| реальный комплект стадии П пилотной системы  | 02, 03, 04     | ждёт владельца (Р-MEP-3) |
| лицензия `pypdfium2` `conditional` → решение | 03 (растр)     | оформить до реализации   |
| позиционный текст                            | 02/03          | открыт                   |
| правила фитингов                             | 09             | Р-MEP-7                  |
| парные П↔РД, исторические ВОР                | 06, 07, 08, 10 | Р-MEP-3                  |

PROMPT 05 блокеров не имеет.
