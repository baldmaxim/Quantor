# PROMPT 17 — Mask/heatmap → centerline polyline

Vectorization masonry отдельно от polygon path.

## Pipeline

- threshold fixed on validation;
- thinning/skeletonization;
- graph endpoints + junctions;
- short-spur pruning;
- merge degree-2 paths;
- simplify while controlling length error;
- stitch tile overlap;
- deduplicate parallel/duplicate paths;
- normalized sheet coordinates.

Не использовать physical meters для pruning, если у sheet нет scale. Pruning config задаётся
в normalized/raster units и versioned. Quantity later may be unavailable without scale.

## Synthetic tests

- straight;
- L/T/X junctions;
- rectangle loop;
- near-touch lines;
- gap;
- noise spur;
- tile boundary;
- overlapping tile duplicate.

## GT metrics

Нужен matching predicted paths ↔ GT lines и page-total length metric. Tolerance определена до
test и записана в experiment config.

Документ `docs/stage2b/14-mask-to-centerline.md`.

STOP.
