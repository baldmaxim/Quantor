# PROMPT 04 — Spatial index для тысяч векторных объектов

Текущий `hitTestMeasurements` линейный. AI overlay увеличит порядок величины.

## Требование

Ввести абстракцию spatial index без изменения публичной семантики hit-test.

Выбери implementation после microbenchmark:

- простая uniform grid / quadtree собственной реализации;
- либо маленькая permissive dependency (например R-tree), но сначала license/size audit.

Критерий выбора — не популярность, а latency/build/update cost на характерных данных.

## Index semantics

- bbox хранится в normalized sheet coordinates;
- query строится из screen tolerance, преобразованной обратно в normalized extent;
- final precise hit-test остаётся существующим geometry-aware algorithm;
- selected/dragging geometry обновляет index без полного rebuild, где разумно;
- deleted/hidden layers не остаются candidates;
- overlapping shapes сохраняют правило smallest extent.

Добавь generic index, чтобы позже его использовал AI candidate layer.

## Benchmarks

1k / 5k / 10k / 25k objects:

- build;
- query median/p95;
- update one object;
- memory estimate.

Не оптимизируй серверный API в этом промте.

Документ `docs/stage2b/04-spatial-index.md`.

STOP.
