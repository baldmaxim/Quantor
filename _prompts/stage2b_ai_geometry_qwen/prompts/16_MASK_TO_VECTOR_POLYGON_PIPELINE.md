# PROMPT 16 — Mask → polygon + holes

Сделай vectorization независимым от конкретной model family.

## Input contract

- probability/mask tile(s);
- tile↔sheet transform;
- frozen vectorization config version.

## Pipeline

- stitch/blend overlapping tiles deterministically;
- threshold from validation config;
- morphology only if validated and versioned;
- connected components;
- contour hierarchy outer/holes;
- small component filtering with threshold fixed on validation;
- simplification with bounded area change;
- normalized sheet coordinates;
- topology validation from Prompt 05.

## Tests

Synthetic masks:

- rectangle;
- concave polygon;
- one hole;
- multiple holes;
- hole near edge;
- tile boundary crossing;
- duplicate predictions in overlap;
- noisy island;
- self-intersection impossible/repair handling after simplification.

## Metrics against PlanSwift vectors

- net area error;
- boundary distance/F1;
- outer component recall;
- hole recall;
- invalid rate;
- vertex count/compression.

Raw mask remains evidence; vector is derived artifact with version/hash.

Документ `docs/stage2b/13-mask-to-polygon.md`.

STOP.
