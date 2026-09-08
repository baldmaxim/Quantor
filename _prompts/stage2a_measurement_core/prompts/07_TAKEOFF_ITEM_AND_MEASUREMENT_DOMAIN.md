# PROMPT 07 — TakeoffItem + Measurement domain

Теперь создаём настоящую область ручного takeoff. `Region` не трогать.

## ADR

Зафиксируй lifecycle/provenance Measurement и scope TakeoffItem.

### TakeoffItem

Это рабочая строка takeoff, не сметная позиция и не classification ontology.
Минимум:

- project ownership;
- name/code optional;
- geometry type;
- display unit derived/validated;
- visual token/color;
- order/archive;
- creator/timestamps.

Не строить рекурсивную BOQ-иерархию без требования Stage 2A.

### Measurement

Хранит нормализованную geometry **отдельно от Region**.

Validation by GeometryType:

```text
COUNT     exactly 1 point
LINE      exactly 2 points
POLYLINE  >= 2 points
POLYGON   >= 3 points
```

- finite [0,1];
- geometry canonicalization documented;
- source Stage 2A writes only MANUAL;
- explicit `scale_calibration_id` for measurements that need physical units when available;
- optimistic concurrency version;
- creator/updater;
- deletion policy explicit (soft delete or auditable alternative).

## Revision safety

Measurement ties to Sheet → DocumentRevision. Не смешивай автоматически старую и новую
ревизии в один total. Project-level TakeoffItem допустим, но API totals должны иметь явный
revision/sheet scope и не складывать разные revisions магически.

## Cross-entity invariants

- item.project == sheet.revision.document.project;
- calibration.sheet == measurement.sheet;
- geometry_type item/measurement consistent;
- archived item cannot accept new measurements;
- source cannot be spoofed by public manual endpoint.

## Migration/tests

Migration reversible. Add indexes by sheet/item and active records. Не класть огромный binary
в JSON. Geometry JSONB допустима на Stage 2A; PostGIS geometry не добавлять «потому что есть PostGIS»
без query need.

Покрыть DB constraints + service validation + tenant isolation.

STOP. UI ещё не строить.
