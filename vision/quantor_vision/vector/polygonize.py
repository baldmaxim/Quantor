"""Маска листа → многоугольники с отверстиями в нормализованных координатах листа.

```text
маска (bool, рабочие пиксели)
→ рёбра пикселей на границе            плита слева по ходу обхода
→ обход колец                          на диагональном касании — поворот к своей клетке
→ углы (коллинеарные вершины убраны)   площадь точно равна числу пикселей
→ отверстия к наименьшему охватывающему внешнему кольцу
→ малые отверстия заливаются, малые области отбрасываются — со счётчиками
→ разведение «перетяжек»               вершина, где кольцо касается себя или отверстия
→ упрощение Дугласа — Пекера            изменение нетто-площади ≤ max_area_change_ratio
→ нормализованные координаты листа
→ проверка валидности промта 05         недействительный — INVALID с кодом, не 0 м²
```

Обход пиксельных рёбер с поворотом на диагональном касании и привязка отверстий по вложенности
взяты из `area_candidate_geometry_v001.py` проекта SU10 (передача 2026-09-14) и переписаны без
numpy. Добавлено то, без чего контур не проходит проверку портала: разведение перетяжек (касание
считается пересечением, ADR-0026), упрощение с ограничением площади и откат допуска, если
упрощённый контур недействителен.

Модель здесь не нужна и не знается: вход — бинарная маска, выход — геометрия с версией настройки.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, fields

import torch
from torch.nn import functional

from quantor_vision.vector.validity import validate_polygon

VECTORIZER_VERSION = "vectorize_polygon_v1"

Lattice = tuple[int, int]
Point = tuple[float, float]
Ring = list[Point]

# Направления рёбер: +x, +y, −x, −y. Плита всегда слева от ребра в координатах (x, y) —
# так внешнее кольцо имеет положительную ориентированную площадь, отверстие — отрицательную.
DIRECTIONS: tuple[Lattice, ...] = ((1, 0), (0, 1), (-1, 0), (0, -1))
# Начало ребра относительно пикселя (x, y) для верхней, правой, нижней и левой стороны.
OFFSETS: tuple[Lattice, ...] = ((0, 0), (1, 0), (1, 1), (0, 1))
# Порядок выбора следующего ребра: поворот к своей клетке, прямо, от неё, назад. На диагональном
# касании это разделяет клетки, соприкасающиеся только углом (4-связность плиты).
TURNS = (1, 0, 3, 2)


class TooComplexError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VectorConfig:
    """Настройка векторизации. Меняется только на val; test получает её замороженной по хешу."""

    version: str = VECTORIZER_VERSION
    # Пиксель листа — плита, если доля покрывающих его тайлов с плитой ≥ порога.
    vote_threshold: float = 0.5
    # Морфология не применяется: на val её польза не проверена.
    morphology: str = "none"
    min_component_px: int = 256
    min_hole_px: int = 64
    simplify_tolerance_px: float = 1.5
    min_tolerance_px: float = 0.25
    max_area_change_ratio: float = 0.01
    pinch_nudge_px: float = 0.05
    edge_budget: int = 4_000_000
    metric_stride_px: int = 2
    boundary_tolerance_px: float = 3.0
    boundary_sample_px: float = 1.0
    coverage_to_recall: float = 0.5

    @classmethod
    def with_overrides(cls, pairs: dict[str, str]) -> VectorConfig:
        """Настройки по умолчанию с заменами из `--set ключ=значение`; неизвестный ключ — отказ."""
        base = cls()
        known = {item.name for item in fields(cls)} - {"version"}
        unknown = sorted(set(pairs) - known)
        if unknown:
            raise ValueError(f"неизвестные настройки векторизации: {unknown}")

        def number(name: str, current: float) -> float:
            return float(pairs[name]) if name in pairs else current

        def integer(name: str, current: int) -> int:
            return int(pairs[name]) if name in pairs else current

        return cls(
            vote_threshold=number("vote_threshold", base.vote_threshold),
            morphology=pairs.get("morphology", base.morphology),
            min_component_px=integer("min_component_px", base.min_component_px),
            min_hole_px=integer("min_hole_px", base.min_hole_px),
            simplify_tolerance_px=number("simplify_tolerance_px", base.simplify_tolerance_px),
            min_tolerance_px=number("min_tolerance_px", base.min_tolerance_px),
            max_area_change_ratio=number("max_area_change_ratio", base.max_area_change_ratio),
            pinch_nudge_px=number("pinch_nudge_px", base.pinch_nudge_px),
            edge_budget=integer("edge_budget", base.edge_budget),
            metric_stride_px=integer("metric_stride_px", base.metric_stride_px),
            boundary_tolerance_px=number("boundary_tolerance_px", base.boundary_tolerance_px),
            boundary_sample_px=number("boundary_sample_px", base.boundary_sample_px),
            coverage_to_recall=number("coverage_to_recall", base.coverage_to_recall),
        )

    def validate(self) -> None:
        if self.version != VECTORIZER_VERSION:
            raise ValueError(f"версия настройки {self.version!r} ≠ {VECTORIZER_VERSION!r}")
        if self.morphology != "none":
            raise ValueError("морфология не поддержана: её польза на val не проверена")
        if not 0 < self.vote_threshold <= 1:
            raise ValueError("vote_threshold вне (0, 1]")
        if not 0 < self.pinch_nudge_px < 0.5:
            raise ValueError("pinch_nudge_px вне (0, 0,5)")
        if self.metric_stride_px < 1 or self.boundary_sample_px <= 0:
            raise ValueError("шаги метрик должны быть положительны")

    def sha256(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PageFrame:
    """Рабочие пиксели листа → нормализованные координаты: x_n = x · downsample / source_width."""

    downsample: int
    source_width: int
    source_height: int

    def normalize(self, ring: Ring) -> list[list[float]]:
        return [
            [x * self.downsample / self.source_width, y * self.downsample / self.source_height]
            for x, y in ring
        ]


@dataclass(frozen=True, slots=True)
class LatticeRing:
    corners: list[Lattice]
    # Направление ребра, приходящего в каждый угол.
    incoming: list[int]


@dataclass(frozen=True, slots=True)
class VectorPolygon:
    outer: list[list[float]]
    holes: list[list[list[float]]]
    status: str
    issue: str | None
    net_area_px: float
    lattice_vertices: int
    output_vertices: int
    tolerance_px: float


@dataclass(frozen=True, slots=True)
class PageVectors:
    polygons: list[VectorPolygon]
    boundary_edges: int
    dropped_components: int
    filled_holes: int
    # Рабочие кольца (пиксели) годных многоугольников — для метрик без повторного перевода.
    working_rings: list[list[Ring]]


def signed_area(ring: Ring) -> float:
    total = 0.0
    count = len(ring)
    for index in range(count):
        x0, y0 = ring[index]
        x1, y1 = ring[(index + 1) % count]
        total += x0 * y1 - x1 * y0
    return total / 2


def boundary_edges(mask: torch.Tensor, budget: int) -> dict[Lattice, list[int]]:
    """Рёбра границы: из угловой точки — список направлений исходящих рёбер."""
    padded = functional.pad(mask.to(torch.uint8), (1, 1, 1, 1)).bool()
    sides = (
        mask & ~padded[:-2, 1:-1],
        mask & ~padded[1:-1, 2:],
        mask & ~padded[2:, 1:-1],
        mask & ~padded[1:-1, :-2],
    )
    count = sum(int(side.sum()) for side in sides)
    if count > budget:
        raise TooComplexError(f"рёбер границы {count} > {budget}")
    edges: dict[Lattice, list[int]] = {}
    for direction, side in enumerate(sides):
        ox, oy = OFFSETS[direction]
        for y, x in torch.nonzero(side).tolist():
            edges.setdefault((x + ox, y + oy), []).append(direction)
    return edges


def trace_rings(edges: dict[Lattice, list[int]]) -> list[LatticeRing]:
    """Обходит все кольца; `edges` расходуется. Порядок детерминирован: старт — наименьшая точка."""
    rings: list[LatticeRing] = []
    while edges:
        # Наименьшая точка (x, y) не бывает диагональным касанием: слева от неё плиты нет.
        start = min(edges)
        direction = min(edges[start])
        point = start
        path: list[Lattice] = [start]
        arrived: list[int] = [-1]
        while True:
            outgoing = edges[point]
            outgoing.remove(direction)
            if not outgoing:
                del edges[point]
            dx, dy = DIRECTIONS[direction]
            point = (point[0] + dx, point[1] + dy)
            if point == start:
                arrived[0] = direction
                break
            available = edges[point]
            path.append(point)
            arrived.append(direction)
            direction = next(
                (direction + turn) % 4 for turn in TURNS if (direction + turn) % 4 in available
            )
        count = len(path)
        corners: list[Lattice] = []
        incoming: list[int] = []
        for index in range(count):
            if arrived[index] != arrived[(index + 1) % count]:
                corners.append(path[index])
                incoming.append(arrived[index])
        rings.append(LatticeRing(corners, incoming))
    return rings


def _lattice_area(ring: LatticeRing) -> float:
    return signed_area([(float(x), float(y)) for x, y in ring.corners])


def _inside(point: Point, ring: list[Lattice]) -> bool:
    x, y = point
    inside = False
    count = len(ring)
    for index in range(count):
        x0, y0 = ring[index]
        x1, y1 = ring[(index + 1) % count]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _probe_point(ring: LatticeRing) -> Point:
    """Точка в клетке плиты рядом с первым ребром кольца (плита слева от ребра)."""
    (x0, y0), (x1, y1) = ring.corners[0], ring.corners[1]
    dx = (x1 > x0) - (x1 < x0)
    dy = (y1 > y0) - (y1 < y0)
    return ((x0 + x1) / 2 - dy * 0.25, (y0 + y1) / 2 + dx * 0.25)


def _nudged(ring: LatticeRing, shared: Counter[Lattice], delta: float) -> Ring:
    """Вершина, через которую граница проходит дважды, сдвигается внутрь своей клетки.

    Клетка слева от приходящего ребра и слева от уходящего — одна и та же, её центр лежит в
    направлении (нормаль − направление). Два прохода сдвигаются в разные клетки диагонали и
    перестают касаться; площадь меняется на доли пикселя.
    """
    points: Ring = []
    for (x, y), direction in zip(ring.corners, ring.incoming, strict=True):
        if shared[(x, y)] > 1:
            dx, dy = DIRECTIONS[direction]
            points.append((x + delta * (-dy - dx), y + delta * (dx - dy)))
        else:
            points.append((float(x), float(y)))
    return points


def _perpendicular(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.dist(point, start)
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length


def _douglas_peucker(points: Ring, tolerance: float) -> Ring:
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best, index = 0.0, -1
        for middle in range(first + 1, last):
            distance = _perpendicular(points[middle], points[first], points[last])
            if distance > best:
                best, index = distance, middle
        if index >= 0 and best > tolerance:
            keep[index] = True
            stack.extend(((first, index), (index, last)))
    return [point for point, kept in zip(points, keep, strict=True) if kept]


def simplify_ring(ring: Ring, tolerance: float) -> Ring:
    """Замкнутое кольцо режется по первой и самой удалённой от неё вершине."""
    if len(ring) <= 4 or tolerance <= 0:
        return list(ring)
    far = max(range(len(ring)), key=lambda index: (math.dist(ring[0], ring[index]), -index))
    first = _douglas_peucker(ring[: far + 1], tolerance)
    second = _douglas_peucker([*ring[far:], ring[0]], tolerance)
    return [*first[:-1], *second[:-1]]


def _net_area(rings: list[Ring]) -> float:
    return signed_area(rings[0]) - sum(abs(signed_area(hole)) for hole in rings[1:])


def _tolerances(config: VectorConfig) -> list[float]:
    values: list[float] = []
    tolerance = config.simplify_tolerance_px
    while tolerance >= config.min_tolerance_px:
        values.append(tolerance)
        tolerance /= 2
    return [*values, 0.0]


def finalize_polygon(
    rings: list[Ring], lattice_vertices: int, frame: PageFrame, config: VectorConfig
) -> tuple[VectorPolygon, list[Ring]]:
    """Упрощение с откатом допуска: первый вариант, укладывающийся в площадь и валидный."""
    exact = _net_area(rings)
    last: tuple[VectorPolygon, list[Ring]] | None = None
    for tolerance in _tolerances(config):
        candidate = [simplify_ring(ring, tolerance) for ring in rings]
        if any(len(ring) < 3 for ring in candidate):
            continue
        net = _net_area(candidate)
        if tolerance > 0 and abs(net - exact) > config.max_area_change_ratio * abs(exact):
            continue
        outer, *holes = (frame.normalize(ring) for ring in candidate)
        issue = validate_polygon(outer, holes)
        polygon = VectorPolygon(
            outer=outer,
            holes=holes,
            status="valid" if issue is None else "invalid",
            issue=None if issue is None else issue.code.value,
            net_area_px=net,
            lattice_vertices=lattice_vertices,
            output_vertices=sum(len(ring) for ring in candidate),
            tolerance_px=tolerance,
        )
        last = (polygon, candidate)
        if issue is None:
            return last
    if last is None:
        raise ValueError("кольцо без трёх вершин даже без упрощения")
    return last


def vectorize_mask(mask: torch.Tensor, frame: PageFrame, config: VectorConfig) -> PageVectors:
    """`mask` — bool H×W рабочего растра листа."""
    edges = boundary_edges(mask, config.edge_budget)
    edge_count = sum(len(directions) for directions in edges.values())
    rings = trace_rings(edges)
    exteriors = [ring for ring in rings if _lattice_area(ring) > 0]
    holes_of: dict[int, list[LatticeRing]] = {index: [] for index in range(len(exteriors))}
    bounds = [
        (
            min(x for x, _ in ring.corners),
            min(y for _, y in ring.corners),
            max(x for x, _ in ring.corners),
            max(y for _, y in ring.corners),
        )
        for ring in exteriors
    ]
    areas = [_lattice_area(ring) for ring in exteriors]
    for hole in (ring for ring in rings if _lattice_area(ring) < 0):
        px, py = _probe_point(hole)
        parents = [
            index
            for index, ring in enumerate(exteriors)
            if bounds[index][0] <= px <= bounds[index][2]
            and bounds[index][1] <= py <= bounds[index][3]
            and _inside((px, py), ring.corners)
        ]
        if not parents:
            raise ValueError("отверстие без внешнего кольца: маска обойдена неверно")
        holes_of[min(parents, key=lambda index: (areas[index], index))].append(hole)

    filled = 0
    kept: list[list[LatticeRing]] = []
    dropped = 0
    for index, exterior in enumerate(exteriors):
        holes = []
        for hole in holes_of[index]:
            if abs(_lattice_area(hole)) < config.min_hole_px:
                filled += 1
            else:
                holes.append(hole)
        net = areas[index] - sum(abs(_lattice_area(hole)) for hole in holes)
        if net < config.min_component_px:
            dropped += 1
            continue
        kept.append([exterior, *holes])

    shared: Counter[Lattice] = Counter(
        corner for group in kept for ring in group for corner in ring.corners
    )
    polygons: list[VectorPolygon] = []
    working: list[list[Ring]] = []
    for group in kept:
        float_rings = [_nudged(ring, shared, config.pinch_nudge_px) for ring in group]
        polygon, output_rings = finalize_polygon(
            float_rings, sum(len(ring.corners) for ring in group), frame, config
        )
        polygons.append(polygon)
        if polygon.status == "valid":
            working.append(output_rings)
    order = sorted(range(len(polygons)), key=lambda index: polygons[index].outer[0])
    return PageVectors(
        polygons=[polygons[index] for index in order],
        boundary_edges=edge_count,
        dropped_components=dropped,
        filled_holes=filled,
        working_rings=working,
    )
