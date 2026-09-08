# PROMPT 12 — Deterministic Quantity Engine v1

Теперь разрешён первый настоящий QTO calculation — только count/length/area.

## Rules v1

```text
count.v1
length.v1
area.v1
```

### Count

COUNT measurement = 1 `pcs`.

### Length

LINE/POLYLINE:

1. normalized → PDF display points;
2. sum Euclidean segment lengths in pt;
3. multiply by explicit `mm_per_pt` calibration;
4. canonical = mm;
5. display convert to m without changing stored/source math.

### Area

POLYGON:

1. normalized → PDF display points;
2. calculate polygon area in pt² (shoelace or justified robust equivalent);
3. validate self-intersection/degenerate policy;
4. multiply by `mm_per_pt²`;
5. canonical = mm²;
6. display = m².

## Never

- calculate directly in normalized coordinates;
- infer scale from page size;
- use `Sheet.width_px`;
- accept factor supplied by client;
- let frontend value become source of truth;
- round before final formatting.

## QuantityResult contract

Return at least:

```text
value
unit
canonical_value
canonical_unit
rule_key
rule_version
measurement_id
page_geometry_fingerprint
scale_calibration_id? / calibration fingerprint
input_fingerprint
verification_state
```

Trace must be sufficient to reproduce.

## Derived vs materialized

Default preference Stage 2A: derived authoritative service, not premature BOQ snapshot table.
Если материализация нужна — сначала ADR and supersession/recompute semantics.

## Aggregate

TakeoffItem total can sum compatible current-scope QuantityResults. Scope must be explicit;
не складывать две revisions одного document автоматически.

## Frontend preview

Можно mirror pure formula in TS for responsive preview, but saved/server result is authoritative.
Shared test vectors should detect drift.

## Tests

- known exact geometries;
- calibration unit conversions;
- old measurement bound to old calibration remains same after new default;
- no-scale length/area returns typed unavailable/error, not zero;
- count works without scale;
- rule version/fingerprint stable;
- repeatability after reload.

STOP.
