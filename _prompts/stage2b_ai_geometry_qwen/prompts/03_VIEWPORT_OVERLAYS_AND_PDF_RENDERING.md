# PROMPT 03 — Viewport-sized overlays и условный PDF tile backend

Реализуй решение ADR из Prompt 02.

## Часть A — vector overlays

Regions, scale draft, measurements и будущий AI-candidate layer не должны требовать full-page
canvas на большом zoom.

Сделай viewport-sized overlay surface(s):

- canvas размером области просмотра в device pixels;
- drawing transform из camera state + sheet coordinates;
- clipping к viewport;
- overlay coordinates остаются normalized;
- pointer coordinate truth не меняется;
- никакого API/React write на pointermove;
- pan не требует PDF rerender.

Не смешивай domain layers в одну сущность; можно совместно оптимизировать surface только если
слои логически остаются независимы и тестируются отдельно.

## Часть B — base PDF

После A повтори benchmark Prompt 02.

Если live/perf budget проходит — **не внедряй tile PDF сейчас**, оставь extension point и отчёт.
Если не проходит — расширь `RenderBackend` viewport/tile primitive и реализуй pdf.js rendering
только видимой области + overscan/cache. Не копируй геометрию камеры во второй источник истины.

## Live regression

Обязательна живая проверка листа @266% после `git pull`:

- 30 секунд pan;
- no white flashes / stale fragments;
- regions/measurements remain aligned;
- no repeated PDF render on pure pan;
- CPU settles after pan;
- coordinate hit remains exact.

Запиши measured before/after в `docs/stage2b/03-viewer-runtime.md`.

STOP. Если live check невозможно выполнить в этой среде — пометь gate BLOCKED, не PASS.
