# PROMPT 02 — Контракты MEP EvidenceGraph / NetworkGraph / BOQ

Создай строгие versioned JSON contracts для инженерного эксперимента. Не превращай MEP в набор произвольных полилиний.

Нужны три контракта:

## A. `MepEvidenceGraph v0.1`
Хранит только то, что распознано/извлечено из стадии П:
- source document/page/view/floor/system/revision/scale;
- architecture anchors/rooms/shafts/risers if observed;
- symbols/equipment/terminals/panels/fixtures;
- text labels, marks, diameters, elevations, dimensions, schedules;
- raw vector/raster geometry;
- observed route fragments;
- evidence refs, confidence, conflicts, unresolved.

## B. `MepNetworkGraph v0.1`
Граф физической системы:
- `nodes`: source/equipment/terminal/riser/junction/device/panel/fixture;
- `ports`: medium/system/direction/size/elevation;
- `edges`: route polyline + system + size + material + elevation + slope where applicable;
- connectivity, branch/junction semantics;
- accessories/fittings/valves;
- constraints and validation issues;
- provenance per field: observed / rd_prior_inferred / rule_derived / retrieved / human_confirmed / unresolved;
- confidence per node/edge/attribute;
- source-space transform and metric-scale status.

## C. `MepBoq v0.1`
- item id / normalized work code;
- system/subsystem;
- quantity kind (count/length/area/volume/mass);
- unit;
- quantity;
- quantity provenance;
- source graph ids;
- pricing context (date, region, currency, building class, brand tier) separately;
- work rate, material rate, total only after pricing stage;
- rate provenance/confidence;
- review flags.

Добавь validators и adversarial tests: disconnected edge, incompatible ports, missing scale, impossible unit, duplicate stable id, quantity without source, price without date/currency, inferred field falsely marked observed.

Сделай JSON examples для одного малого ВК-контура: стояк → магистраль → два ответвления → два прибора.
