# Benchmark Stage 2A

Цель — доказать не «красивый UI», а математическую корректность измерительного ядра.

## Уровень A — pure geometry

Автоматические fixtures:

- horizontal line;
- vertical line;
- diagonal 3-4-5;
- polyline;
- rectangle polygon;
- arbitrary polygon;
- portrait page;
- landscape page;
- fractional page dimensions;
- boundary points 0/1;
- invalid points, NaN/Infinity;
- degenerate line/polygon;
- self-intersection policy.

## Уровень B — calibration

- 6000 mm reference dimension;
- input in m/cm/mm gives same canonical mm;
- calibration A→B and B→A gives same factor;
- new calibration does not mutate old measurement result;
- two scales on one sheet do not cross-contaminate.

## Уровень C — API/domain

- tenant isolation;
- permissions;
- cross-project IDs rejected;
- cross-sheet calibration rejected;
- optimistic concurrency;
- batch count bounded;
- deleted/archived records not aggregated;
- no N+1 by item count.

## Уровень D — frontend

- tool state machine;
- screen→normalized roundtrip;
- zoom/pan while draft exists;
- no double pdf.js render on one canvas;
- pointermove causes zero network writes;
- measurement layer does not force PDF render;
- keyboard controls.

## Уровень E — live real PDF

На известном чертеже выбрать минимум:

1. один подписанный горизонтальный размер;
2. один вертикальный;
3. одну диагональ/прямоугольник для независимой проверки;
4. count минимум 10 повторов;
5. area простого помещения/прямоугольника с известными размерами.

Сохранить точные expected values и источник листа в `docs/stage2a/live-acceptance.md`.

## Метрики

- absolute error;
- relative error;
- repeatability after reload;
- API latency for list/create/batch on real DB;
- overlay draw time for synthetic 1k / 5k / 10k primitives;
- memory/bundle impact.

Числа в отчёте — только измеренные. Не было измерения → писать «не измерено».
