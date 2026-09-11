# PROMPT 02 — Viewer scalability: измерить до переписывания

Stage 2B добавит тысячи candidate primitives. Сначала убери неопределённость viewer.

## Задача

Измерь текущую архитектуру на больших zoom/overlay counts и оформи ADR стратегии.

## Обязательные измерения

- A1/эталонный крупный лист на 100%, 266%, 400% при доступных DPR;
- page canvas pixel dimensions и оценка raw RGBA memory;
- размеры каждого из 4 canvas;
- pan frame timing / long tasks;
- render count PDF при чистом pan;
- overlay draw times на 1k / 5k / 10k / 25k primitives;
- current hit-test 1k / 5k / 10k / 25k;
- memory trend после 30 секунд pan (если API браузера ограничен — так и написать, не выдумывать).

## Архитектурное правило

Проверь тестом: `screen pointer → inverse camera transform → normalized coordinate` не зависит от
размеров raster canvas. Если сейчас зависит — это blocker и исправляется первым.

## Решение ADR должно быть условным, не догматичным

Предпочтительный инкрементальный путь:

1. viewport-sized vector overlays;
2. spatial culling/index;
3. перемерить;
4. только если base PDF остаётся bottleneck — tile/viewport PDF backend.

Не переходить на WebGL «потому что AI». Нужен benchmark.

Документ: `docs/stage2b/02-viewer-scalability.md` + новый ADR.
Код production renderer пока не переписывать, кроме тестового instrumentation при необходимости.

STOP.
