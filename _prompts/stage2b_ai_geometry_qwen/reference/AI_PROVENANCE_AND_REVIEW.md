# AI provenance и human review

## Prediction до проверки не является рабочим Measurement

Рекомендуемый домен:

```text
VisionPredictionRun (immutable provenance)
  └── PredictionCandidate × N
          state = pending | accepted | rejected
          raw geometry + confidence + class/task
          raw mask artifact reference
          └── accepted_measurement_id ?
```

После accept/edit trusted service создаёт:

```text
Measurement
source = ai
points/holes = accepted geometry
metadata.prediction_candidate_id = ...
```

Manual HTTP endpoint по-прежнему не может прислать `source=ai`.

## Минимальный provenance run

- project/document revision/sheet ids;
- model family/id/version;
- weights SHA-256;
- code/experiment config version;
- input raster transform and artifact SHA-256;
- preprocessing config;
- threshold/vectorization config;
- dataset/training run reference, если применимо;
- device/runtime versions;
- started/finished timestamps;
- output mask/vector artifact hashes.

## Human correction signal

Original candidate immutable. Accepted/edit geometry — отдельный Measurement. Поэтому можно
посчитать:

```text
model geometry ↔ human accepted geometry
```

и сохранить correction metrics без потери исходного предсказания.

## Quantity preview

UI может показать candidate quantity preview, используя тот же deterministic Quantity Engine,
но preview явно помечен «AI, не принято» и не входит в рабочий TakeoffItem total. После accept
обычный Measurement попадает в существующий total.


## Hybrid provenance

For Qwen→SAM keep hashes/references for every stage:

```text
input raster artifact
→ Qwen base + adapter/merged weights + decoding config
→ structured localization JSON artifact/hash
→ SAM checkpoint + prompt transform
→ probability/mask artifact
→ vectorizer config/hash
→ PredictionCandidate
```

This is required to attribute a geometry error to localization, segmentation or vectorization rather than treating “AI” as one opaque box.
