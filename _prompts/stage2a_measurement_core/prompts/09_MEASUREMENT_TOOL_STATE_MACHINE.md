# PROMPT 09 — Pure Measurement Tool State Machine

До отрисовки создай чистое клиентское ядро взаимодействия.

## Modes

```text
select
pan
scale
count
line
polyline
polygon
```

Scale можно переиспользовать из Prompt 06, но state transitions должны быть согласованы.

## Draft lifecycle

State machine получает semantic events:

```text
pointerDown(normalizedPoint)
pointerMove(normalizedPoint)
finish
cancel
backspace
selectMeasurement
startVertexDrag
moveVertex
finishVertexDrag
```

Она не знает DOM, API, TanStack Query и pdf.js.

## Keyboard

- Esc cancel;
- Enter finish polyline/polygon;
- Backspace removes last draft point;
- Delete selected measurement handled above state machine with confirmation policy;
- Space temporary pan handled without losing current draft.

## Geometry constraints

- line completes on second click;
- polygon cannot finish <3;
- no duplicate accidental last point;
- clamp/reject outside-page semantics explicit;
- no NaN/Infinity;
- draft survives zoom/pan because stored normalized, not screen pixels.

## Tests

Table-driven tests for every transition, cancel path and invalid sequence.
No snapshots as substitute for state assertions.

STOP. Не подключай API пока state machine не зелёная.
