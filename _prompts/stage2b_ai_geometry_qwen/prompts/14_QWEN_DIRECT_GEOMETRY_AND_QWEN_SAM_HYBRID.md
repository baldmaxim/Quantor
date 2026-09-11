# PROMPT 14 — Qwen direct geometry vs Qwen→SAM hybrid

Используй best **validation-selected** Qwen checkpoint Prompt 13. Test split остаётся frozen.

## Experiment Q-DIRECT

Проверь гипотезу, может ли Qwen напрямую вернуть bounded simplified slab geometry:

```text
image → strict polygon JSON → topology validation → normalized geometry
```

Это research branch, не production assumption.

Требования:

- bounded max objects/vertices/tokens;
- outer + holes schema;
- integer 0..1000 input-relative coordinates;
- invalid/self-intersecting/parse-failed output = explicit failure;
- никаких физических area numbers от модели;
- quantity сравнивается только после existing geometry/benchmark code.

Метрики: parse rate, valid topology rate, boundary error, net-area error, latency.

## Experiment Q→SAM

Основной hybrid candidate:

```text
Qwen localization JSON
       ↓
bbox + positive/negative points
       ↓
SAM2 / MobileSAM
       ↓
mask
       ↓
existing Mask→Vector pipeline
       ↓
QTO benchmark
```

### Anti-leakage

На validation/test SAM prompt строится **только** из Qwen output. Нельзя подменять missed/poor Qwen prompt GT bbox/points и продолжать считать sample успешным.

Отдельно посчитай oracle diagnostic `GT-prompt→SAM` **только как верхнюю границу SAM**, в отдельной таблице с пометкой `ORACLE / NOT PRODUCTION`; он не участвует в model selection.

## Compare

Сравни:

- SAM-only production prompt policy из Prompt 11;
- small segmentation → SAM;
- Qwen4B → SAM;
- Qwen2B → SAM, если есть checkpoint;
- Qwen direct polygon.

Главные метрики — downstream vector/QTO, не bbox IoU сам по себе.

Создай `docs/stage2b/14-qwen-direct-and-sam-hybrid.md`.

STOP. Это контрольная точка: покажи владельцу, где Qwen реально добавил качество, а где только latency.
