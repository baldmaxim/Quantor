# ADR-0028. MEP: базовое распознавание заморожено, семантическое — в scope

Статус: принято, 2026-09-15. Дополняет [ADR-0027](0027-mep-gipoteza-p-rd-vor-izolirovannyj-eksperiment.md).

## Контекст

ADR-0027 разрешил вход Stage 1 только как `oracle_stage1`, а автоматическое распознавание ВК отложил
до отдельного решения (Р-MEP-6). Владелец выдал пакет v3 (`_prompts/mep_p_to_rd_v3/`) с правкой scope:

> Base document recognition is solved and frozen. MEP semantic recognition is NOT solved and IS IN SCOPE.

Сверка с репозиторием ([квитанция](../mep/MIGRATION_V1_TO_V3_RECEIPT.md)): базовое распознавание —
импорт legacy-v1, блоки `text/image/stamp` с bbox и текстом блока. MEP-сущностей, OCR-спанов,
вектора и серверного растра листа нет.

## Решение

```text
legacy-v1 base recognition [FROZEN]
→ MEP semantic extraction (vision/, NEW)
→ MepEvidenceGraph
→ P→RD generator → MepNetworkGraph → Quantity Engine → Pricing
```

- Семантическое распознавание ВК — часть эксперимента. Код, датасет разметки и веса — в `vision/`
  (ADR-0021), за флагом `mep_rd_hypothesis_v1` в портале.
- Базовое распознавание read-only: импорт legacy-v1, `PageGeometry`, калибровка, `Measurement` и
  `count.v1` / `length.v1` / `area.v1`, существующие слои просмотрщика, контур Stage 2B.
- Слой MEP читает готовые артефакты: `Region` и тексты блоков, геометрию страницы, калибровку.
  Второй общий распознаватель, второй OCR и второй рендерер PDF не строятся.
- Вход генератора — только `MepEvidenceGraph` с `input_mode` ∈ `MODEL_EXTRACTED` / `HUMAN_GT` /
  `HYBRID_REVIEWED`. `oracle_stage1` из ADR-0027 становится `HUMAN_GT` (Track A); ручная разметка —
  GT и валидация, не production-вход.
- Detection («что показано на П») и Generation («какая РД нужна») — разные слои и метрики.
  `inferred` не маркируется `observed`; в EvidenceGraph нет `rd_prior_inferred`.
- Нумерация и порядок промтов — по v3.

### Уточнения владельца 2026-09-15

- Экспортный ZIP портала — пример формата, не описание внутреннего base. Внутренний pipeline Quantor,
  экспортный контракт и MEP-слой разделены ([контракт переиспользования](../mep/BASE_RECOGNITION_REUSE_CONTRACT.md)).
- Растр: MEP-слой получает изображение страницы из исходного PDF через `PageRasterProvider` —
  детерминированный рендер с кешем, без OCR, классификации и разметки. Это не второй recognition
  pipeline. Сначала переиспользуется существующий рендер; серверного в репозитории нет. pdf.js не меняется.
- Ядро контрактов discipline-agnostic; специфика ВК/ОВ — через system profile и class schema.
- Label schema фиксируется по реальному комплекту П пилотной системы; альбом-пример как датасет не используется.

## Последствия

- Строка «Вход Stage 1» и последствие «predicted Stage 1 — `BLOCKED`» ADR-0027 заменены этим решением;
  Р-MEP-6 закрыт.
- Серверного растра листа в репозитории нет; создаётся `PageRasterProvider` в `vision/` (v3 03), после
  решения по лицензии `pypdfium2` (сейчас `conditional`).
- Taxonomy определяется по реальным листам ВК П; пока их нет — `HOLD_DATA` (Р-MEP-3).
- Тяжёлое обучение по-прежнему только по команде владельца.
- Схемы `_prompts/mep_hypothesis_v1/schemas/*_v0.1` устарели, заменяются контрактами v0.3.

## Отвергнутые альтернативы

- **Оставить только oracle.** Не проверяет production-like цепочку и не показывает, куда уходит ошибка.
- **Считать MEP-сущности частью base.** Реальный выход legacy-v1 их не содержит.
- **Новый общий распознаватель документов.** Дублирует замороженный base и ломает его границу.
