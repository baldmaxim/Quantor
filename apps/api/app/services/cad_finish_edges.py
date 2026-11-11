"""Привязка рёбер зоны помещения к конструкциям листа (ADR-0042, п. 6): чистая геометрия без базы.

Контур зоны (мм DXF, тот же перевод, что в 3D-виде) режется на отрезки с шагом `SAMPLE_STEP_MM`;
для середины каждого отрезка ищется ближайшая граница (контур или отверстие конструкции, контур
перемычки проёма) не дальше `EDGE_TOLERANCE_MM`. Перемычка проёма приоритетнее конструкции: в
проёме граница - перемычка (при равном расстоянии побеждает перемычка). Соседние отрезки одного
класса склеиваются в участки:

- `wall` - стена с основанием `monolith` / `masonry` / `gkl` (класс `wall:<основание>:<id>`);
- `door` / `gap` - дверной проём или проём без двери (`door:<id>`, `gap:<id>`);
- `none` - стены нет (граница с соседней зоной, линия разреза).

Конструкции и перемычки лежат в сетке по отрезкам границ (ячейка `GRID_CELL_MM`): на точку смотрим
только соседние ячейки, а не все конструкции листа. Сумма длин участков зоны равна периметру её
контура. Размеры - мм; стандартная библиотека, ни Shapely, ни numpy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from app.contracts.cad_constructions import CadConstructionKind

SAMPLE_STEP_MM: Final = 50.0
EDGE_TOLERANCE_MM: Final = 80.0
GRID_CELL_MM: Final = 1000.0
# Отрезков зоны в одной выборке кандидатов из сетки (500 мм при шаге 50).
_CHUNK_SAMPLES: Final = 10

Base = Literal["monolith", "masonry", "gkl"]
BASES: Final[tuple[Base, ...]] = ("monolith", "masonry", "gkl")
SpanKind = Literal["wall", "door", "gap", "none"]
OpeningKind = Literal["door", "gap"]
Point = tuple[float, float]
Ring = Sequence[Point]

# Материалы, по которым конструкция считается основанием ГКЛ независимо от вида. В `CadMaterial`
# такого материала нет (ГКЛ - каркасные перегородки `frame_partition`), поэтому набор пуст.
GKL_MATERIALS: Final[frozenset[str]] = frozenset()

_MONOLITH_KINDS: Final[frozenset[CadConstructionKind]] = frozenset(
    {"monolith_wall", "monolith_pylon", "monolith_column"}
)


def construction_base(kind: CadConstructionKind, material: str | None = None) -> Base | None:
    """Основание отделки по виду конструкции и материалу; плита перекрытия - не стена (`None`)."""
    if kind == "floor_slab":
        return None
    if kind == "frame_partition" or (material is not None and material in GKL_MATERIALS):
        return "gkl"
    if kind == "masonry":
        return "masonry"
    if kind in _MONOLITH_KINDS:
        return "monolith"
    return None


@dataclass(frozen=True, slots=True)
class EdgeConstruction:
    """Стена листа: основание и контуры (внешнее кольцо и отверстия) в мм."""

    id: str
    base: Base
    rings: Sequence[Ring]


@dataclass(frozen=True, slots=True)
class EdgeOpening:
    """Проём: контур перемычки в мм, вид, ширина, толщина стены и основание стены-хозяина."""

    id: str
    kind: OpeningKind
    lintel: Ring
    width_mm: float
    thickness_mm: float | None
    host_base: Base | None


@dataclass(frozen=True, slots=True)
class EdgeSpan:
    """Участок границы зоны одного класса; `ref` - id конструкции или проёма."""

    kind: SpanKind
    length_mm: float
    base: Base | None = None
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class ZoneEdges:
    """Результат по зоне: участки по порядку обхода и длины по классам (мм)."""

    spans: tuple[EdgeSpan, ...]
    base_mm: dict[Base, float]
    door_mm: dict[str, float]
    gap_mm: dict[str, float]
    open_mm: float

    @property
    def perimeter_mm(self) -> float:
        return sum(span.length_mm for span in self.spans)


_ClassKey = tuple[SpanKind, str | None, Base | None]
_NONE_CLASS: Final[_ClassKey] = ("none", None, None)


@dataclass(slots=True)
class _Run:
    """Идущие подряд отрезки одного класса."""

    cls: _ClassKey
    length_mm: float


class _Seg(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    cls: _ClassKey
    lintel: bool


def _dist2(px: float, py: float, seg: _Seg) -> float:
    dx, dy = seg.x1 - seg.x0, seg.y1 - seg.y0
    length2 = dx * dx + dy * dy
    if length2 == 0.0:
        return (px - seg.x0) ** 2 + (py - seg.y0) ** 2
    t = max(0.0, min(1.0, ((px - seg.x0) * dx + (py - seg.y0) * dy) / length2))
    return (px - seg.x0 - t * dx) ** 2 + (py - seg.y0 - t * dy) ** 2


def _ring_points(ring: Ring) -> list[Point]:
    """Кольцо без повторного замыкающего узла."""
    points = [(float(p[0]), float(p[1])) for p in ring]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _ring_segments(ring: Ring, cls: _ClassKey, lintel: bool) -> Iterable[_Seg]:
    points = _ring_points(ring)
    if len(points) < 2:
        return
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        if (x0, y0) == (x1, y1):
            continue
        yield _Seg(x0, y0, x1, y1, min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), cls, lintel)


def _cell(value: float) -> int:
    return math.floor(value / GRID_CELL_MM)


class EdgeIndex:
    """Сетка отрезков границ конструкций и перемычек листа; строится один раз на лист."""

    def __init__(
        self,
        constructions: Iterable[EdgeConstruction],
        openings: Iterable[EdgeOpening],
        *,
        tolerance_mm: float = EDGE_TOLERANCE_MM,
    ) -> None:
        self._tolerance = tolerance_mm
        self._segments: list[_Seg] = []
        self._cells: dict[tuple[int, int], list[int]] = {}
        for item in constructions:
            for ring in item.rings:
                for seg in _ring_segments(ring, ("wall", item.id, item.base), False):
                    self._add(seg)
        for opening in openings:
            for seg in _ring_segments(opening.lintel, (opening.kind, opening.id, None), True):
                self._add(seg)

    def _add(self, seg: _Seg) -> None:
        index = len(self._segments)
        self._segments.append(seg)
        # Идём по отрезку шагом в полъячейки: запрос точки не дальше допуска от отрезка попадёт в
        # ячейки, покрытые запасом `допуск + четверть ячейки` вокруг одной из точек обхода.
        step = GRID_CELL_MM / 2.0
        count = max(1, math.ceil(math.hypot(seg.x1 - seg.x0, seg.y1 - seg.y0) / step))
        margin = self._tolerance + GRID_CELL_MM / 4.0
        seen: set[tuple[int, int]] = set()
        for k in range(count + 1):
            px = seg.x0 + (seg.x1 - seg.x0) * k / count
            py = seg.y0 + (seg.y1 - seg.y0) * k / count
            for cx in range(_cell(px - margin), _cell(px + margin) + 1):
                for cy in range(_cell(py - margin), _cell(py + margin) + 1):
                    if (cx, cy) not in seen:
                        seen.add((cx, cy))
                        self._cells.setdefault((cx, cy), []).append(index)

    def _candidates(self, lo_x: float, lo_y: float, hi_x: float, hi_y: float) -> list[_Seg]:
        """Отрезки, чей габарит пересекает прямоугольник, расширенный на допуск."""
        tol = self._tolerance
        found: set[int] = set()
        for cx in range(_cell(lo_x - tol), _cell(hi_x + tol) + 1):
            for cy in range(_cell(lo_y - tol), _cell(hi_y + tol) + 1):
                found.update(self._cells.get((cx, cy), ()))
        result: list[_Seg] = []
        for index in sorted(found):
            seg = self._segments[index]
            if (
                seg.max_x >= lo_x - tol
                and seg.min_x <= hi_x + tol
                and seg.max_y >= lo_y - tol
                and seg.min_y <= hi_y + tol
            ):
                result.append(seg)
        return result

    def _classify(self, px: float, py: float, candidates: Sequence[_Seg]) -> _ClassKey:
        limit = self._tolerance * self._tolerance
        best_lintel: tuple[float, _ClassKey] | None = None
        best_wall: tuple[float, _ClassKey] | None = None
        for seg in candidates:
            d2 = _dist2(px, py, seg)
            if d2 > limit:
                continue
            if seg.lintel:
                if best_lintel is None or d2 < best_lintel[0]:
                    best_lintel = (d2, seg.cls)
            elif best_wall is None or d2 < best_wall[0]:
                best_wall = (d2, seg.cls)
        # Перемычка приоритетнее конструкции при равном расстоянии: в проёме граница - перемычка.
        # Строгий приоритет в пределах допуска растягивал бы дверь за торцы перемычки на допуск
        # (на листе 82 - до 20 % ширины), поэтому побеждает ближайшая граница.
        if best_lintel is not None and (best_wall is None or best_lintel[0] <= best_wall[0]):
            return best_lintel[1]
        if best_wall is not None:
            return best_wall[1]
        return _NONE_CLASS

    def link_ring(self, ring: Ring, *, step_mm: float = SAMPLE_STEP_MM) -> ZoneEdges:
        """Участки границы зоны по классам; кольцо менее чем из трёх точек - без участков."""
        points = _ring_points(ring)
        runs: list[_Run] = []
        if len(points) >= 3:
            for index, (ax, ay) in enumerate(points):
                bx, by = points[(index + 1) % len(points)]
                length = math.hypot(bx - ax, by - ay)
                if length == 0.0:
                    continue
                count = max(1, math.ceil(length / step_mm))
                piece = length / count
                for start in range(0, count, _CHUNK_SAMPLES):
                    stop = min(start + _CHUNK_SAMPLES, count)
                    samples = [
                        (
                            ax + (bx - ax) * (k + 0.5) / count,
                            ay + (by - ay) * (k + 0.5) / count,
                        )
                        for k in range(start, stop)
                    ]
                    xs = [s[0] for s in samples]
                    ys = [s[1] for s in samples]
                    candidates = self._candidates(min(xs), min(ys), max(xs), max(ys))
                    for px, py in samples:
                        cls = self._classify(px, py, candidates)
                        if runs and runs[-1].cls == cls:
                            runs[-1].length_mm += piece
                        else:
                            runs.append(_Run(cls, piece))
        return _summarize(runs)


def _summarize(runs: Sequence[_Run]) -> ZoneEdges:
    spans: list[EdgeSpan] = []
    base_mm: dict[Base, float] = dict.fromkeys(BASES, 0.0)
    door_mm: dict[str, float] = {}
    gap_mm: dict[str, float] = {}
    open_mm = 0.0
    for run in runs:
        kind, ref, base = run.cls
        length = run.length_mm
        spans.append(EdgeSpan(kind, length, base, ref))
        if kind == "wall" and base is not None:
            base_mm[base] += length
        elif kind == "door" and ref is not None:
            door_mm[ref] = door_mm.get(ref, 0.0) + length
        elif kind == "gap" and ref is not None:
            gap_mm[ref] = gap_mm.get(ref, 0.0) + length
        else:
            open_mm += length
    return ZoneEdges(tuple(spans), base_mm, door_mm, gap_mm, open_mm)
