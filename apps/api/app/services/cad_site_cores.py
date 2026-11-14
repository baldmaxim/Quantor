"""Совмещение зданий объекта по ядрам: поворот и сдвиг, при которых монолит совпадает с монолитом.

Общих марок осей у подземной автостоянки и корпусов нет (у паркинга своя сетка «01…08, 0А…0Р»), а
крылья комплекса повёрнуты друг к другу. Но ядра корпусов (лестнично-лифтовые узлы, пилоны, стены
шахт) проходят сквозь паркинг: на плане подземки они нарисованы на своих местах. Поэтому скопление
зданий ставится на объект там, где его монолитные стены и пилоны ложатся на монолит уже
поставленных этажей.

Чистые функции на списках колец в мм системы объекта (без Shapely: процесс API, ADR-0036):

1. Поворот - разность направления стен скопления и одного из выраженных направлений основы (по
   модулю 90°) плюс k·90°.
2. Сдвиги-кандидаты - голосование пар похожих элементов (площадь, длина, ширина, направление).
3. Оценка кандидата - доля точек сетки `CELL_MM` внутри монолита скопления, попавших на монолит
   основы (расширенный на клетку: разбивка стен на части в разных листах разная).
4. Лучший кандидат уточняется по повороту (±1° шагом 0,1°) и сдвигу; принимается, если доля не
   меньше `MIN_SHARE` и не меньше чем в `MIN_RATIO` раза больше лучшего другого варианта (дальше
   `DISTINCT_MM` или с другим поворотом): у одинаковых секций ядро похоже на чужое место.

Колонны в счёт не идут: сетка колонн паркинга периодична и даёт ложные совпадения со сдвигом на
шаг. Масштаб не подбирается: геометрия листа - по его калибровке (лист с неверным масштабом не
совместится, и это видно по причине отказа).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

Point = tuple[float, float]
Ring = Sequence[Sequence[float]]

CELL_MM: Final = 250.0
VOTE_BIN_MM: Final = 500.0
MAX_SAMPLES: Final = 5000
MIN_ELEMENT_LENGTH_MM: Final = 800.0
MIN_EDGE_MM: Final = 300.0
TOP_CANDIDATES: Final = 15
# Отбор кандидатов по прореженным точкам, пересчёт лучших по всем, уточнение по части.
COARSE_SAMPLES: Final = 600
FULL_CANDIDATES: Final = 8
FINE_SAMPLES: Final = 2000
MIN_SHARE: Final = 0.6
MIN_RATIO: Final = 2.0
MIN_SAMPLES: Final = 200
DISTINCT_MM: Final = 3000.0
FINE_STEP_DEG: Final = 0.1
FINE_RANGE_DEG: Final = 1.0
SIZE_TOLERANCE: Final = 0.3
WIDTH_TOLERANCE: Final = 0.4
ANGLE_TOLERANCE_DEG: Final = 6.0
# Направления основы: не больше трёх пиков, каждый не слабее 15 % сильнейшего, не ближе 3°.
ANGLE_PEAKS: Final = 3
ANGLE_PEAK_SHARE: Final = 0.15
ANGLE_PEAK_GAP_DEG: Final = 3.0


@dataclass(frozen=True, slots=True)
class CoreMatch:
    """Перевод из системы скопления в систему основы: `p' = R(rotation) p + (tx, ty)`."""

    rotation_deg: float
    tx: float
    ty: float
    share: float
    second_share: float
    accepted: bool


@dataclass(frozen=True, slots=True)
class _Element:
    cx: float
    cy: float
    area: float
    length: float
    width: float
    angle: float  # направление длинной стороны, 0…180°


def _ring(ring: Ring) -> list[Point]:
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def _angle_bins(rings: Sequence[Ring]) -> list[float]:
    """Гистограмма направлений рёбер по модулю 90° (взвешена длиной), шаг 0,5°, сглаженная."""
    bins = [0.0] * 180
    for ring in rings:
        pts = _ring(ring)
        for i, (x0, y0) in enumerate(pts):
            x1, y1 = pts[(i + 1) % len(pts)]
            length = math.hypot(x1 - x0, y1 - y0)
            if length < MIN_EDGE_MM:
                continue
            angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90.0
            bins[int(angle * 2) % 180] += length
    return [bins[i - 1] + bins[i] + bins[(i + 1) % 180] for i in range(180)]


def dominant_angle(rings: Sequence[Ring]) -> float:
    """Преобладающее направление рёбер, 0…90°, шаг 0,5°."""
    smooth = _angle_bins(rings)
    return max(range(180), key=lambda i: smooth[i]) / 2 + 0.25


def dominant_angles(rings: Sequence[Ring], limit: int = ANGLE_PEAKS) -> list[float]:
    """Выраженные направления рёбер, сильнейшее первым: у основы их несколько (крыло комплекса
    повёрнуто к остальному, а ортогональных стен больше)."""
    smooth = _angle_bins(rings)
    top = max(smooth, default=0.0)
    if top <= 0:
        return [0.25]
    peaks: list[float] = []
    for i in sorted(range(180), key=lambda i: -smooth[i]):
        if smooth[i] < ANGLE_PEAK_SHARE * top or len(peaks) >= limit:
            break
        angle = i / 2 + 0.25
        if all(min(abs(angle - a), 90.0 - abs(angle - a)) >= ANGLE_PEAK_GAP_DEG for a in peaks):
            peaks.append(angle)
    return peaks


def _inside(x: float, y: float, pts: Sequence[Point]) -> bool:
    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def raster(rings: Sequence[Ring]) -> list[Point]:
    """Центры клеток сетки `CELL_MM`, лежащие внутри колец."""
    out: list[Point] = []
    for ring in rings:
        pts = _ring(ring)
        if len(pts) < 3:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        for ix in range(math.floor(min(xs) / CELL_MM), math.floor(max(xs) / CELL_MM) + 1):
            cx = (ix + 0.5) * CELL_MM
            for iy in range(math.floor(min(ys) / CELL_MM), math.floor(max(ys) / CELL_MM) + 1):
                cy = (iy + 0.5) * CELL_MM
                if _inside(cx, cy, pts):
                    out.append((cx, cy))
    return out


def occupancy(rings: Sequence[Ring], grow: int = 1) -> set[tuple[int, int]]:
    """Клетки монолита основы, расширенные на `grow` клеток во все стороны."""
    cells: set[tuple[int, int]] = set()
    span = range(-grow, grow + 1)
    for x, y in raster(rings):
        ix, iy = math.floor(x / CELL_MM), math.floor(y / CELL_MM)
        for dx in span:
            for dy in span:
                cells.add((ix + dx, iy + dy))
    return cells


def _element(ring: Ring) -> _Element | None:
    pts = _ring(ring)
    if len(pts) < 3:
        return None
    area2 = cx = cy = 0.0
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area2) < 2.0:
        return None
    cx, cy = cx / (3 * area2), cy / (3 * area2)
    sxx = sum((x - cx) ** 2 for x, _ in pts)
    syy = sum((y - cy) ** 2 for _, y in pts)
    sxy = sum((x - cx) * (y - cy) for x, y in pts)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(theta), math.sin(theta)
    along = [(x - cx) * ux + (y - cy) * uy for x, y in pts]
    across = [-(x - cx) * uy + (y - cy) * ux for x, y in pts]
    length, width = max(along) - min(along), max(across) - min(across)
    angle = math.degrees(theta)
    if width > length:
        length, width, angle = width, length, angle + 90.0
    return _Element(cx, cy, abs(area2) / 2, length, width, angle % 180.0)


def _close(a: float, b: float, tolerance: float) -> bool:
    return b > 0 and a > 0 and a / b < 1 + tolerance and b / a < 1 + tolerance


def _rotate(x: float, y: float, deg: float) -> Point:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return c * x - s * y, s * x + c * y


def _score(
    samples: Sequence[Point], cells: frozenset[tuple[int, int]], deg: float, tx: float, ty: float
) -> float:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    hits = 0
    floor = math.floor
    for x, y in samples:
        if (floor((c * x - s * y + tx) / CELL_MM), floor((s * x + c * y + ty) / CELL_MM)) in cells:
            hits += 1
    return hits / len(samples) if samples else 0.0


def _bucket(area: float) -> int:
    return round(math.log(max(area, 1.0)) / math.log(1.0 + SIZE_TOLERANCE))


@dataclass(frozen=True, slots=True)
class BaseIndex:
    """Основа, подготовленная к совмещению: клетки монолита (с расширением и без), элементы по
    корзинам площади и выраженные направления стен. Строится один раз на набор колец."""

    cells: frozenset[tuple[int, int]]
    strict: frozenset[tuple[int, int]]
    buckets: dict[int, tuple[_Element, ...]]
    peaks: tuple[float, ...]
    empty: bool


def index_base(rings: Sequence[Ring]) -> BaseIndex:
    groups: dict[int, list[_Element]] = {}
    for element in _elements(rings):
        groups.setdefault(_bucket(element.area), []).append(element)
    return BaseIndex(
        frozenset(occupancy(rings)),
        frozenset(occupancy(rings, grow=0)),
        {k: tuple(v) for k, v in groups.items()},
        tuple(dominant_angles(rings)) if rings else (0.25,),
        not rings,
    )


def _elements(rings: Sequence[Ring]) -> list[_Element]:
    """Элементы для голосования: без мелочи короче `MIN_ELEMENT_LENGTH_MM`."""
    out: list[_Element] = []
    for ring in rings:
        element = _element(ring)
        if element is not None and element.length >= MIN_ELEMENT_LENGTH_MM:
            out.append(element)
    return out


def _votes(base: BaseIndex, other: Sequence[_Element], deg: float) -> list[tuple[int, int, int]]:
    """Сдвиги пар похожих элементов при повороте `deg`: (бин x, бин y, голоса), лучшие сверху."""
    counts: dict[tuple[int, int], int] = {}
    for o in other:
        rx, ry = _rotate(o.cx, o.cy, deg)
        angle = (o.angle + deg) % 180.0
        elongated = o.length / max(o.width, 1.0) > 1.5
        key = _bucket(o.area)
        for b in (
            *base.buckets.get(key - 1, ()),
            *base.buckets.get(key, ()),
            *base.buckets.get(key + 1, ()),
        ):
            if not (
                _close(o.area, b.area, SIZE_TOLERANCE)
                and _close(o.length, b.length, SIZE_TOLERANCE)
                and _close(o.width, b.width, WIDTH_TOLERANCE)
            ):
                continue
            if elongated:
                diff = abs(angle - b.angle) % 180.0
                if min(diff, 180.0 - diff) > ANGLE_TOLERANCE_DEG:
                    continue
            shift = (round((b.cx - rx) / VOTE_BIN_MM), round((b.cy - ry) / VOTE_BIN_MM))
            counts[shift] = counts.get(shift, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [(bx, by, n) for (bx, by), n in ranked[:TOP_CANDIDATES]]


def _turn_gap(a: float, b: float) -> float:
    """Разница поворотов по кругу, градусы."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _thin(samples: list[Point], limit: int = MAX_SAMPLES) -> list[Point]:
    if len(samples) <= limit:
        return samples
    step = len(samples) / limit
    return [samples[int(i * step)] for i in range(limit)]


def register(base: Sequence[Ring] | BaseIndex, other: Sequence[Ring]) -> CoreMatch | None:
    """Совмещение монолита `other` с монолитом основы; нечего сравнивать - `None`.

    Результат возвращается и при отказе (`accepted = False`): доли нужны для причины. Кандидаты
    отбираются по прореженным точкам (`COARSE_SAMPLES`), лучшие - пересчитываются по всем.
    """
    index = base if isinstance(base, BaseIndex) else index_base(base)
    samples = _thin(raster(other))
    if len(samples) < MIN_SAMPLES or index.empty:
        return None
    coarse = _thin(samples, COARSE_SAMPLES)
    other_elements = _elements(other)
    own = dominant_angle(other)
    turns = [peak - own + 90.0 * k for peak in index.peaks for k in range(4)]
    rough: list[tuple[float, float, float, float]] = []  # доля, поворот, tx, ty
    for deg in turns:
        for bx, by, _n in _votes(index, other_elements, deg):
            best = (-1.0, deg, 0.0, 0.0)
            for ax in (-1, 0, 1):
                for ay in (-1, 0, 1):
                    tx, ty = bx * VOTE_BIN_MM + ax * CELL_MM, by * VOTE_BIN_MM + ay * CELL_MM
                    share = _score(coarse, index.cells, deg, tx, ty)
                    if share > best[0]:
                        best = (share, deg, tx, ty)
            rough.append(best)
    if not rough:
        return None
    rough.sort(key=lambda c: -c[0])
    candidates = sorted(
        (
            (_score(samples, index.cells, d, x, y), d, x, y)
            for _s, d, x, y in rough[:FULL_CANDIDATES]
        ),
        key=lambda c: -c[0],
    )
    share, deg, tx, ty = candidates[0]
    distinct = [
        c[0]
        for c in candidates[1:] + [(r[0], r[1], r[2], r[3]) for r in rough[FULL_CANDIDATES:]]
        if math.hypot(c[2] - tx, c[3] - ty) > DISTINCT_MM
        or _turn_gap(c[1], deg) > ANGLE_PEAK_GAP_DEG
    ]
    second = max(distinct, default=0.0)
    # Уточнение по нерасширенной основе: расширенная прощает градус поворота и полклетки сдвига.
    fine_samples = _thin(samples, FINE_SAMPLES)
    steps = round(FINE_RANGE_DEG / FINE_STEP_DEG)
    fine = (_score(fine_samples, index.strict, deg, tx, ty), 0, deg, tx, ty)
    for i in range(-steps, steps + 1):
        d = deg + i * FINE_STEP_DEG
        for ax in (-1, 0, 1):
            for ay in (-1, 0, 1):
                tx2, ty2 = tx + ax * CELL_MM / 2, ty + ay * CELL_MM / 2
                s = _score(fine_samples, index.strict, d, tx2, ty2)
                if s > fine[0]:
                    fine = (s, abs(i), d, tx2, ty2)
    _strict, _i, deg, tx, ty = fine
    share = _score(samples, index.cells, deg, tx, ty)
    accepted = share >= MIN_SHARE and share >= MIN_RATIO * second
    rotation = (deg + 180.0) % 360.0 - 180.0
    return CoreMatch(round(rotation, 3), round(tx, 1), round(ty, 1), share, second, accepted)


def transform_point(x: float, y: float, rotation_deg: float, tx: float, ty: float) -> Point:
    rx, ry = _rotate(x, y, rotation_deg)
    return rx + tx, ry + ty
