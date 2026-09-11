# PROMPT 15 — Masonry centerline segmentation baseline

Вторая независимая задача: PlanSwift кладка даёт polyline centerline ground truth.

## Model target

Обучить отдельный small semantic model, не переиспользовать slab head без доказательства.
Output — centerline probability/heatmap.

Проверь минимум две target/loss стратегии на validation, но test не трогать:

- thin/buffered binary centerline + Dice/Focal/BCE combination;
- distance/soft target, если первая страдает от class imbalance.

## Important

Не считать длину по площади маски/толщине полосы. Конечный QTO path:

```text
probability → skeleton/vector polyline → existing length.v1
```

## Evaluation raw

- pixel/heatmap metrics как диагностические;
- centerline tolerance metric preliminary;
- latency/memory;
- false-positive on text/dimension lines — отдельная error bucket.

Документ `docs/stage2b/12-masonry-baseline.md`.

STOP.
