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
5. Резерв (`CoreMatch.reserve`): доля от `RESERVE_SHARE` при отрыве от второго варианта в
   `RESERVE_RATIO` раз. Одной доли здесь мало - вызывающий принимает такое совмещение только с
   проверками по месту (контур в пределах основы, нет наложения на поставленные здания).
6. Варианты (`CoreMatch.variants`): все различимые места, найденные для скопления, лучшими
   сверху. По ним вызывающий отсеивает места, занятые другими зданиями или лежащие вне основы, и
   сверяет посадки по нескольким этажам здания (`agree`): этажи независимо дают одно место.

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
# Доля совпадения: верные совмещения ЖК Знаки 0,60–0,89; лист с неверным масштабом 0,31.
MIN_SHARE: Final = 0.5
MIN_RATIO: Final = 2.0
# Резерв: кровля стилобата секций 1-6 ЖК Знаки встаёт верно при 0,38 против 0,13 у второго
# варианта (сквозь неё проходят не все ядра подземки); у ложных совмещений одиночных башен отрыв
# от второго варианта не больше 1,5.
RESERVE_SHARE: Final = 0.35
RESERVE_RATIO: Final = 2.5
# Согласие этажей: посадки по нескольким этажам здания, независимо давшие одно место (поворот в
# пределах 1,5° - шаг уточнения 0,1° плюс разброс листов, центр в пределах 1 м - клетка 250 мм и
# погрешность вычерчивания ядер на разных листах), принимаются при доле от `RESERVE_SHARE` и
# при отрыве от второго места ниже обычного: один этаж так не принимается никогда.
AGREE_ROTATION_DEG: Final = 1.5
AGREE_SHIFT_MM: Final = 1000.0
AGREE_MIN_FLOORS: Final = 2
# Не больше стольких вариантов на скопление (лучшие по доле): остальные в кеше не нужны.
MAX_VARIANTS: Final = 40
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
class CoreVariant:
    """Одно место скопления на основе: перевод `p' = R(rotation) p + (tx, ty)` и доля совпадения."""

    rotation_deg: float
    tx: float
    ty: float
    share: float


@dataclass(frozen=True, slots=True)
class CoreMatch:
    """Перевод из системы скопления в систему основы: `p' = R(rotation) p + (tx, ty)`.

    `variants` - все найденные места (лучшее первым, не больше `MAX_VARIANTS`); по умолчанию пусто.
    """

    rotation_deg: float
    tx: float
    ty: float
    share: float
    second_share: float
    accepted: bool
    variants: tuple[CoreVariant, ...] = ()

    @property
    def reserve(self) -> bool:
        """Годится как резерв: доля меньше обычной, зато отрыв от второго варианта больше."""
        return self.share >= RESERVE_SHARE and self.share >= RESERVE_RATIO * self.second_share


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


def distinct(a: CoreVariant, b: CoreVariant) -> bool:
    """Разные места: дальше `DISTINCT_MM` или другой поворот (больше `ANGLE_PEAK_GAP_DEG`)."""
    return (
        math.hypot(a.tx - b.tx, a.ty - b.ty) > DISTINCT_MM
        or _turn_gap(a.rotation_deg, b.rotation_deg) > ANGLE_PEAK_GAP_DEG
    )


def second_share(best: CoreVariant, variants: Sequence[CoreVariant]) -> float:
    """Наибольшая доля среди мест, отличных от `best`; других нет - 0."""
    return max((v.share for v in variants if distinct(v, best)), default=0.0)


def passes(share: float, second: float) -> bool:
    """Обычный порог (`MIN_SHARE`, `MIN_RATIO`) или порог резерва (`RESERVE_*`)."""
    return (share >= MIN_SHARE and share >= MIN_RATIO * second) or (
        share >= RESERVE_SHARE and share >= RESERVE_RATIO * second
    )


def same_place(a: CoreVariant, b: CoreVariant, centre: Point) -> bool:
    """Одно место для согласия этажей: поворот в `AGREE_ROTATION_DEG`, центр здания `centre` (в
    системе скопления) - в `AGREE_SHIFT_MM`. Сдвиги `tx, ty` сравнивать нельзя: начало системы
    скопления может быть далеко от здания, и поворот на градус уводит его на метры."""
    ax, ay = transform_point(centre[0], centre[1], a.rotation_deg, a.tx, a.ty)
    bx, by = transform_point(centre[0], centre[1], b.rotation_deg, b.tx, b.ty)
    return (
        _turn_gap(a.rotation_deg, b.rotation_deg) <= AGREE_ROTATION_DEG
        and math.hypot(ax - bx, ay - by) <= AGREE_SHIFT_MM
    )


def _wrap(deg: float) -> float:
    """Поворот в пределах -180…180°."""
    return (deg + 180.0) % 360.0 - 180.0


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
    others = [
        CoreVariant(_wrap(c[1]), c[2], c[3], c[0])
        for c in candidates[1:] + [(r[0], r[1], r[2], r[3]) for r in rough[FULL_CANDIDATES:]]
    ]
    second = second_share(CoreVariant(_wrap(deg), tx, ty, share), others)
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
    rotation = _wrap(deg)
    winner = CoreVariant(round(rotation, 3), round(tx, 1), round(ty, 1), share)
    ranked = sorted(others, key=lambda v: -v.share)[: MAX_VARIANTS - 1]
    return CoreMatch(
        winner.rotation_deg, winner.tx, winner.ty, share, second, accepted, (winner, *ranked)
    )


def transform_point(x: float, y: float, rotation_deg: float, tx: float, ty: float) -> Point:
    rx, ry = _rotate(x, y, rotation_deg)
    return rx + tx, ry + ty


def _edge_distance(x: float, y: float, pts: Sequence[Point]) -> float:
    best = math.inf
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length2))
        best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return best


def inside_share(points: Sequence[Point], outline: Ring, tolerance_mm: float) -> float:
    """Доля точек внутри контура или не дальше `tolerance_mm` от его границы; нет точек - 0."""
    pts = _ring(outline)
    if not points or len(pts) < 3:
        return 0.0
    hits = sum(
        1 for x, y in points if _inside(x, y, pts) or _edge_distance(x, y, pts) <= tolerance_mm
    )
    return hits / len(points)


# ------------------------------------------------------- отсев мест и согласие этажей

AREA_CELL_MM: Final = 1000.0
MAX_AREA_SAMPLES: Final = 1500


def area_samples(outline: Ring) -> list[Point]:
    """Точки сетки `AREA_CELL_MM` внутри контура (не больше `MAX_AREA_SAMPLES`): выборка для
    долей площади без Shapely."""
    pts = _ring(outline)
    if len(pts) < 3:
        return []
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    step = AREA_CELL_MM
    out: list[Point] = []
    for ix in range(math.floor(min(xs) / step), math.floor(max(xs) / step) + 1):
        x = (ix + 0.5) * step
        for iy in range(math.floor(min(ys) / step), math.floor(max(ys) / step) + 1):
            y = (iy + 0.5) * step
            if _inside(x, y, pts):
                out.append((x, y))
    return _thin(out, MAX_AREA_SAMPLES)


def covered_share(points: Sequence[Point], outlines: Sequence[Ring]) -> float:
    """Доля точек, лежащих внутри хотя бы одного из контуров; нет точек или контуров - 0."""
    polygons = [(pts, *_extent(pts)) for pts in (_ring(o) for o in outlines) if len(pts) >= 3]
    if not points or not polygons:
        return 0.0
    hits = 0
    for x, y in points:
        for pts, x0, y0, x1, y1 in polygons:
            if x0 <= x <= x1 and y0 <= y <= y1 and _inside(x, y, pts):
                hits += 1
                break
    return hits / len(points)


def _extent(pts: Sequence[Point]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True, slots=True)
class FloorChoice:
    """Лучшее допустимое место, найденное по одному этажу здания, и отрыв от следующего места."""

    floor: int
    match: CoreMatch
    best: CoreVariant
    second: float
    dropped: int


@dataclass(frozen=True, slots=True)
class Decision:
    """Принятое место: `kind` - `agreement` (этажи сошлись) или `filtered` (отрыв после отсева)."""

    kind: str
    choice: FloorChoice
    agreed: int
    floors: int


def choose(choices: Sequence[FloorChoice], centre: Point) -> Decision | None:
    """Место здания по выбору этажей (`choices` - по одному на этаж, отсеянное уже убрано).

    1. Согласие: не меньше `AGREE_MIN_FLOORS` этажей независимо дали одно место (`same_place`),
       их строго больше, чем у любого другого места, доля лучшего из них не ниже `RESERVE_SHARE`.
       Положение - лучшего по доле из согласных: сдвиги разных этажей усреднять нельзя (разный
       поворот при общей точке отсчёта), а лучший этаж даёт одну согласованную пару поворот и сдвиг.
       Два места с равным числом согласных этажей - отказ.
    2. Отсев: лучший по доле этаж проходит порог (`passes`) после отсева конкурентов, хотя до отсева
       не проходил, и ни один другой этаж не проходит порог в другом месте.
    """
    if not choices:
        return None
    support = [sum(same_place(c.best, d.best, centre) for d in choices) for c in choices]
    ranked = sorted(range(len(choices)), key=lambda i: (-support[i], -choices[i].best.share, i))
    lead = ranked[0]
    leader = choices[lead]
    rivals = [
        support[i] for i, c in enumerate(choices) if not same_place(c.best, leader.best, centre)
    ]
    rival = max(rivals, default=0)
    if support[lead] >= AGREE_MIN_FLOORS:
        if support[lead] <= rival:
            return None  # два места с равным числом согласных: не принимать
        if leader.best.share >= RESERVE_SHARE:
            return Decision("agreement", leader, support[lead], len(choices))
        # Слабое согласие (доля ниже порога резерва) места не даёт; решает отсев.
    top = max(choices, key=lambda c: (c.best.share, -c.floor))
    if (
        passes(top.best.share, top.second)
        and not passes(top.match.share, top.match.second_share)
        and not any(
            passes(c.best.share, c.second) and not same_place(c.best, top.best, centre)
            for c in choices
        )
    ):
        return Decision("filtered", top, 1, len(choices))
    return None
