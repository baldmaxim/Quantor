# PROMPT 11 — Kreo-like manual takeoff workspace

Собери инструменты в цельный workflow, не копируя дизайн Kreo.

## Left panel — Takeoff Items

Минимум:

- list current project items;
- create item;
- choose Count / Line / Polyline / Area;
- name;
- color/token;
- active item;
- per-current-scope total placeholder/value;
- archive, not destructive delete by default.

Не создавать строительные категории автоматически. Пользователь сам называет строку.

## Toolbar

Select / Pan / Count / Line / Polyline / Area / Scale.
Tool availability follows active item type.

## Right inspector

Selected Measurement:

- item/name;
- geometry type;
- source Manual;
- current authoritative value or «—»;
- scale calibration / warning;
- sheet/revision provenance;
- verification state;
- points debug only behind dev affordance, not main UX.

## State/data architecture

- server state → TanStack Query;
- ephemeral drawing state → local tool controller/store;
- camera stays imperative;
- no gigantic global Zustand object with every pointer coordinate;
- optimistic Count allowed, bounded reconciliation;
- error rolls optimistic geometry back visibly.

## Empty/error/loading states

Must handle:

- no PageGeometry;
- no scale;
- geometry extraction queued/failed;
- no TakeoffItem;
- no permissions;
- 409 edit conflict;
- network failure;
- stale revision.

## Mobile

Не пытайся сделать полноценный CAD-editor на 360px. На mobile viewer остаётся usable/readable;
manual drawing tools могут быть desktop/tablet-gated с честным сообщением, если это лучше UX.
Не ломать существующий PWA responsive shell.

## Tests

Playwright desktop flows: create item → calibrate → create measurement → reload → edit → delete.
Add permission/read-only reviewer/viewer cases.

STOP.
