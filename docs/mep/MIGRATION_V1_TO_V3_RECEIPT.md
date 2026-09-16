# MEP: квитанция миграции на пакет v3

Дата: 2026-09-15. База: `d570e83`, рабочее дерево не закоммичено.
Пакет v3 — `_prompts/mep_p_to_rd_v3/MASTER_PROMPTS_v3.md`, патч — `_prompts/mep_p_to_rd_v3/MIGRATION_FROM_V2.md`.
Решение — [ADR-0028](../adr/0028-mep-semanticheskoe-raspoznavanie-v-scope.md).

## 1. Что реально выполнено до миграции

Патч написан для перехода с `Prompt_Pack_v2`. **Пакет v2 в репозитории не применялся.** Работа шла по
`_prompts/mep_hypothesis_v1/`, выполнен только промт 00, и только документами.

| Файл                                                                       | Изменение                |
| -------------------------------------------------------------------------- | ------------------------ |
| [ADR-0027](../adr/0027-mep-gipoteza-p-rd-vor-izolirovannyj-eksperiment.md) | новый                    |
| [MEP_EXPERIMENT_STATE.md](MEP_EXPERIMENT_STATE.md)                         | новый                    |
| `CLAUDE.md`                                                                | раздел «MEP-эксперимент» |
| `docs/adr/README.md`                                                       | строка ADR-0027          |
| `_prompts/mep_hypothesis_v1/`                                              | пакет v1, без изменений  |

Кода MEP нет: нет флага `mep_rd_hypothesis_v1`, пространства имён `mep`, адаптера, `MepGenerationInput`.
Отменять нечего; переиспользовать как base-artifact adapter тоже нечего — адаптер появится в v3 01.

> **Поправка владельца 2026-09-15.** ZIP ниже — пример экспорта портала, а не полный состав внутреннего
> base recognition. Выводы §2–3 о «составе base» заменены аудитом PROMPT 01:
> [BASE_RECOGNITION_REUSE_CONTRACT.md](BASE_RECOGNITION_REUSE_CONTRACT.md),
> [MEP_SEMANTIC_GAP_GATE.md](MEP_SEMANTIC_GAP_GATE.md). Вопрос растра закрыт: Р-MEP-9 = ALLOW.

## 2. Проверенный выход base recognition (пример экспорта)

Образец — реальный пакет legacy-v1 `ПД-00542664-ОВ0-1_V1.zip` (ОВ, не ВК; вне git):

- `blocks.json`: `schema_version: 1`, `coordinate_space: normalized_page_top_left`, `pages[]` с
  `width_px/height_px/rotation`, блоки `text` 285 / `image` 267 / `stamp` 110;
- `results.md`, `results.html` — markdown-описание блоков; `stamp_audit.json` — штампы;
- PDF исходника.

В портале это `Sheet` и `Region` (`apps/api/app/models/sheet.py`): `block_type`, `coords_norm`,
`polygon_points`, `raw_content_md`, `legacy_metadata`. Итого: **блоки с bbox и текстом на уровне блока.**
Нет OCR-спанов, векторных примитивов, MEP-классов, этажа, стадии, confidence.

Растр: серверного рендерера PDF нет. Есть pdf.js на клиенте (ADR-0025) и TIFF-растры из PlanSwift в
офлайн-контуре `tools/planswift_gt/`. Растры распознавалки в пакет не входят, `crop_url` сервер не
загружает.

## 3. MEP-сущности: что есть и чего нет

Предварительно: реальных листов **ВК стадии П** в доступе нет, taxonomy уточняется в v3 01–02.

| Required MEP entity   | already available | exact source                                                 | missing                         | proposed extraction method                                      | GT needed            |
| --------------------- | ----------------- | ------------------------------------------------------------ | ------------------------------- | --------------------------------------------------------------- | -------------------- |
| riser / source anchor | нет               | —; изображение листа — только PDF (рендерера на сервере нет) | класс, точка, система, марка    | symbol/template matching по растру + связь с подписью «Ст В1-…» | point + атрибуты     |
| fixture / terminal    | нет               | — (часть приборов может попасть в `image`-блок без класса)   | класс, точка, тип прибора       | детектор символов по растру; тип — по подписи                   | point/bbox + тип     |
| equipment             | нет               | —                                                            | класс, bbox, марка              | детектор символов + OCR-regex марки                             | bbox + марка         |
| shaft / zone          | нет               | —                                                            | контур шахты/помещения          | геометрия по растру; сначала проверить нужность генератору      | polygon (если нужен) |
| visible pipe segment  | нет               | —                                                            | полилинии, система              | извлечение линий по растру, фильтр по типу линии                | polyline + система   |
| system label (В1, К1) | частично          | `Region(text).raw_content_md` + `coords_norm` блока          | привязка к позиции внутри блока | regex/lexicon по тексту блока; позиция — только уровень блока   | text span ref        |
| diameter / size text  | частично          | то же                                                        | спан и позиция подписи          | regex `Ø\d+`, `Ду\d+`, `d\d+` по тексту блока                   | text span ref        |
| mark / name           | частично          | то же; `stamp_audit.json` — только штамп                     | спан, позиция                   | regex/lexicon                                                   | text span ref        |
| connection marker     | нет               | —                                                            | класс, точка                    | детектор символов                                               | point                |
| text ↔ symbol         | нет               | —                                                            | связь                           | геометрическое связывание (расстояние, выноска)                 | relation edge        |
| symbol ↔ route        | нет               | —                                                            | связь                           | касание/близость символа и полилинии                            | relation edge        |
| route ↔ riser         | нет               | —                                                            | связь                           | касание/близость полилинии и стояка                             | relation edge        |

Масштаб — `ScaleCalibration` (ADR-0018), не автоматически. Инструмент ручной GT-разметки —
существующие примитивы `Measurement` count/polyline (только GT, не production-вход).

Ключевой пробел: **для детекции символов и линий на произвольном листе ВК П нет изображения из
существующего пайплайна** — тайлы `vision/` строятся из растров PlanSwift, а не из PDF портала. Правило v3 «не строить второй PDF renderer» и отсутствие первого — вопрос
владельцу на гейте v3 01 (`NEEDS_OWNER_DECISION`).

## 4. Что остаётся из v1

- ADR-0027: изоляция, флаг `mep_rd_hypothesis_v1`, `vision/` для тяжёлого кода, данные вне git,
  детерминированные величины, отдельная цена.
- Решения Р-MEP-1, Р-MEP-3, Р-MEP-4, Р-MEP-5, Р-MEP-7; реестр рисков; точки интеграции.
- `oracle_stage1` — как режим входа `HUMAN_GT` (Track A).
- Методика `reference/TEST_PIPELINE_v1.md`, `ONE_FLOOR_TEST_PROTOCOL.md` — как справка.

## 5. Что меняется

- Семантическое распознавание MEP — в scope (новый слой в `vision/`), не `BLOCKED` по scope.
- Вход генератора — только `MepEvidenceGraph` с `input_mode` ∈ `MODEL_EXTRACTED` / `HUMAN_GT` /
  `HYBRID_REVIEWED`.
- Stage 1 v1 (один промт) расщеплён на v3 02 разметка, 03 baseline, 04 обучаемый экстрактор.
- Контракты — v0.3 (v3 05): provenance EvidenceGraph без `rd_prior_inferred`.
- Нумерация промтов — по v3.

## 6. Устаревшие артефакты (не удаляются, история)

- `_prompts/mep_hypothesis_v1/schemas/*_v0.1.schema.json` — заменяются контрактами v3 05;
- порядок v1 `00 → 01 → 02 → 03 (oracle) → 07 → 10 → 04 → 05 → 08 → 06 → 09 → 11`;
- формулировка Р-MEP-6 и строка ADR-0027 «predicted Stage 1 — `BLOCKED`».

Имя state-файла `MEP_P_TO_RD_STATE.md` из v3 00 не вводится: живой документ — `MEP_EXPERIMENT_STATE.md`.

## 7. Соответствие промтов

| v1                      | v3                                            | Статус                                 |
| ----------------------- | --------------------------------------------- | -------------------------------------- |
| 00 контекст             | 00                                            | выполнен документами; п.6 (флаг) — нет |
| 01 аудит и каркас, флаг | 00 п.6 + 01 (gap audit, reuse contract, gate) | следующий                              |
| 02 контракты v0.1       | 05 контракты v0.3                             | ожидает                                |
| 03 Stage 1 (oracle)     | 02 разметка, 03 baseline, 04 обучаемый        | ожидает                                |
| 04 датасет П↔РД         | 06                                            | ожидает, Р-MEP-3                       |
| 05 baseline             | 07                                            | ожидает                                |
| 06 обучаемая модель     | 08                                            | ожидает                                |
| 07 Quantity Engine      | 09                                            | ожидает, Р-MEP-7                       |
| 08 расценка             | 10                                            | ожидает, Р-MEP-3                       |
| 10 страница портала     | 11                                            | ожидает                                |
| 09 слепой тест          | 12 (Track A / B)                              | ожидает                                |
| 11 приёмка              | 13                                            | ожидает                                |

Порядок v3 с учётом блокеров данных:

```text
00 п.6 → 01 → 05 → 02 → 03 → 09 → 11 (моки) → 06 → 07 → 04 → 10 → 08 → 12 → 13
```

## 8. Следующий шаг

v3 PROMPT 01 вместе с остатком 00 п.6 (флаг `mep_rd_hypothesis_v1`, выключен). Выход —
`BASE_RECOGNITION_REUSE_CONTRACT.md` и `MEP_SEMANTIC_GAP_GATE.md`. Ожидаемый вердикт гейта —
`NEEDS_OWNER_DECISION` (растр листа) и нужны реальные листы ВК П. Начинается только по команде владельца.
