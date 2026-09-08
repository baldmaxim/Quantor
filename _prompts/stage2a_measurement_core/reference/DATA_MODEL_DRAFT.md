# Черновик доменной модели Stage 2A

Это ориентир, не приказ копировать имена полей. Claude обязан свериться с текущими моделями
и оформить отклонения ADR.

## PageGeometry — 1:1 с Sheet

Рекомендуемые данные:

```text
id / sheet_id
coordinate_space = pdf_display_points_top_left
display_width_pt
display_height_pt
pdf_rotation
media_box
crop_box
parser_name
parser_version
source_revision_sha256
geometry_fingerprint
extracted_at
```

`Sheet.width_px/height_px` не удалять: это legacy raster metadata. Просто не использовать в QTO.

## ScaleCalibration — immutable

```text
id
sheet_id
scope_kind: sheet | region
scope_polygon_norm?       # future/local scale readiness
point_a_norm
point_b_norm
known_distance_mm
page_distance_pt
mm_per_pt
source: manual | detected_dimension | imported
verification_state
created_by
created_at
supersedes_id?
```

Для Stage 2A реально создаётся только `source=manual`.

## TakeoffItem

Семантическая строка рабочего takeoff, например «Перегородка ПГ-1» или «Дверь Д1».
Не превращать её в сметную позицию.

```text
id
project_id
name
code?
geometry_type: count | line | polyline | polygon
display_unit
color/token
sort_order
archived_at?
created_by
created_at / updated_at
```

Stage 2A не обязан делать рекурсивное дерево папок. Лучше устойчивый плоский список, чем
недоделанная иерархия.

## Measurement

```text
id
takeoff_item_id
sheet_id
points_norm
source: manual | ai | imported
scale_calibration_id?
verification_state
confidence?
version                 # optimistic concurrency
created_by / updated_by
created_at / updated_at
deleted_at?             # если выбран soft delete
```

Stage 2A write API принимает только `source=manual`. AI enum может существовать как контракт,
но endpoint не должен позволять клиенту выдать ручное измерение за AI или наоборот.

## Quantity

На Stage 2A не материализовать сложную BOQ-схему без необходимости. Допустим безопасный
вариант: authoritative deterministic calculation service возвращает `QuantityResult` с:

```text
value
unit
rule_key
rule_version
measurement_id(s)
scale_calibration_id(s)
input_fingerprint
verification
```

Если Claude считает, что quantity необходимо хранить, сначала отдельный ADR: что даёт
materialization, как supersede/recompute работает и почему derived-on-read недостаточно.

Главный инвариант остаётся:

```text
Region != Measurement != Quantity
```
