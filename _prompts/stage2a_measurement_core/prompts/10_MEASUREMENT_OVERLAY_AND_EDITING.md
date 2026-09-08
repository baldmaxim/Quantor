# PROMPT 10 — Measurement Canvas overlay + selection/editing

Добавь отдельный measurement overlay поверх recognition overlay.

## Не смешивать

```text
PDF base canvas
Recognition overlay canvas
Measurement overlay canvas
Interaction handles (минимально)
```

`Region` painter не расширять флагом «measurement=true». Новый слой/типы.

## Render

Поддержать:

- Count markers;
- Line;
- Polyline;
- Polygon fill/stroke;
- draft geometry;
- selected/hovered style;
- vertex handles selected item;
- item color token.

Canvas2D по умолчанию. WebGL только после Prompt 14 benchmark.

## Interaction

- hit testing current sheet;
- smallest/nearest primitive semantics documented;
- selection;
- drag vertex with local preview;
- API update only on drag-end;
- Delete;
- creation from state machine;
- pan/zoom independent.

## PDF render invariant

Добавь regression test: изменение draft/hover/selection/vertex position не вызывает новую
pdf.js page render. Existing `maxLive===1` equivalent must remain green.

## Scaling/DPR

Measurement overlay pixel alignment follows same `SheetPlacement` and DPR semantics as recognition.
No use of recognition raster `width_px`.

## Tests

- render primitives;
- hit test at multiple zooms;
- selection after pan;
- edit persists normalized points;
- pointermove no network;
- layer unmount cleanup;
- thousands synthetic elements must at least function before performance optimization.

STOP.
