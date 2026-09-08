# PROMPT 15 — Live acceptance на реальном PDF

Это обязательный «момент истины» Stage 2A.

## Fixture

Найди реальный fixture согласно `fixtures/README.md`. Предпочтительно ранее использованный
АР-пакет 77 листов / 383 regions.

Если fixture отсутствует — STOP с `LIVE_PDF=BLOCKED`, не придумывай цифры.

## Прогон

На живом стенде:

1. загрузить/импортировать fixture;
2. geometry job должен быть взят **worker**, не API inline (если production path такой);
3. проверить page count и PageGeometry;
4. открыть лист;
5. выбрать подписанный известный размер и вручную откалибровать;
6. измерить этот же размер повторно Line;
7. измерить независимый вертикальный размер;
8. измерить диагональ/прямоугольник, чтобы поймать старую `units_per_normalized` ошибку;
9. создать Polygon area на геометрии с известными сторонами;
10. поставить минимум 10 Count points;
11. reload/browser reopen и проверить persistence/values;
12. edit one vertex → authoritative value changes predictably;
13. create second calibration on same sheet and доказать, что старое measurement не перепривязалось молча;
14. проверить viewer pan/zoom и recognition layer одновременно с measurement layer.

## Evidence

`docs/stage2a/live-acceptance.md` должен содержать:

- exact document/sheet identifiers or safe labels;
- known dimensions and откуда они взяты;
- expected vs actual;
- absolute/relative error;
- screenshots/overlay references только если реально созданы;
- worker/job timings;
- API/browser errors;
- environment.

Не скрывать отклонения. Если ошибка > tolerance — gate FAIL, не «примерно работает».

## Feature flag

На этом prompt `takeoff.manual` всё ещё не включать глобально. Это делает Prompt 16 после
полного acceptance audit.

STOP.
