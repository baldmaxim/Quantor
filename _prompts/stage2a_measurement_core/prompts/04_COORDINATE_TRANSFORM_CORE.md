# PROMPT 04 — Coordinate Transform Core

Цель: сделать математику координат отдельным, проверяемым ядром до scale/UI.

## Реализуй backend pure module

Типы/функции минимум:

```text
NormalizedPoint
PdfDisplayPoint
PageGeometryValue
normalized_to_pdf_display()
pdf_display_to_normalized()
distance_pdf_points()
polyline_length_pdf_points()
polygon_area_pdf_points2()
```

Входы валидируются: finite, [0,1], корректное число точек, page dimensions > 0.

## Важное

Для legacy-v1 normalized coordinates **не применять rotation**. `display_width_pt` и
`display_height_pt` уже описывают отображаемую страницу.

Старые rotate helpers frontend не удалять: они могут понадобиться package-v2, но текущий
measurement path должен использовать правильное отображаемое пространство.

## Shared vectors

Создай один JSON fixture, например:

```text
tests/fixtures/coordinate_vectors.json
```

который читают и Python tests, и TypeScript tests. Включить:

- portrait / landscape;
- diagonal 3-4-5-like ratio;
- fractional dimensions;
- edges 0/1;
- roundtrip;
- invalid cases отдельными tests.

Frontend должен иметь pure transforms measurement geometry ↔ screen, используя существующий
viewer placement, а authoritative PDF-point math остаётся server-side.

## Precision

Не округлять промежуточную геометрию до UI precision. UI formatting — последний слой.
Если выбираешь Decimal/Numeric для outputs, явно зафиксируй boundary float→Decimal.

## Acceptance

Python и TS дают одинаковые ожидаемые test vectors; нет зависимости от browser DOM в core;
Stage 1 region overlay tests остаются зелёными.

STOP.
