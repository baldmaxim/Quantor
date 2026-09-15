"""Валидность многоугольника с отверстиями (промт 05, ADR-0026).

Чистый детерминированный модуль: ни базы, ни HTTP, ни зависимостей. Отвечает на один вопрос —
годится ли контур для площади, и если нет, то чем именно. Геометрию он **не чинит**: молча
убранная вершина или развёрнутый контур дали бы правдоподобную площадь не той фигуры, которую
поставил человек.

## Что считается недействительным

```text
too_few_vertices   в кольце меньше трёх вершин
duplicate_vertex   две соседние вершины совпадают — ребро нулевой длины, в том числе замыкающее
degenerate_ring    все вершины кольца на одной прямой — площади нет
self_intersection  рёбра кольца пересекаются или касаются, кроме соседних в общей вершине
ring_intersection  граница отверстия касается или пересекает внешний контур или другое отверстие
hole_outside_outer отверстие не внутри внешнего контура
hole_inside_hole   отверстие внутри другого отверстия
too_complex        проверка вышла за предел работы — отказ, а не догадка
```

Касание считается пересечением: «восьмёрка» с общей вершиной и отверстие, касающееся контура,
не имеют однозначной площади в правиле `outer − Σ holes`.

## Точность

Проверка идёт в нормализованных координатах листа. Растяжение по осям не меняет ни пересечений,
ни коллинеарности, поэтому ответ тот же, что в точках PDF, и страница для него не нужна.

Предикаты точные. Знак ориентации тройки точек сначала считается в float с оценкой погрешности
(фильтр Шевчука); если число близко к нулю, оно пересчитывается рационально из тех же float —
`Fraction(float)` точен. Отсюда главное свойство: близкие, но не касающиеся рёбра остаются
действительными, касающиеся — нет, и ответ не зависит ни от машины, ни от порядка вызовов.

## Порядок и стоимость

Проблема ищется в фиксированном порядке: сначала устройство каждого кольца по порядку (внешнее,
затем отверстия), потом пересечения рёбер по возрастанию номеров, потом вложенность. Первая
найденная и возвращается — одна и та же геометрия всегда даёт один и тот же ответ.

Пары рёбер на крупных фигурах отбираются сеткой: ребро ложится в ячейки, через которые проходит,
а не во весь свой охват. Работа ограничена `MAX_CANDIDATE_PAIRS`: контур, для проверки которого
нужно больше, отвергается кодом `too_complex`. Это защита сервера, а не геометрия: реальный контур
этажа в тысячи вершин укладывается с запасом (замер — разбор промта 05 в `docs/stage2b`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from typing import Final

from quantor_vision.vector.issue_codes import GeometryIssueCode

__all__ = [
    "MAX_CANDIDATE_PAIRS",
    "GeometryIssue",
    "GeometryIssueCode",
    "validate_polygon",
]

Point = tuple[float, float]

# Предел проверяемых пар рёбер. На машине замера пара стоит единицы микросекунд, так что это
# около секунды работы на самый неудобный из допустимых контуров.
MAX_CANDIDATE_PAIRS: Final = 250_000

# До скольких рёбер пары перебираются напрямую: на малых фигурах сетка дороже перебора.
_BRUTE_FORCE_EDGES: Final = 64


@dataclass(frozen=True, slots=True)
class GeometryIssue:
    """Первая найденная проблема и где она.

    Кольцо 0 — внешний контур, кольцо k ≥ 1 — отверстие k по порядку хранения. Номера вершин и
    рёбер — с нуля; ребро i идёт от вершины i к следующей, последнее замыкает кольцо.
    """

    code: GeometryIssueCode
    ring: int
    vertex: int | None = None
    edge: int | None = None
    other_ring: int | None = None
    other_edge: int | None = None

    def as_payload(self) -> dict[str, str | int | None]:
        """Уточнение для ответа API: код и номера, без координат."""
        return {
            "code": self.code.value,
            "ring": self.ring,
            "vertex": self.vertex,
            "edge": self.edge,
            "other_ring": self.other_ring,
            "other_edge": self.other_edge,
        }

    @property
    def message(self) -> str:
        """Объяснение по-русски — то, что увидит человек, поставивший контур."""
        where = "Внешний контур" if self.ring == 0 else f"Отверстие {self.ring}"
        match self.code:
            case GeometryIssueCode.TOO_FEW_VERTICES:
                return f"{where}: меньше трёх вершин"
            case GeometryIssueCode.DUPLICATE_VERTEX:
                return f"{where}: вершина {self.vertex} совпадает с предыдущей"
            case GeometryIssueCode.DEGENERATE_RING:
                return f"{where}: все вершины на одной прямой, площади нет"
            case GeometryIssueCode.SELF_INTERSECTION:
                return f"{where}: рёбра {self.edge} и {self.other_edge} пересекаются или касаются"
            case GeometryIssueCode.RING_INTERSECTION:
                other = (
                    "внешнего контура" if self.other_ring == 0 else f"отверстия {self.other_ring}"
                )
                return f"{where} касается или пересекает границу {other}"
            case GeometryIssueCode.HOLE_OUTSIDE_OUTER:
                return f"{where} лежит не внутри внешнего контура"
            case GeometryIssueCode.HOLE_INSIDE_HOLE:
                return f"{where} лежит внутри отверстия {self.other_ring}"
            case GeometryIssueCode.TOO_COMPLEX:
                return "Контур слишком сложен для проверки: упростите его"


# Фильтр ориентации Шевчука: (3 + 16ε)ε, ε = 2⁻⁵³. Если |det| больше границы, знак float верен.
_ORIENT_ERROR_BOUND: Final = (3.0 + 16.0 * 2.0**-53) * 2.0**-53


def _orientation(a: Point, b: Point, c: Point) -> int:
    """Знак ориентации тройки: +1 — против часовой, −1 — по часовой, 0 — на одной прямой."""
    left = (a[0] - c[0]) * (b[1] - c[1])
    right = (a[1] - c[1]) * (b[0] - c[0])
    det = left - right
    bound = _ORIENT_ERROR_BOUND * (abs(left) + abs(right))
    if det > bound:
        return 1
    if -det > bound:
        return -1

    exact = (Fraction(a[0]) - Fraction(c[0])) * (Fraction(b[1]) - Fraction(c[1])) - (
        Fraction(a[1]) - Fraction(c[1])
    ) * (Fraction(b[0]) - Fraction(c[0]))
    return (exact > 0) - (exact < 0)


def _within_box(a: Point, b: Point, p: Point) -> bool:
    """Точка, уже лежащая на прямой ab, — внутри отрезка ab (сравнения float точны)."""
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_touch(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Замкнутые отрезки пересекаются или касаются, включая наложение на одной прямой."""
    # Охваты не пересекаются — отрезки тоже; дешёвая отсечка до четырёх предикатов.
    if (
        max(p1[0], p2[0]) < min(q1[0], q2[0])
        or max(q1[0], q2[0]) < min(p1[0], p2[0])
        or max(p1[1], p2[1]) < min(q1[1], q2[1])
        or max(q1[1], q2[1]) < min(p1[1], p2[1])
    ):
        return False

    d1 = _orientation(q1, q2, p1)
    d2 = _orientation(q1, q2, p2)
    d3 = _orientation(p1, p2, q1)
    d4 = _orientation(p1, p2, q2)

    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (
        (d1 == 0 and _within_box(q1, q2, p1))
        or (d2 == 0 and _within_box(q1, q2, p2))
        or (d3 == 0 and _within_box(p1, p2, q1))
        or (d4 == 0 and _within_box(p1, p2, q2))
    )


def _folds_back(a: Point, b: Point, c: Point) -> bool:
    """Соседние рёбра ab и bc на одной прямой и второе идёт назад по первому — «шип».

    Соседние рёбра всегда касаются в общей вершине, и это законно. Незаконно только наложение:
    коллинеарность и разворот. Скалярное произведение считается точно — на коллинеарных тройках
    это редкий путь.
    """
    if _orientation(a, b, c) != 0:
        return False
    dot = (Fraction(b[0]) - Fraction(a[0])) * (Fraction(c[0]) - Fraction(b[0])) + (
        Fraction(b[1]) - Fraction(a[1])
    ) * (Fraction(c[1]) - Fraction(b[1]))
    return dot <= 0


def _ring_structure(ring: Sequence[Point], index: int) -> GeometryIssue | None:
    """Устройство одного кольца: число вершин, нулевые рёбра, вырожденность."""
    count = len(ring)
    if count < 3:
        return GeometryIssue(GeometryIssueCode.TOO_FEW_VERTICES, ring=index)

    for vertex in range(count):
        if ring[vertex] == ring[vertex - 1]:
            # Для вершины 0 предыдущая — последняя: замыкание повторением первой точки тоже
            # ребро нулевой длины.
            return GeometryIssue(GeometryIssueCode.DUPLICATE_VERTEX, ring=index, vertex=vertex)

    first = ring[0]
    second = ring[1]
    if all(_orientation(first, second, ring[k]) == 0 for k in range(2, count)):
        return GeometryIssue(GeometryIssueCode.DEGENERATE_RING, ring=index)
    return None


def _spikes(rings: Sequence[Sequence[Point]]) -> GeometryIssue | None:
    """Соседние рёбра, наложенные друг на друга, — самопересечение в общей вершине."""
    for ring_index, ring in enumerate(rings):
        count = len(ring)
        for index in range(count):
            if _folds_back(ring[index - 1], ring[index], ring[(index + 1) % count]):
                return GeometryIssue(
                    GeometryIssueCode.SELF_INTERSECTION,
                    ring=ring_index,
                    edge=(index - 1) % count,
                    other_ring=ring_index,
                    other_edge=index,
                )
    return None


class _Edges:
    """Рёбра всех колец подряд в плоских списках — без объекта на ребро.

    На десяти тысячах вершин объект с полями на каждое ребро и пересчёт его охвата в каждой
    проверке стоили больше самих предикатов.
    """

    def __init__(self, rings: Sequence[Sequence[Point]]) -> None:
        self.start: list[Point] = []
        self.end: list[Point] = []
        self.ring: list[int] = []
        self.local: list[int] = []
        # Соседи по кольцу в сквозной нумерации: соседние рёбра касаются законно.
        self.previous: list[int] = []
        self.following: list[int] = []
        self.min_x: list[float] = []
        self.min_y: list[float] = []
        self.max_x: list[float] = []
        self.max_y: list[float] = []

        offset = 0
        for ring_index, ring in enumerate(rings):
            count = len(ring)
            for index in range(count):
                start = ring[index]
                end = ring[(index + 1) % count]
                self.start.append(start)
                self.end.append(end)
                self.ring.append(ring_index)
                self.local.append(index)
                self.previous.append(offset + (index - 1) % count)
                self.following.append(offset + (index + 1) % count)
                self.min_x.append(start[0] if start[0] < end[0] else end[0])
                self.max_x.append(end[0] if start[0] < end[0] else start[0])
                self.min_y.append(start[1] if start[1] < end[1] else end[1])
                self.max_y.append(end[1] if start[1] < end[1] else start[1])
            offset += count

    def __len__(self) -> int:
        return len(self.start)

    def touching(self, first: int, second: int) -> bool:
        """Несоседние рёбра касаются или пересекаются."""
        if second == self.following[first] or second == self.previous[first]:
            return False
        if (
            self.max_x[first] < self.min_x[second]
            or self.max_x[second] < self.min_x[first]
            or self.max_y[first] < self.min_y[second]
            or self.max_y[second] < self.min_y[first]
        ):
            return False
        return _segments_touch(
            self.start[first], self.end[first], self.start[second], self.end[second]
        )

    def issue(self, first: int, second: int) -> GeometryIssue:
        if self.ring[first] == self.ring[second]:
            return GeometryIssue(
                GeometryIssueCode.SELF_INTERSECTION,
                ring=self.ring[first],
                edge=self.local[first],
                other_ring=self.ring[second],
                other_edge=self.local[second],
            )
        # Рёбра нумеруются по кольцам подряд, поэтому у второго ребра номер кольца больше: это
        # отверстие, а первое — внешний контур или отверстие раньше по порядку.
        return GeometryIssue(
            GeometryIssueCode.RING_INTERSECTION,
            ring=self.ring[second],
            edge=self.local[second],
            other_ring=self.ring[first],
            other_edge=self.local[first],
        )


# Множитель ключа ячейки: столбцов и строк не больше `_MAX_CELLS_PER_SIDE` с запасом.
_KEY_STRIDE: Final = 1 << 20
_MAX_CELLS_PER_SIDE: Final = 1024
# Предел записей рёбер в ячейках. Считается до раскладки, по размерам рёбер: контур, которому их
# нужно больше, отвергается сразу, не потратив времени.
_MAX_GRID_ENTRIES: Final = 400_000


def _crossings(rings: Sequence[Sequence[Point]]) -> GeometryIssue | None:
    """Первая пара несоседних рёбер, которые касаются или пересекаются.

    Пары проверяются по возрастанию номеров рёбер — прямым перебором на малых фигурах и через
    сетку на крупных, — поэтому ответ от способа отбора не зависит.

    Ячейка сетки — порядка короткого ребра (четверть рёбер короче её половины): при ячейке «корень
    из числа рёбер» окружность в десять тысяч вершин клала в ячейку десятки соседей. Ребро ложится в
    ячейки, через которые проходит отрезок, а не во весь свой охват: длинная диагональ через всю
    фигуру стоит сотни записей, а не миллион.
    """
    edges = _Edges(rings)
    total = len(edges)

    if total <= _BRUTE_FORCE_EDGES:
        for first in range(total):
            for second in range(first + 1, total):
                if edges.touching(first, second):
                    return edges.issue(first, second)
        return None

    origin_x = min(edges.min_x)
    origin_y = min(edges.min_y)
    extent = max(max(edges.max_x) - origin_x, max(edges.max_y) - origin_y)
    sizes = sorted(
        max(
            edges.max_x[position] - edges.min_x[position],
            edges.max_y[position] - edges.min_y[position],
        )
        for position in range(total)
    )
    cell = min(
        max(sizes[total // 4] * 2.0, extent / _MAX_CELLS_PER_SIDE, 1e-12), max(extent, 1e-12)
    )

    estimate = 0
    for position in range(total):
        estimate += (
            int((edges.max_x[position] - edges.min_x[position]) / cell)
            + int((edges.max_y[position] - edges.min_y[position]) / cell)
            + 2
        )
    if estimate > _MAX_GRID_ENTRIES:
        return GeometryIssue(GeometryIssueCode.TOO_COMPLEX, ring=0)

    cells: dict[int, list[int]] = {}
    slack = cell * 1e-6
    for position in range(total):
        (x0, y0), (x1, y1) = edges.start[position], edges.end[position]
        if x0 > x1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        first_column = int((x0 - origin_x) / cell)
        last_column = int((x1 - origin_x) / cell)
        for column in range(first_column, last_column + 1):
            if first_column == last_column:
                low, high = (y0, y1) if y0 < y1 else (y1, y0)
            else:
                left = x0 if column == first_column else origin_x + column * cell
                right = x1 if column == last_column else origin_x + (column + 1) * cell
                slope = (y1 - y0) / (x1 - x0)
                at_left = y0 + (left - x0) * slope
                at_right = y0 + (right - x0) * slope
                low, high = (at_left, at_right) if at_left < at_right else (at_right, at_left)
            first_row = int((low - slack - origin_y) / cell)
            last_row = int((high + slack - origin_y) / cell)
            base = column * _KEY_STRIDE
            for row in range(first_row if first_row > 0 else 0, last_row + 1):
                members = cells.get(base + row)
                if members is None:
                    cells[base + row] = [position]
                elif members[-1] != position:
                    members.append(position)

    # Пары из общих ячеек. Номера в ячейке растут: рёбра раскладывались по порядку.
    pairs: set[int] = set()
    for members in cells.values():
        count = len(members)
        if count < 2:
            continue
        if len(pairs) + count * (count - 1) // 2 > 2 * MAX_CANDIDATE_PAIRS:
            return GeometryIssue(GeometryIssueCode.TOO_COMPLEX, ring=0)
        for first in range(count - 1):
            base = members[first] * total
            for second in range(first + 1, count):
                pairs.add(base + members[second])
        if len(pairs) > MAX_CANDIDATE_PAIRS:
            return GeometryIssue(GeometryIssueCode.TOO_COMPLEX, ring=0)

    for key in sorted(pairs):
        first, second = divmod(key, total)
        if edges.touching(first, second):
            return edges.issue(first, second)
    return None


class _Ring:
    """Кольцо с полосами рёбер по y — для принадлежности точки без обхода всех рёбер."""

    def __init__(self, points: Sequence[Point]) -> None:
        self.points = points
        ys = [point[1] for point in points]
        self.min_x = min(point[0] for point in points)
        self.max_x = max(point[0] for point in points)
        self.min_y = min(ys)
        self.max_y = max(ys)
        count = len(points)
        self.bands = max(1, min(256, isqrt(count)))
        self.height = max(self.max_y - self.min_y, 1e-300)
        self.edges_by_band: list[list[int]] = [[] for _ in range(self.bands)]
        for index in range(count):
            start = points[index]
            end = points[(index + 1) % count]
            for band in range(
                self._band(min(start[1], end[1])), self._band(max(start[1], end[1])) + 1
            ):
                self.edges_by_band[band].append(index)

    def _band(self, y: float) -> int:
        return min(self.bands - 1, max(0, int((y - self.min_y) / self.height * self.bands)))

    def contains(self, point: Point) -> bool:
        """Точка строго внутри — число оборотов с точными предикатами.

        Вызывается только для точек, заведомо не лежащих на границе: пересечения и касания уже
        отвергнуты, поэтому «на границе» здесь не бывает.
        """
        if not (self.min_x <= point[0] <= self.max_x and self.min_y <= point[1] <= self.max_y):
            return False
        winding = 0
        count = len(self.points)
        for index in self.edges_by_band[self._band(point[1])]:
            start = self.points[index]
            end = self.points[(index + 1) % count]
            if start[1] <= point[1]:
                if end[1] > point[1] and _orientation(start, end, point) > 0:
                    winding += 1
            elif end[1] <= point[1] and _orientation(start, end, point) < 0:
                winding -= 1
        return winding != 0


def validate_polygon(
    outer: Sequence[Sequence[float]],
    holes: Sequence[Sequence[Sequence[float]]] = (),
) -> GeometryIssue | None:
    """Первая проблема контура с отверстиями или `None`, если он годится для площади.

    Точки — пары нормализованных координат, как они хранятся. Диапазон и конечность здесь не
    проверяются: это граница API и сервиса, а сюда приходят уже числа.
    """
    rings: list[list[Point]] = [
        [(float(point[0]), float(point[1])) for point in ring] for ring in (outer, *holes)
    ]

    for index, ring in enumerate(rings):
        issue = _ring_structure(ring, index)
        if issue is not None:
            return issue

    issue = _spikes(rings) or _crossings(rings)
    if issue is not None:
        return issue

    if len(rings) == 1:
        return None

    # Границы не касаются друг друга — значит, каждое отверстие целиком по одну сторону любой
    # другой границы, и хватает одной вершины.
    located = [_Ring(ring) for ring in rings]
    for hole_index in range(1, len(rings)):
        if not located[0].contains(rings[hole_index][0]):
            return GeometryIssue(GeometryIssueCode.HOLE_OUTSIDE_OUTER, ring=hole_index)
    for hole_index in range(1, len(rings)):
        probe = rings[hole_index][0]
        for other_index in range(1, len(rings)):
            if other_index != hole_index and located[other_index].contains(probe):
                return GeometryIssue(
                    GeometryIssueCode.HOLE_INSIDE_HOLE, ring=hole_index, other_ring=other_index
                )
    return None
