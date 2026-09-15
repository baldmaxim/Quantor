"""Метрики вектора против векторной разметки PlanSwift — в рабочих пикселях листа.

На одном листе масштаб общий, поэтому доля ошибки площади в пикселях равна доле ошибки
физической площади; метры здесь не нужны и не считаются.

- **Нетто-площадь листа:** Σ(внешнее − отверстия) годных многоугольников против той же суммы по
  разметке. Недействительный многоугольник площади не даёт — как в портале. Листы без плиты в
  разметке дают отдельную метрику: ложная площадь в долях площади листа (раньше такие листы
  выпадали из оценки, промт 11).
- **Полнота плит:** плита разметки найдена, если прогноз покрывает ≥ `coverage_to_recall` её
  нетто-площади. **Точность:** многоугольник прогноза подтверждён, если ≥ той же доли его площади
  лежит в плитах разметки.
- **Полнота отверстий:** отверстие найденной плиты найдено, если ≥ той же доли его площади
  прогноз оставил пустой. Отверстия меньше `min_hole_px` не считаются — их заливает и векторизация.
- **Граница:** точки через `boundary_sample_px` вдоль колец; расстояние до ближайшего отрезка
  другой стороны; F1 при допуске `boundary_tolerance_px`.
- **Недействительные** — доля и коды; **вершины** — до и после упрощения.

Покрытие считается растеризацией по центрам клеток шага `metric_stride_px` (чёт-нечет по кольцам).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

from quantor_vision.vector.polygonize import Point, Ring, VectorConfig, signed_area

Intervals = list[tuple[int, int]]
Rows = dict[int, Intervals]
Polygon = list[Ring]


def net_area(polygon: Polygon) -> float:
    return abs(signed_area(polygon[0])) - sum(abs(signed_area(hole)) for hole in polygon[1:])


def rasterize(polygon: Polygon, stride: int) -> Rows:
    """Клетки, чей центр внутри многоугольника: строка → отсортированные полуинтервалы столбцов."""
    edges = [
        (ring[index], ring[(index + 1) % len(ring)])
        for ring in polygon
        for index in range(len(ring))
        if ring[index][1] != ring[(index + 1) % len(ring)][1]
    ]
    if not edges:
        return {}
    top = min(min(a[1], b[1]) for a, b in edges)
    bottom = max(max(a[1], b[1]) for a, b in edges)
    rows: Rows = {}
    for row in range(max(0, math.floor(top / stride - 0.5)), math.ceil(bottom / stride) + 1):
        center = (row + 0.5) * stride
        crossings = sorted(
            a[0] + (center - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            for a, b in edges
            if (a[1] <= center) != (b[1] <= center)
        )
        intervals: Intervals = []
        for left, right in zip(crossings[0::2], crossings[1::2], strict=False):
            start = max(0, math.ceil(left / stride - 0.5))
            stop = math.floor(right / stride - 0.5) + 1
            if stop > start:
                intervals.append((start, stop))
        if intervals:
            rows[row] = intervals
    return rows


def _merge(intervals: Intervals) -> Intervals:
    merged: Intervals = []
    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged


def union(parts: list[Rows]) -> Rows:
    rows: dict[int, Intervals] = {}
    for part in parts:
        for row, intervals in part.items():
            rows.setdefault(row, []).extend(intervals)
    return {row: _merge(intervals) for row, intervals in rows.items()}


def cells(rows: Rows) -> int:
    return sum(stop - start for intervals in rows.values() for start, stop in intervals)


def overlap(first: Rows, second: Rows) -> int:
    total = 0
    for row, intervals in first.items():
        other = second.get(row)
        if not other:
            continue
        i = j = 0
        while i < len(intervals) and j < len(other):
            start = max(intervals[i][0], other[j][0])
            stop = min(intervals[i][1], other[j][1])
            total += max(0, stop - start)
            if intervals[i][1] < other[j][1]:
                i += 1
            else:
                j += 1
    return total


def boundary_samples(polygon: Polygon, step: float) -> list[Point]:
    samples: list[Point] = []
    for ring in polygon:
        for index in range(len(ring)):
            (x0, y0), (x1, y1) = ring[index], ring[(index + 1) % len(ring)]
            pieces = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / step))
            samples.extend(
                (x0 + (x1 - x0) * k / pieces, y0 + (y1 - y0) * k / pieces) for k in range(pieces)
            )
    return samples


class SegmentIndex:
    """Отрезки колец в сетке ячеек размером `cell`: ближайший ищется в соседних ячейках."""

    def __init__(self, polygons: list[Polygon], cell: float) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[tuple[Point, Point]]] = {}
        for polygon in polygons:
            for ring in polygon:
                for index in range(len(ring)):
                    a, b = ring[index], ring[(index + 1) % len(ring)]
                    for key in self._keys(a, b):
                        self.cells.setdefault(key, []).append((a, b))

    def _keys(self, a: Point, b: Point) -> list[tuple[int, int]]:
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        return [
            (i, j)
            for i in range(math.floor(x0 / self.cell), math.floor(x1 / self.cell) + 1)
            for j in range(math.floor(y0 / self.cell), math.floor(y1 / self.cell) + 1)
        ]

    def distance(self, point: Point) -> float:
        """До ближайшего отрезка, но не больше `cell` (дальше — «не рядом»)."""
        ci, cj = math.floor(point[0] / self.cell), math.floor(point[1] / self.cell)
        best = self.cell
        for i in (ci - 1, ci, ci + 1):
            for j in (cj - 1, cj, cj + 1):
                for a, b in self.cells.get((i, j), ()):
                    best = min(best, _segment_distance(point, a, b))
        return best


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    t = min(1.0, max(0.0, t))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


@dataclass(slots=True)
class VectorMetrics:
    config: VectorConfig
    page_errors: list[float] = field(default_factory=list)
    false_area: list[float] = field(default_factory=list)
    truth_polygons: int = 0
    recalled_polygons: int = 0
    predicted_polygons: int = 0
    supported_polygons: int = 0
    truth_holes: int = 0
    recalled_holes: int = 0
    boundary_hits_pred: int = 0
    boundary_pred: int = 0
    boundary_hits_truth: int = 0
    boundary_truth: int = 0
    distances: list[float] = field(default_factory=list)
    invalid: Counter[str] = field(default_factory=Counter)
    total_polygons: int = 0
    lattice_vertices: int = 0
    output_vertices: int = 0

    def add_page(
        self,
        predicted: list[Polygon],
        truth: list[Polygon],
        *,
        page_area_px: float,
        invalid_codes: list[str],
        lattice_vertices: int,
        output_vertices: int,
    ) -> dict[str, float | int | None]:
        """`predicted` — только годные многоугольники; недействительные — кодами."""
        config = self.config
        stride = config.metric_stride_px
        self.total_polygons += len(predicted) + len(invalid_codes)
        self.invalid.update(invalid_codes)
        self.lattice_vertices += lattice_vertices
        self.output_vertices += output_vertices

        predicted_area = sum(net_area(polygon) for polygon in predicted)
        truth_area = sum(net_area(polygon) for polygon in truth)
        page: dict[str, float | int | None] = {
            "predicted_area_px": predicted_area,
            "truth_area_px": truth_area,
            "area_error": None,
            "false_area_of_page": None,
        }
        if truth_area > 0:
            error = abs(predicted_area - truth_area) / truth_area
            self.page_errors.append(error)
            page["area_error"] = error
        else:
            share = predicted_area / page_area_px if page_area_px else 0.0
            self.false_area.append(share)
            page["false_area_of_page"] = share

        predicted_rows = [rasterize(polygon, stride) for polygon in predicted]
        truth_rows = [rasterize(polygon, stride) for polygon in truth]
        predicted_union = union(predicted_rows)
        truth_union = union(truth_rows)
        for polygon, rows in zip(truth, truth_rows, strict=True):
            area = cells(rows)
            if not area:
                continue
            self.truth_polygons += 1
            if overlap(rows, predicted_union) < config.coverage_to_recall * area:
                continue
            self.recalled_polygons += 1
            for hole in polygon[1:]:
                if abs(signed_area(hole)) < config.min_hole_px:
                    continue
                hole_rows = rasterize([hole], stride)
                hole_cells = cells(hole_rows)
                if not hole_cells:
                    continue
                self.truth_holes += 1
                empty = hole_cells - overlap(hole_rows, predicted_union)
                if empty >= config.coverage_to_recall * hole_cells:
                    self.recalled_holes += 1
        for rows in predicted_rows:
            area = cells(rows)
            if not area:
                continue
            self.predicted_polygons += 1
            if overlap(rows, truth_union) >= config.coverage_to_recall * area:
                self.supported_polygons += 1

        cap = max(config.boundary_tolerance_px * 4, 1.0)
        truth_index = SegmentIndex(truth, cap)
        predicted_index = SegmentIndex(predicted, cap)
        for polygon in predicted:
            for point in boundary_samples(polygon, config.boundary_sample_px):
                distance = truth_index.distance(point)
                self.distances.append(distance)
                self.boundary_pred += 1
                self.boundary_hits_pred += distance <= config.boundary_tolerance_px
        for polygon in truth:
            for point in boundary_samples(polygon, config.boundary_sample_px):
                self.boundary_truth += 1
                hit = predicted_index.distance(point) <= config.boundary_tolerance_px
                self.boundary_hits_truth += hit
        return page

    def summary(self) -> dict[str, object]:
        def ratio(part: int, whole: int) -> float | None:
            return part / whole if whole else None

        def quantile(values: list[float], share: float) -> float | None:
            ordered = sorted(values)
            return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else None

        precision = ratio(self.boundary_hits_pred, self.boundary_pred)
        recall = ratio(self.boundary_hits_truth, self.boundary_truth)
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else 0.0
        )
        return {
            "pages_with_slab": len(self.page_errors),
            "page_area_error_median": statistics.median(self.page_errors)
            if self.page_errors
            else None,
            "page_area_error_p90": quantile(self.page_errors, 0.9),
            "page_area_error_max": max(self.page_errors) if self.page_errors else None,
            "pages_without_slab": len(self.false_area),
            "false_area_of_page_max": max(self.false_area) if self.false_area else None,
            "polygon_recall": ratio(self.recalled_polygons, self.truth_polygons),
            "polygon_precision": ratio(self.supported_polygons, self.predicted_polygons),
            "hole_recall": ratio(self.recalled_holes, self.truth_holes),
            "truth_polygons": self.truth_polygons,
            "truth_holes": self.truth_holes,
            "boundary_precision": precision,
            "boundary_recall": recall,
            "boundary_f1": f1,
            "boundary_tolerance_px": self.config.boundary_tolerance_px,
            "boundary_distance_median_px": statistics.median(self.distances)
            if self.distances
            else None,
            "boundary_distance_p90_px": quantile(self.distances, 0.9),
            "invalid_rate": ratio(sum(self.invalid.values()), self.total_polygons),
            "invalid_codes": dict(sorted(self.invalid.items())),
            "polygons": self.total_polygons,
            "vertices_lattice": self.lattice_vertices,
            "vertices_output": self.output_vertices,
            "vertex_compression": ratio(self.lattice_vertices, self.output_vertices),
        }
