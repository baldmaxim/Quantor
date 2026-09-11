# PROMPT 05 — Geometry validity + polygon holes

Это обязательный доменный шаг до PlanSwift slabs.

## 1. Self-intersection policy

Зафиксировать:

> self-intersecting polygon INVALID; quantity unavailable/error reason, никогда не 0 m².

Не делать silent auto-repair пользовательской геометрии.

Добавь deterministic validator с тестами:

- bow-tie;
- duplicate consecutive vertices;
- zero-length edges;
- collinear degenerate ring;
- normal concave polygon;
- near-touching but valid cases.

Если вводится Shapely/GEOS или другая dependency — сначала dependency/license ADR. Не тащи её
в browser bundle.

## 2. Holes

Эволюционируй Measurement geometry минимально и backward-compatible. Предпочтение:

```text
points = outer ring (как сейчас)
holes = [] | [ring1, ring2, ...]
```

но сначала сравни с GeoJSON-like full geometry и объясни выбор ADR.

Инварианты:

- holes только у polygon;
- каждый ring >= 3 unique points;
- hole внутри outer;
- hole не пересекает outer/другой hole;
- boundaries normalized [0,1];
- request limits bounded и для суммарного числа hole vertices;
- existing rows migrate без изменения quantity.

## 3. Quantity versioning

Existing polygon без holes продолжает давать прежний `area.v1` result/provenance.
Polygon с holes использует новый versioned rule (например `area_with_holes.v1`),
`outer - sum(holes)`, через canonical PDF geometry + stored calibration.

Никакого семантического «найди дверные проёмы»: holes здесь чистая геометрия.

## 4. Viewer editing

Manual polygon должен уметь хотя бы корректно **показать** holes. Полный UX рисования holes
можно оставить на AI/review prompt, но API/read path должен быть готов.

Миграция, OpenAPI regen, DB tests и benchmark обязательны.

Документ `docs/stage2b/05-geometry-validity-and-holes.md`.

STOP. Это контрольная точка владельца.
