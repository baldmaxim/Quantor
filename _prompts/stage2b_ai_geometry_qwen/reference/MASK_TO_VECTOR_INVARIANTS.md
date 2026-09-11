# Mask → Vector invariants

Модель заканчивает работу на probability/mask. Физическую величину модель не выдаёт.

## Polygon path

```text
probability map
→ threshold fixed from validation
→ connected components
→ contour hierarchy
→ outer rings + holes
→ simplify in geometry-aware tolerance
→ map tile pixels → sheet normalized
→ topology validation
→ PredictionCandidate
```

Инварианты:

- outer ring >= 3 unique points;
- hole >= 3 unique points;
- self-intersection = INVALID, не `0 m²`;
- hole должен лежать внутри outer ring и не пересекать его;
- overlapping/duplicate tile predictions deduplicate deterministically;
- simplify не имеет права менять площадь сверх заранее заданного tolerance;
- raw mask сохраняется как evidence artifact;
- candidate geometry хранит vectorization version/config/hash.

## Centerline path

```text
probability map
→ threshold
→ thinning/skeleton
→ graph endpoints/junctions
→ spur pruning
→ path merge
→ polyline simplification
→ tile dedup/stitch
→ normalized sheet coordinates
```

Pruning/simplification params выбираются на validation set. Test set их не настраивает.

## Coordinate truth

Model raster pixels — не физическая система координат. Quantor quantity считает только
после преобразования candidate в canonical normalized/PDF coordinate system и применения
существующей ScaleCalibration. Если масштаба нет — candidate существует, quantity unavailable.
