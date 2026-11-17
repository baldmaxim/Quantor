"""Высоты окон плана по видам фасадов (ADR-0048 п. 3-5): сопоставление окон плана и окон фасада.

Чистые функции без базы и хранилища и загрузчик видов проекта. Окно векторного вида фасада
(`cad_facade_views`) даёт подоконник и верх окна в мм от ±0,000; окно плана (`kind = window`
без `opening_height_mm`) получает их, если нашлось однозначное окно фасада того же этажа и той же
стороны здания.

Горизонталь фасада переводится в мм плана только через оси плана: у вида берутся доли страницы
марок осей, у плана - мм тех же осей; перевод `c = a * x + b` - наименьшие квадраты по общим осям.
Горизонтальные мм генератора (`u_mm`, `u0_mm`, `u1_mm`, `width_mm`) не используются (ADR-0048
п. 3), размерные линии не читаются, растр не анализируется. Геометрия - на чистом Python.

Не определено - окно без высоты и замечание с кодом, не 0 и не умолчание. Виды `rejected`, растровые
и без привязки по отметкам (`text_only`, `none`) не берутся.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import WallsOpening
from app.contracts.cad_facades import FacadeAxis, FacadeWindow
from app.contracts.cad_floor3d import WallsOpeningExtras
from app.models import CadFacadeView, DocumentRevision

# Наибольшее отклонение оси вида от перевода по наименьшим квадратам (при трёх и более осях).
AXES_FIT_TOLERANCE_MM: Final = 150.0
MIN_AXES: Final = 2
MIN_AXES_FOR_CHECK: Final = 3
# На сколько мм от центра окна по нормали проверяется, лежит ли точка вне плиты.
OUTWARD_PROBE_MM: Final = 600.0
# Окно плана на стороне фасада, если угол между нормалями не больше 20 градусов.
SIDE_COS_MIN: Final = math.cos(math.radians(20.0))
# Допуск этажа по z: окно фасада - этажа плана, если низ окна в [z_f - 300, z_f + h - 300).
FLOOR_Z_MARGIN_MM: Final = 300.0
# Доля длины окна плана, перекрытая окном фасада, при которой они сопоставляются.
MIN_OVERLAP: Final = 0.5
# Расхождение высот двух видов одного приоритета, при котором окно не назначается.
HEIGHT_CONFLICT_MM: Final = 50

ACCEPTABLE_SCALES: Final = ("fitted", "weak")
LOADED_STATUSES: Final = ("accepted", "candidate")

CODE_NO_LEVEL: Final = "facade_windows_no_level"
CODE_NO_SLAB: Final = "facade_windows_no_slab"
CODE_NOT_LINKED: Final = "facade_view_not_linked"
CODE_ORIENTATION: Final = "facade_view_orientation_ambiguous"
CODE_AXES_MISMATCH: Final = "facade_view_axes_mismatch"
CODE_NOT_OUTER: Final = "facade_window_not_on_outer_wall"
CODE_AMBIGUOUS: Final = "facade_window_ambiguous"
CODE_HIDDEN: Final = "facade_window_hidden"
CODE_CONFLICT: Final = "facade_window_height_conflict"
CODE_INVALID: Final = "facade_window_height_invalid"
CODE_UNITS_MISMATCH: Final = "facade_view_not_consistent"
CODE_OTHER_BUILDING: Final = "facade_views_other_building"
CODE_VIEW_INVALID: Final = "facade_view_invalid"
# Окна с одной глубиной (разница проекций центров на нормаль не больше) не закрывают друг друга.
DEPTH_TOLERANCE_MM: Final = 300.0
# Сверка расстояний между осями вида (`u_mm`, только справочно) и плана: допуск 3 % или 150 мм.
UNITS_REL_TOLERANCE: Final = 0.03
UNITS_ABS_TOLERANCE_MM: Final = 150.0

_MESSAGES: Final = {
    CODE_UNITS_MISMATCH: (
        "Вид фасада не согласован с осями плана: расстояния между осями вида и плана "
        "расходятся, окна вида пропущены."
    ),
    CODE_OTHER_BUILDING: (
        "Виды фасадов проекта относятся к другому корпусу или секции: окна листа по фасадам "
        "не сопоставлены."
    ),
    CODE_NO_LEVEL: ("Окна по фасадам не сопоставлены: у листа нет отметки этажа или высоты этажа."),
    CODE_NO_SLAB: "Окна по фасадам не сопоставлены: у листа нет контура плиты.",
    CODE_NOT_LINKED: (
        "Вид фасада не привязан к осям плана: общих осей меньше двух, окна вида пропущены."
    ),
    CODE_ORIENTATION: (
        "Вид фасада не привязан к осям плана: направление осей неоднозначно, окна вида пропущены."
    ),
    CODE_AXES_MISMATCH: (
        "Вид фасада не привязан к осям плана: расстояния между осями расходятся, окна вида "
        "пропущены."
    ),
    CODE_NOT_OUTER: "Окно плана не на наружной стороне контура плиты: по фасаду не сопоставлено.",
    CODE_AMBIGUOUS: "Окно плана неоднозначно сопоставляется с окнами фасада: высота не назначена.",
    CODE_HIDDEN: (
        "Окно плана не видно на фасаде (закрыто остеклением перед ним): высота не назначена."
    ),
    CODE_CONFLICT: "Виды фасадов дают окну разную высоту: высота не назначена.",
    CODE_INVALID: "Окно фасада с некорректной высотой (верх не выше низа): высота не назначена.",
}
_KEPT_WITH_MANUAL: Final = (CODE_VIEW_INVALID, CODE_CONFLICT)
_WINDOW_CODES: Final = (CODE_AMBIGUOUS, CODE_HIDDEN, CODE_CONFLICT, CODE_INVALID, CODE_NOT_OUTER)

Point = tuple[float, float]
Orientation = Literal["vertical", "horizontal"]


@dataclass(frozen=True, slots=True)
class FacadeViewInput:
    """Вид фасада для сопоставления: данные строки `cad_facade_views` без лишнего."""

    id: uuid.UUID
    revision_id: uuid.UUID
    view_key: str
    page_index: int
    title: str
    corps: str | None
    section: str | None
    accepted: bool
    scale_status: str
    axes: tuple[FacadeAxis, ...]
    windows: tuple[FacadeWindow, ...]


@dataclass(frozen=True, slots=True)
class FacadeWindowHeight:
    """Высота окна плана: от чистого пола листа, мм; с вида фасада (`observed`) или ручная."""

    sill_mm: int
    head_mm: int
    accepted: bool
    view_id: uuid.UUID | None
    view_key: str | None
    page_index: int | None
    revision_id: uuid.UUID | None
    title: str | None
    overlap: float
    axes_checked: bool
    # `facade` - вид фасада; `manual` - ручной ввод листа (ADR-0048 п. 5), поля вида пусты.
    source: Literal["facade", "manual"] = "facade"


@dataclass(frozen=True, slots=True)
class MatchIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SheetLevel:
    """Уровень листа плана: чистый пол (мм от ±0,000), высота этажа, известна ли отметка."""

    floor_z_mm: int | None
    floor_height_mm: int | None
    elevation_known: bool


@dataclass(frozen=True, slots=True)
class FacadeMatch:
    heights: Mapping[str, FacadeWindowHeight] = field(default_factory=dict)
    issues: tuple[MatchIssue, ...] = ()


# --------------------------------------------------------------------------- геометрия


def point_in_ring(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    """Точка в многоугольнике: чётно-нечётное правило (луч вправо); граница не определена."""
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _unit(dx: float, dy: float) -> Point | None:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (dx / length, dy / length)


@dataclass(frozen=True, slots=True)
class _PlanWindow:
    opening_id: str
    points: tuple[Point, ...]
    center: Point
    outward: Point | None


def _contour_direction(points: Sequence[Point]) -> Point | None:
    """Направление вдоль стены по длинной стороне контура (если `direction` в файле нет)."""
    if len(points) < 3:
        return None
    first = (points[1][0] - points[0][0], points[1][1] - points[0][1])
    second = (points[2][0] - points[1][0], points[2][1] - points[1][1])
    chosen = first if math.hypot(*first) >= math.hypot(*second) else second
    return _unit(chosen[0], chosen[1])


def _plan_window(
    opening: WallsOpening,
    extra: WallsOpeningExtras | None,
    slab_shell: Sequence[Sequence[float]],
) -> _PlanWindow | None:
    """Окно плана: контур проёма, центр и наружная нормаль по плите; нет контура - `None`."""
    raw = opening.lintel if opening.lintel else (None if extra is None else extra.lintel)
    if raw is None or len(raw) < 3 or any(len(p) < 2 for p in raw):
        return None
    points = tuple((float(p[0]), float(p[1])) for p in raw)
    center = (
        math.fsum(p[0] for p in points) / len(points),
        math.fsum(p[1] for p in points) / len(points),
    )
    along: Point | None = None
    if extra is not None and extra.direction is not None and len(extra.direction) >= 2:
        along = _unit(extra.direction[0], extra.direction[1])
    if along is None:
        along = _contour_direction(points)
    if along is None:
        return _PlanWindow(opening.id, points, center, None)
    normal = (-along[1], along[0])
    plus = point_in_ring(
        center[0] + normal[0] * OUTWARD_PROBE_MM,
        center[1] + normal[1] * OUTWARD_PROBE_MM,
        slab_shell,
    )
    minus = point_in_ring(
        center[0] - normal[0] * OUTWARD_PROBE_MM,
        center[1] - normal[1] * OUTWARD_PROBE_MM,
        slab_shell,
    )
    outward: Point | None
    if not plus and minus:
        outward = normal
    elif plus and not minus:
        outward = (-normal[0], -normal[1])
    else:
        outward = None
    return _PlanWindow(opening.id, points, center, outward)


# --------------------------------------------------------------------------- привязка вида


@dataclass(frozen=True, slots=True)
class _LinkedView:
    view: FacadeViewInput
    orientation: Orientation
    a: float
    b: float
    axes_checked: bool
    # Наружная нормаль фасада в плоскости плана (мм DXF, y вверх).
    normal: Point


def _matches(
    axes: Sequence[FacadeAxis], plan_axes: Mapping[str, float]
) -> dict[str, tuple[float, float, int | None]]:
    """Общие оси: метка оси плана -> (доля страницы вида, мм плана, `u_mm` вида)."""
    found: dict[str, tuple[float, float, int | None]] = {}
    for axis in axes:
        for key in (axis.label, axis.label_full):
            if key and key in plan_axes:
                found.setdefault(key, (axis.x, plan_axes[key], axis.u_mm))
                break
    return found


def _units_consistent(pairs: Sequence[tuple[float, float, int | None]]) -> bool | None:
    """Сверка расстояний между осями: план против `u_mm` вида (только проверка, не вход).

    `None` - у менее чем двух общих осей есть `u_mm`. Расхождение допускается до большего из
    3 % расстояния и 150 мм.
    """
    with_units = [(c, u) for _x, c, u in pairs if u is not None]
    if len(with_units) < MIN_AXES:
        return None
    first_plan, first_units = with_units[0]
    for plan, units in with_units[1:]:
        plan_distance = abs(plan - first_plan)
        tolerance = max(UNITS_REL_TOLERANCE * plan_distance, UNITS_ABS_TOLERANCE_MM)
        if abs(plan_distance - abs(units - first_units)) > tolerance:
            return False
    return True


def _fit(pairs: Sequence[tuple[float, float]]) -> tuple[float, float, float] | None:
    """`c = a * x + b` наименьшими квадратами: (a, b, наибольшее отклонение) или None."""
    n = len(pairs)
    mean_x = math.fsum(x for x, _ in pairs) / n
    mean_c = math.fsum(c for _, c in pairs) / n
    sxx = math.fsum((x - mean_x) ** 2 for x, _ in pairs)
    if sxx < 1e-12:
        return None
    a = math.fsum((x - mean_x) * (c - mean_c) for x, c in pairs) / sxx
    if abs(a) < 1e-9:
        return None
    b = mean_c - a * mean_x
    return a, b, max(abs(a * x + b - c) for x, c in pairs)


def _side_normal(orientation: Orientation, a: float) -> Point:
    """Наружная нормаль по знаку `a`: лицом к фасаду справа растёт координата (DXF, y вверх)."""
    if orientation == "vertical":
        return (0.0, -1.0) if a > 0 else (0.0, 1.0)
    return (1.0, 0.0) if a > 0 else (-1.0, 0.0)


def _link_view(
    view: FacadeViewInput, vertical: Mapping[str, float], horizontal: Mapping[str, float]
) -> _LinkedView | MatchIssue:
    by_vertical = _matches(view.axes, vertical)
    by_horizontal = _matches(view.axes, horizontal)
    count_v, count_h = len(by_vertical), len(by_horizontal)
    if max(count_v, count_h) < MIN_AXES:
        return MatchIssue(CODE_NOT_LINKED, _MESSAGES[CODE_NOT_LINKED])
    if count_v == count_h:
        return MatchIssue(CODE_ORIENTATION, _MESSAGES[CODE_ORIENTATION])
    orientation: Orientation = "vertical" if count_v > count_h else "horizontal"
    triples = list((by_vertical if orientation == "vertical" else by_horizontal).values())
    fitted = _fit([(x, c) for x, c, _u in triples])
    if fitted is None:
        return MatchIssue(CODE_NOT_LINKED, _MESSAGES[CODE_NOT_LINKED])
    a, b, deviation = fitted
    checked = len(triples) >= MIN_AXES_FOR_CHECK
    if checked and deviation > AXES_FIT_TOLERANCE_MM:
        return MatchIssue(CODE_AXES_MISMATCH, _MESSAGES[CODE_AXES_MISMATCH])
    units = _units_consistent(triples)
    if units is False:
        return MatchIssue(CODE_UNITS_MISMATCH, _MESSAGES[CODE_UNITS_MISMATCH])
    return _LinkedView(
        view, orientation, a, b, checked or units is True, _side_normal(orientation, a)
    )


def _norm(value: str | None) -> str | None:
    """Корпус или секция как в `group_of`: пробелы схлопнуты, регистр не важен."""
    text = " ".join(value.split()).casefold() if value else ""
    return text or None


def _same_building(view: FacadeViewInput, corps: str | None, section: str | None) -> bool:
    """Вид пропускается, если у вида и плана заданы оба корпуса (или обе секции) и они разные."""
    view_corps, plan_corps = _norm(view.corps), _norm(corps)
    if view_corps and plan_corps and view_corps != plan_corps:
        return False
    view_section, plan_section = _norm(view.section), _norm(section)
    return not (view_section and plan_section and view_section != plan_section)


# --------------------------------------------------------------------------- сопоставление


@dataclass(frozen=True, slots=True)
class _Candidate:
    height: FacadeWindowHeight
    # Приоритет: меньше - лучше; (принят: 0, fitted: 0).
    rank: tuple[int, int]


def _span(values: Sequence[float]) -> tuple[float, float]:
    return (min(values), max(values))


def _overlap(first: tuple[float, float], second: tuple[float, float]) -> float:
    return max(0.0, min(first[1], second[1]) - max(first[0], second[0]))


def _candidates_of_view(
    linked: _LinkedView,
    windows: Sequence[_PlanWindow],
    pending_ids: Collection[str],
    level: SheetLevel,
    reasons: dict[str, set[str]],
) -> dict[str, _Candidate]:
    """Высоты окон плана с одного вида; причины отказов пишутся в `reasons` по id окна плана.

    `windows` - все окна листа с контуром, `pending_ids` - те из них, что без своей высоты.
    """
    view = linked.view
    floor_z = float(level.floor_z_mm or 0)
    floor_height = float(level.floor_height_mm or 0)
    floor_windows = [
        w
        for w in view.windows
        if floor_z - FLOOR_Z_MARGIN_MM <= w.z_bottom_mm < floor_z + floor_height - FLOOR_Z_MARGIN_MM
    ]
    facade_spans = [
        _span((linked.a * w.bbox[0] + linked.b, linked.a * w.bbox[2] + linked.b))
        for w in floor_windows
    ]
    index = 0 if linked.orientation == "vertical" else 1
    # fi -> [(окно плана, перекрытие)]
    taken: dict[int, list[tuple[_PlanWindow, float]]] = defaultdict(list)
    for window in windows:
        outward = window.outward
        if outward is None:
            if window.opening_id in pending_ids:
                reasons[window.opening_id].add(CODE_NOT_OUTER)
            continue
        if outward[0] * linked.normal[0] + outward[1] * linked.normal[1] < SIDE_COS_MIN:
            continue
        plan_span = _span([p[index] for p in window.points])
        length = plan_span[1] - plan_span[0]
        if length <= 0:
            continue
        ratios = sorted(
            ((_overlap(plan_span, span) / length, fi) for fi, span in enumerate(facade_spans)),
            reverse=True,
        )
        if not ratios or ratios[0][0] < MIN_OVERLAP:
            continue
        if len(ratios) > 1 and ratios[1][0] >= MIN_OVERLAP:
            if window.opening_id in pending_ids:
                reasons[window.opening_id].add(CODE_AMBIGUOUS)
            continue
        taken[ratios[0][1]].append((window, ratios[0][0]))
    result: dict[str, _Candidate] = {}
    rank = (0 if view.accepted else 1, 0 if view.scale_status == "fitted" else 1)

    def depth(window: _PlanWindow) -> float:
        return window.center[0] * linked.normal[0] + window.center[1] * linked.normal[1]

    for fi, group in taken.items():
        # Остекление перед окном глубже закрывает его: высота - только окнам на той же глубине,
        # что и самое наружное (разница проекций центров на нормаль не больше 300 мм). В расчёт
        # закрытия входят и окна со своей высотой из walls.json, но высоту они не получают.
        front = max(depth(item[0]) for item in group)
        for window, overlap in group:
            if window.opening_id not in pending_ids:
                continue
            if front - depth(window) > DEPTH_TOLERANCE_MM:
                reasons[window.opening_id].add(CODE_HIDDEN)
                continue
            facade = floor_windows[fi]
            sill = max(0, round(facade.z_bottom_mm - floor_z))
            head = round(facade.z_top_mm - floor_z)
            if head <= sill:
                reasons[window.opening_id].add(CODE_INVALID)
                continue
            result[window.opening_id] = _Candidate(
                FacadeWindowHeight(
                    sill_mm=sill,
                    head_mm=head,
                    accepted=view.accepted,
                    view_id=view.id,
                    view_key=view.view_key,
                    page_index=view.page_index,
                    revision_id=view.revision_id,
                    title=view.title,
                    overlap=round(overlap, 3),
                    axes_checked=linked.axes_checked,
                ),
                rank,
            )
    return result


def _resolve(candidates: Sequence[_Candidate]) -> FacadeWindowHeight | None:
    """Лучший по приоритету (принят > кандидат, fitted > weak, перекрытие); конфликт - `None`."""
    best_rank = min(c.rank for c in candidates)
    top = [c for c in candidates if c.rank == best_rank]
    chosen = max(top, key=lambda c: c.height.overlap)
    for other in top:
        if (
            abs(other.height.sill_mm - chosen.height.sill_mm) > HEIGHT_CONFLICT_MM
            or abs(other.height.head_mm - chosen.height.head_mm) > HEIGHT_CONFLICT_MM
        ):
            return None
    return chosen.height


def match_sheet_windows(
    *,
    openings: Sequence[WallsOpening],
    extras: Sequence[WallsOpeningExtras],
    slab_shell: Sequence[Sequence[float]] | None,
    vertical_axes: Mapping[str, float],
    horizontal_axes: Mapping[str, float],
    corps: str | None,
    section: str | None,
    level: SheetLevel,
    views: Sequence[FacadeViewInput],
    invalid_views: int = 0,
) -> FacadeMatch:
    """Высоты окон плана без `opening_height_mm` по видам фасадов; замечания без умолчаний.

    Нет окон без высоты или нет видов - пустой результат без замечаний. Закрытие окна остеклением
    перед ним считается по всем окнам листа с контуром, в том числе со своей высотой из walls.json;
    высоту получают только окна без своей. `invalid_views` - виды с данными вне контракта.
    """
    pending = [o for o in openings if o.kind == "window" and o.opening_height_mm is None]
    if not pending:
        return FacadeMatch()
    invalid = (
        [
            MatchIssue(
                CODE_VIEW_INVALID,
                f"Виды фасадов с данными вне контракта пропущены: {invalid_views}.",
            )
        ]
        if invalid_views
        else []
    )
    if not views:
        return FacadeMatch(issues=tuple(invalid))
    if not level.elevation_known or level.floor_z_mm is None or not level.floor_height_mm:
        return FacadeMatch(issues=(MatchIssue(CODE_NO_LEVEL, _MESSAGES[CODE_NO_LEVEL]), *invalid))
    if slab_shell is None or len(slab_shell) < 3:
        return FacadeMatch(issues=(MatchIssue(CODE_NO_SLAB, _MESSAGES[CODE_NO_SLAB]), *invalid))
    extra_by_id = {item.id: item for item in extras}
    windows = [
        w
        for o in openings
        if o.kind == "window" and (w := _plan_window(o, extra_by_id.get(o.id), slab_shell))
    ]
    pending_ids = {o.id for o in pending}
    issues: list[MatchIssue] = list(invalid)
    reasons: dict[str, set[str]] = defaultdict(set)
    per_window: dict[str, list[_Candidate]] = defaultdict(list)
    same_building = [view for view in views if _same_building(view, corps, section)]
    if not same_building:
        return FacadeMatch(
            issues=(MatchIssue(CODE_OTHER_BUILDING, _MESSAGES[CODE_OTHER_BUILDING]), *invalid)
        )
    for view in same_building:
        linked = _link_view(view, vertical_axes, horizontal_axes)
        if isinstance(linked, MatchIssue):
            issues.append(linked)
            continue
        for opening_id, candidate in _candidates_of_view(
            linked, windows, pending_ids, level, reasons
        ).items():
            per_window[opening_id].append(candidate)
    heights: dict[str, FacadeWindowHeight] = {}
    for window in windows:
        if window.opening_id not in pending_ids:
            continue
        found = per_window.get(window.opening_id)
        if found:
            resolved = _resolve(found)
            if resolved is None:
                reasons[window.opening_id].add(CODE_CONFLICT)
            else:
                heights[window.opening_id] = resolved
                continue
        for code in _WINDOW_CODES:
            if code in reasons.get(window.opening_id, ()):
                issues.append(MatchIssue(code, _MESSAGES[code]))
    return FacadeMatch(heights, tuple(issues))


def merge_manual_heights(
    match: FacadeMatch,
    openings: Sequence[WallsOpening],
    sill_mm: int | None,
    head_mm: int | None,
) -> FacadeMatch:
    """Высоты окон без `opening_height_mm`: принятый вид фасада > ручной ввод листа > кандидат.

    Ручной ввод (`sill_mm`, `head_mm` - оба или ни одного) считается проверенным человеком:
    `accepted = true`. Окно, у которого уже есть принятая высота фасада, её сохраняет; кандидат
    фасада уступает ручному вводу. Ручной ввод покрывает все окна без высоты листа, поэтому
    оконные замечания сопоставления снимаются; `facade_view_invalid` и конфликт высот принятых
    видов остаются. Без ручного ввода результат - `match` как есть.
    """
    if sill_mm is None or head_mm is None:
        return match
    pending = [o.id for o in openings if o.kind == "window" and o.opening_height_mm is None]
    if not pending:
        return match
    manual = FacadeWindowHeight(
        sill_mm=sill_mm,
        head_mm=head_mm,
        accepted=True,
        view_id=None,
        view_key=None,
        page_index=None,
        revision_id=None,
        title=None,
        overlap=0.0,
        axes_checked=False,
        source="manual",
    )
    heights: dict[str, FacadeWindowHeight] = dict(match.heights)
    for opening_id in pending:
        found = heights.get(opening_id)
        if found is None or not found.accepted:
            heights[opening_id] = manual
    # Каждое окно без высоты теперь имеет принятую (фасад или ручной ввод): оконным замечаниям
    # сопоставления нечего сообщать. Данные видов вне контракта и конфликт высот принятых видов
    # остаются: это сведения о самих видах, ручной ввод их не отменяет.
    kept = tuple(i for i in match.issues if i.code in _KEPT_WITH_MANUAL)
    return FacadeMatch(heights, kept)


@dataclass(frozen=True, slots=True)
class SheetAxes:
    """Оси плана листа в мм DXF для сопоставления с видами фасадов или причина, почему их нет.

    `issue` - кадр вида не подтверждён или осей на плане нет: окна по фасадам не сопоставляются.
    """

    vertical: Mapping[str, float] = field(default_factory=dict)
    horizontal: Mapping[str, float] = field(default_factory=dict)
    issue: MatchIssue | None = None


def sheet_window_heights(
    *,
    loaded: LoadedViews,
    openings: Sequence[WallsOpening],
    extras: Sequence[WallsOpeningExtras],
    slab_shell: Sequence[Sequence[float]] | None,
    axes: SheetAxes | None,
    corps: str | None,
    section: str | None,
    level: SheetLevel,
    manual_sill_mm: int | None,
    manual_head_mm: int | None,
) -> FacadeMatch:
    """Высоты окон листа без `opening_height_mm`: общий расчёт для 3D этажа, объёма и 3D здания.

    Приоритет: принятый вид фасада, ручной ввод листа (`manual_*`, проверен человеком), вид-кандидат
    фасада, затем высоты нет. `axes` нужны только при наличии видов; кадр не подтверждён или осей
    нет - карта пустая и замечание (ручной ввод осей не требует). Нет окон без высоты - пусто.
    """
    if not any(o.kind == "window" and o.opening_height_mm is None for o in openings):
        return FacadeMatch()
    vertical: Mapping[str, float] = {}
    horizontal: Mapping[str, float] = {}
    match: FacadeMatch
    if loaded.views and axes is not None and axes.issue is not None:
        match = FacadeMatch(issues=(axes.issue,))
    else:
        if loaded.views and axes is not None:
            vertical, horizontal = axes.vertical, axes.horizontal
        match = match_sheet_windows(
            openings=openings,
            extras=extras,
            slab_shell=slab_shell,
            vertical_axes=vertical,
            horizontal_axes=horizontal,
            corps=corps,
            section=section,
            level=level,
            views=loaded.views,
            invalid_views=loaded.invalid,
        )
    return merge_manual_heights(match, openings, manual_sill_mm, manual_head_mm)


def grouped_warnings(issues: Sequence[MatchIssue]) -> list[tuple[str, str]]:
    """Замечания по кодам, не по строке на окно: `(код, текст)`; при повторах - число случаев."""
    counts = Counter(issue.code for issue in issues)
    first: dict[str, str] = {}
    for issue in issues:
        first.setdefault(issue.code, issue.message)
    return [
        (code, message if counts[code] == 1 else f"{message} Случаев: {counts[code]}.")
        for code, message in first.items()
    ]


# --------------------------------------------------------------------------- загрузчик


@dataclass(frozen=True, slots=True)
class LoadedViews:
    views: list[FacadeViewInput]
    # Видов с данными вне контракта (пропущены, не молча: замечание `facade_view_invalid`).
    invalid: int = 0


_AXES_ADAPTER: Final = TypeAdapter(list[FacadeAxis])
_WINDOWS_ADAPTER: Final = TypeAdapter(list[FacadeWindow])


async def _latest_revisions(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """По одной последней ревизии каждого документа среди ревизий проекта, у которых есть виды."""
    rows = await session.execute(
        select(CadFacadeView.revision_id, DocumentRevision.document_id, DocumentRevision.created_at)
        .join(DocumentRevision, DocumentRevision.id == CadFacadeView.revision_id)
        .where(CadFacadeView.project_id == project_id)
        .distinct()
    )
    latest: dict[uuid.UUID, tuple[datetime, uuid.UUID]] = {}
    for revision_id, document_id, created_at in rows.all():
        current = latest.get(document_id)
        if current is None or (created_at, revision_id) > current:
            latest[document_id] = (created_at, revision_id)
    return [revision_id for _created, revision_id in latest.values()]


async def load_views(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> LoadedViews:
    """Виды фасадов проекта: принятые и кандидаты, векторные, с привязкой и окнами.

    Берутся только виды последней ревизии каждого документа (из ревизий, у которых есть виды):
    виды старых ревизий не используются. Отклонённые, растровые, без привязки по отметкам и без
    окон не берутся. Строка с данными вне контракта пропускается и считается в `invalid`.
    """
    revisions = await _latest_revisions(session, project_id)
    if not revisions:
        return LoadedViews([])
    rows = await session.execute(
        select(
            CadFacadeView.id,
            CadFacadeView.revision_id,
            CadFacadeView.view_key,
            CadFacadeView.page_index,
            CadFacadeView.title,
            CadFacadeView.corps,
            CadFacadeView.section,
            CadFacadeView.status,
            CadFacadeView.scale_status,
            CadFacadeView.axes,
            CadFacadeView.windows,
        )
        .where(
            CadFacadeView.workspace_id == workspace_id,
            CadFacadeView.project_id == project_id,
            CadFacadeView.revision_id.in_(revisions),
            CadFacadeView.status.in_(LOADED_STATUSES),
            CadFacadeView.scale_status.in_(ACCEPTABLE_SCALES),
            CadFacadeView.body == "vector",
            CadFacadeView.window_count > 0,
        )
        .order_by(CadFacadeView.revision_id, CadFacadeView.page_index, CadFacadeView.seq)
    )
    views: list[FacadeViewInput] = []
    invalid = 0
    for row in rows.all():
        try:
            axes = tuple(_AXES_ADAPTER.validate_python(row.axes))
            windows = tuple(_WINDOWS_ADAPTER.validate_python(row.windows))
        except ValidationError:
            invalid += 1
            continue
        views.append(
            FacadeViewInput(
                id=row.id,
                revision_id=row.revision_id,
                view_key=row.view_key,
                page_index=row.page_index,
                title=row.title,
                corps=row.corps,
                section=row.section,
                accepted=row.status == "accepted",
                scale_status=row.scale_status,
                axes=axes,
                windows=windows,
            )
        )
    return LoadedViews(views, invalid)
