# PROMPT 19 — Prediction domain + provenance

Выполнять только после PASS/owner approval Prompt 18.

Не записывай raw prediction сразу в Measurement.

## Domain

Спроектируй immutable-ish provenance:

```text
VisionPredictionRun
  └── PredictionCandidate
```

Candidate states минимум `pending / accepted / rejected`. Accepted candidate знает созданный
Measurement, но original predicted geometry не переписывается человеческой правкой.

## Storage

- raw mask/probability artifact — object storage;
- weights — controlled model artifact storage, не DB;
- DB — keys/hashes/metadata/vector candidate;
- никаких base64 masks в API.

## Provenance fields

По reference `AI_PROVENANCE_AND_REVIEW.md`. Все foreign object IDs tenant-safe.

## Geometry

Candidate поддерживает только geometry types прошедшего Prompt 18 task. Не открывай generic
«любой класс AI» без реализации.

## DB/migrations

Инварианты, indexes, soft/immutable state transitions. Нельзя принять candidate дважды и
создать duplicate Measurement.

## API read

Добавь bounded list/read candidate/run endpoints, но **не accept** до Prompt 21.
OpenAPI regen.

Документ `docs/stage2b/16-prediction-domain.md`.

STOP.


## Pipeline provenance

Run хранит не только один `model_id`, а ordered pipeline components. Для hybrid это может быть:

```text
Qwen3-VL-4B + LoRA adapter hash
→ structured localization schema v1
→ SAM2 checkpoint hash
→ mask vectorizer version
```

Нельзя потерять provenance промежуточного prompt JSON/mask; их hashes должны позволять воспроизвести candidate.
