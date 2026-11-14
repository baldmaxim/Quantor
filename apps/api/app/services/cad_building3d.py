"""Общий вид здания для 3D: этажи проекта (листы CAD) с отметками и контуром плиты.

Этаж — тройка (задание `cad_pdf_convert`, страница, вид) с последним успешным `cad_walls`.
Из `walls.json` берётся контур плиты (или прямоугольник по стенам) и высоты; по запросу
(`include_walls`) - ещё внешние кольца конструкций. Модель этажа целиком (двери, зоны) здесь не
строится. Высоты — действующие значения листа, те же, что
в `cad_floor3d.build_floor3d` (`cad_constructions.effective_levels`).

Этажи делятся на здания по корпусу и секции из заголовка плана; этажи одного здания совмещаются
в плане по общим осям (`axes` в walls.json, pt -> мм по кадру вида): смещение уже применено к
контуру. Затем здания ставятся на объект по общим маркам осей (`place_groups`): опора - здание с
наибольшим числом общих марок (обычно паркинг), смещение тоже применено, клиент получает геометрию
поставленных зданий в системе объекта, не поставленных - в системе эталонного этажа группы.

Порядок работы: сначала всё нужное из базы — последовательно (сессия не конкурентна), затем
`walls.json` листов читаются из хранилища параллельно с ограничением, проверка контракта и сборка
этажа идут в потоке. Этаж листа до совмещения запоминается в памяти процесса (`floor_cache`) по
ключам артефактов и высотам: повторное открытие не читает и не разбирает walls.json заново.
Ошибка одного листа не валит ответ: лист пропускается с предупреждением. В итоги обмера, calc и
MEP вид не входит.
"""

from __future__ import annotations

import asyncio
import math
import re
import statistics
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import CadFrameRead
from app.contracts.cad_building3d import (
    CadBuilding3dFloorRead,
    CadBuilding3dGroupRead,
    CadBuilding3dLevelZoneRead,
    CadBuilding3dPlacement,
    CadBuilding3dRead,
    CadBuilding3dWallRead,
    CadBuilding3dWarningRead,
)
from app.contracts.cad_constructions import CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras, WallsLevels
from app.domain import JobStatus, JobType
from app.models import Document, DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_construction_store, cad_site_cores, cad_views, cad_walls
from app.services.cad_constructions import ProjectSlab, effective_levels
from app.services.cad_floor_title import format_floor_title
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

MAX_OUTLINE_POINTS: Final = 200
# Контуры конструкций (`walls=true`): предел числа на этаж и точек в кольце.
MAX_WALLS_PER_FLOOR: Final = 4000
MAX_WALL_POINTS: Final = 64
# Участки уровней плиты этажа (cad_walls v1.15): число и точки кольца участка.
MAX_LEVEL_ZONES: Final = 300
MAX_LEVEL_POINTS: Final = 400
READ_CONCURRENCY: Final = 6
# Для отрисовки, когда высота этажа или толщина плиты не определены (помечаются `*_known = false`).
DEFAULT_FLOOR_HEIGHT_MM: Final = 3000
DEFAULT_SLAB_THICKNESS_MM: Final = 200
# Допуск расхождения смещений по общим осям: больше - оси разных этажей «не сходятся».
AXIS_TOLERANCE_MM: Final = 150.0
# Минимальная доля перекрытия bbox совмещённого этажа с эталоном (от меньшего bbox).
MIN_ALIGN_OVERLAP: Final = 0.3
GROUP_NONE_KEY: Final = "none"
GROUP_NONE_LABEL: Final = "Корпус не указан"
MESSAGE_AXES_OUTDATED: Final = "оси не распознаны: пересчитайте конструкции листа"
MESSAGE_AXES_EMPTY: Final = "оси на листе не распознаны"
MESSAGE_FRAME_MISSING: Final = "кадр вида не установлен"
MESSAGE_NO_REFERENCE: Final = "в группе нет этажа с осями в обоих направлениях"
# Постановка зданий на объект: не меньше марок всего и доля согласованных среди общих.
SITE_MIN_AXES: Final = 3
SITE_MIN_AGREEMENT: Final = 0.75
# Этажи двух зданий «на одной отметке» и предел их перекрытия в плане (доля меньшего bbox).
SITE_SAME_LEVEL_MM: Final = 300
SITE_MAX_OVERLAP: Final = 0.3
SITE_PREFIXED_LABEL: Final = re.compile(r"\d{1,2}[.\-]")
# Ядра для постановки по совпадению монолита: стены и пилоны (колонны паркинга периодичны).
CORE_KINDS: Final = frozenset({"monolith_wall", "monolith_pylon"})
# Нижних этажей скопления, пробуемых по одному, и наименьшее число колец ядер этажа.
CORE_TRY_FLOORS: Final = 6
CORE_MIN_RINGS: Final = 4

Point = tuple[float, float]


# --------------------------------------------------------------------------- геометрия


def _distance_to_line(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dx * (a[1] - p[1]) - dy * (a[0] - p[0])) / length


def _douglas_peucker(points: Sequence[Point], epsilon: float) -> list[Point]:
    """Дуглас - Пекер для открытой ломаной; концы сохраняются. Без рекурсии."""
    count = len(points)
    if count <= 2:
        return list(points)
    keep = [False] * count
    keep[0] = keep[-1] = True
    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        far_index, far_distance = -1, 0.0
        for index in range(first + 1, last):
            distance = _distance_to_line(points[index], points[first], points[last])
            if distance > far_distance:
                far_index, far_distance = index, distance
        if far_index != -1 and far_distance > epsilon:
            keep[far_index] = True
            stack.append((first, far_index))
            stack.append((far_index, last))
    return [point for point, kept in zip(points, keep, strict=True) if kept]


def _open_ring(ring: Sequence[Sequence[float]]) -> list[Point]:
    """Кольцо без замыкающей точки и без подряд идущих повторов."""
    points: list[Point] = []
    for item in ring:
        point = (float(item[0]), float(item[1]))
        if not points or point != points[-1]:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def simplify_ring(
    ring: Sequence[Sequence[float]], max_points: int = MAX_OUTLINE_POINTS
) -> list[list[float]]:
    """Контур не более `max_points` точек: Дуглас - Пекер замкнутого кольца.

    Кольцо делится на две ломаные по точке 0 и самой удалённой от неё, допуск растёт, пока
    точек не станет достаточно мало. Замыкающая точка не дублируется.
    """
    points = _open_ring(ring)
    if len(points) <= max_points:
        return [[x, y] for x, y in points]
    far = max(range(1, len(points)), key=lambda i: math.hypot(*_sub(points[i], points[0])))
    left = points[: far + 1]
    right = [*points[far:], points[0]]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    epsilon = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2000.0
    for _ in range(80):
        simplified = [
            *_douglas_peucker(left, epsilon)[:-1],
            *_douglas_peucker(right, epsilon)[:-1],
        ]
        if len(simplified) <= max_points:
            return [[x, y] for x, y in simplified]
        epsilon = max(epsilon * 1.5, 1e-6)
    step = len(points) / max_points
    return [[points[int(i * step)][0], points[int(i * step)][1]] for i in range(max_points)]


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def bbox_of(rings: Sequence[Sequence[Sequence[float]]]) -> list[float] | None:
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _rectangle(box: Sequence[float]) -> list[list[float]]:
    minx, miny, maxx, maxy = box
    return [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy]]


def _round_mm(value: float) -> int:
    """Округление к ближайшему целому мм (половина - вверх): разные целые не склеиваются."""
    return math.floor(value + 0.5)


def wall_ring(shell: Sequence[Sequence[float]]) -> list[list[int]] | None:
    """Кольцо конструкции для вида: открытое, целые мм, без подряд идущих дублей.

    Больше `MAX_WALL_POINTS` точек - Дуглас - Пекер (`simplify_ring`): сохраняет углы и берёт
    подмножество исходных точек; прореживание «через одну» срезало бы углы стен. Меньше трёх
    точек - `None` (вырожденное кольцо).
    """
    # Один проход: округление и снятие подряд идущих дублей (стен на объекте - десятки тысяч).
    floor = math.floor
    points: list[list[int]] = []
    for p in shell:
        x, y = floor(p[0] + 0.5), floor(p[1] + 0.5)
        if not points or x != points[-1][0] or y != points[-1][1]:
            points.append([x, y])
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) > MAX_WALL_POINTS:
        simplified = _open_ring(simplify_ring(points, MAX_WALL_POINTS))
        points = [[_round_mm(x), _round_mm(y)] for x, y in simplified]
    return points if len(points) >= 3 else None


# --------------------------------------------------------------------------- лист -> этаж


@dataclass(frozen=True, slots=True)
class SheetRef:
    """Лист CAD, собранный из базы: адрес, подпись, высоты от человека и ключ walls.json."""

    job_id: uuid.UUID
    revision_id: uuid.UUID
    document_id: uuid.UUID
    page_index: int
    view: int
    label: str
    order: tuple[float, float, int, int]
    overrides: CadSheetLevelsRead
    # `None` — последнего успешного `cad_walls` нет или файл не найден в итоге задания.
    walls_key: str | None
    # Масштаб и проверки родительского задания: из них собирается кадр вида (pt -> мм осей).
    scale_key: str | None = None
    checks_key: str | None = None


def group_of(corps: str | None, section: str | None) -> tuple[str, str]:
    """Ключ и подпись здания по корпусу и секции; ни того ни другого - «none»."""
    c, sec = _clean(corps), _clean(section)
    if c is None and sec is None:
        return GROUP_NONE_KEY, GROUP_NONE_LABEL
    key = "-".join(
        part for part in (f"k{_slug(c)}" if c else None, f"s{_slug(sec)}" if sec else None) if part
    )
    parts = [f"Корп. {c}" if c else GROUP_NONE_LABEL]
    if sec:
        parts.append(f"сек. {sec}")
    return key, " · ".join(parts)


def _clean(value: str | None) -> str | None:
    text = " ".join(value.split()) if value else ""
    return text or None


def _slug(value: str) -> str:
    return re.sub(r"[^0-9a-zа-я.]+", "_", value.casefold())


def build_floor(
    sheet: SheetRef,
    document: WallsDocument,
    extras: WallsFloorExtras,
    project_slab: ProjectSlab | None,
    *,
    include_walls: bool = False,
) -> tuple[CadBuilding3dFloorRead, list[CadBuilding3dWarningRead]]:
    """Этаж по walls.json: высоты и контур плиты (или прямоугольник по стенам).

    `include_walls` - добавить контуры конструкций (`floor_slab` пропускается: плита уже в
    `outline`); сверх `MAX_WALLS_PER_FLOOR` лишние отбрасываются с предупреждением.
    """
    levels = effective_levels(document.heights, sheet.overrides, project_slab)
    warnings: list[CadBuilding3dWarningRead] = []
    floor_height = levels.floor_height.value_mm
    thickness = levels.slab_thickness.value_mm
    if floor_height is None:
        warnings.append(
            CadBuilding3dWarningRead(
                code="floor_height_default",
                message=f"{sheet.label}: высота этажа не определена, показана типовая.",
            )
        )
    if thickness is None:
        warnings.append(
            CadBuilding3dWarningRead(
                code="slab_thickness_default",
                message=f"{sheet.label}: толщина плиты не определена, показана типовая.",
            )
        )
    wall_rings: list[Sequence[Sequence[float]]] = [c.polygon.shell for c in document.constructions]
    zones = level_zones(extras.levels, document, levels.base_z_mm, levels.elevation_mm)
    rings = list(wall_rings)
    if extras.slab is not None:
        rings.append(extras.slab.shell)
    rings.extend(zone.shell for zone in zones)
    box = bbox_of(rings)
    outline: list[list[float]]
    source: str
    if extras.slab is not None and len(_open_ring(extras.slab.shell)) >= 3:
        outline, source = simplify_ring(extras.slab.shell), "slab"
    else:
        # План кровли: стен в DXF почти нет, контур - по стенам и участкам уровней.
        fallback_box = bbox_of([*wall_rings, *(zone.shell for zone in zones)])
        if fallback_box is None:
            raise ValueError("нет ни плиты, ни стен")
        outline, source = _rectangle(fallback_box), "bbox"
    tops = construction_tops(extras.levels, document, levels.base_z_mm, levels.elevation_mm)
    title = document.heights.title
    corps = _clean(title.corps) if title is not None else None
    section = _clean(title.section) if title is not None else None
    group_key, group_label = group_of(corps, section)
    walls: list[CadBuilding3dWallRead] | None = None
    if include_walls:
        walls = []
        skipped = 0
        for construction in document.constructions:
            if construction.kind == "floor_slab":
                continue
            ring = wall_ring(construction.polygon.shell)
            if ring is None:
                continue
            if len(walls) >= MAX_WALLS_PER_FLOOR:
                skipped += 1
                continue
            # Поля уже проверены контрактом walls.json (тот же `CadConstructionKind`), кольцо -
            # целые мм из `wall_ring`: повторная проверка тысяч стен только тратит время.
            walls.append(
                CadBuilding3dWallRead.model_construct(
                    id=construction.id,
                    kind=construction.kind,
                    shell=ring,
                    top_mm=tops.get(construction.id),
                )
            )
        if skipped:
            warnings.append(
                CadBuilding3dWarningRead(
                    code="walls_truncated",
                    message=f"{sheet.label}: конструкций больше {MAX_WALLS_PER_FLOOR}, "
                    f"{skipped} не показано.",
                )
            )
    floor = CadBuilding3dFloorRead(
        job_id=sheet.job_id,
        revision_id=sheet.revision_id,
        page_index=sheet.page_index,
        view=sheet.view,
        document_id=sheet.document_id,
        label=format_floor_title(document.heights.title, sheet.label),
        elevation_known=levels.elevation_mm is not None,
        base_z_mm=levels.base_z_mm,
        floor_height_mm=DEFAULT_FLOOR_HEIGHT_MM if floor_height is None else floor_height,
        floor_height_known=floor_height is not None,
        slab_thickness_mm=DEFAULT_SLAB_THICKNESS_MM if thickness is None else thickness,
        slab_thickness_known=thickness is not None,
        outline=outline,
        outline_source="slab" if source == "slab" else "bbox",
        bbox=box,
        corps=corps,
        section=section,
        group_key=group_key,
        group_label=group_label,
        offset_mm=(0.0, 0.0),
        alignment="none",
        alignment_axes=[],
        alignment_message=None,
        kind=title.kind if title is not None else None,
        levels=zones,
        walls=walls,
    )
    return floor, warnings


def _level_shift(document: WallsDocument, base_z_mm: int, elevation_mm: int | None) -> int:
    """Сдвиг отметок walls.json к действующим высотам листа.

    Участки и верх конструкций в walls.json - от отметки листа по документации; если человек задал
    отметку этажа, они сдвигаются вместе с ней. Отметки листа нет ни там, ни там - сдвига нет.
    """
    heights = document.heights
    own = (
        heights.slab_top_elevation_mm
        if heights.slab_top_elevation_mm is not None
        else heights.floor_elevation_mm
    )
    if own is None or elevation_mm is None:
        return 0
    return base_z_mm - own


def _level_ring(ring: Sequence[Sequence[float]]) -> list[list[int]] | None:
    points = _open_ring(ring)
    if len(points) > MAX_LEVEL_POINTS:
        points = _open_ring(simplify_ring(points, MAX_LEVEL_POINTS))
    out = [[_round_mm(x), _round_mm(y)] for x, y in points]
    return out if len(out) >= 3 else None


def level_zones(
    raw: WallsLevels | None, document: WallsDocument, base_z_mm: int, elevation_mm: int | None
) -> list[CadBuilding3dLevelZoneRead]:
    """Участки уровней плиты листа для вида; нет блока или отметок - пусто (одна плита)."""
    if raw is None or not raw.zones:
        return []
    shift = _level_shift(document, base_z_mm, elevation_mm)
    out: list[CadBuilding3dLevelZoneRead] = []
    for zone in raw.zones[:MAX_LEVEL_ZONES]:
        shell = _level_ring(zone.shell)
        top = zone.slab_top_mm if zone.slab_top_mm is not None else zone.mark_mm
        if shell is None or top is None:
            continue
        holes = [ring for ring in (_level_ring(h) for h in zone.holes) if ring is not None]
        out.append(
            CadBuilding3dLevelZoneRead(
                shell=shell,
                holes=holes,
                top_mm=top + shift,
                mark_mm=zone.mark_mm,
                max_mm=zone.max_mm,
                source="marks" if zone.source == "marks" else "base",
            )
        )
    return out


def construction_tops(
    raw: WallsLevels | None, document: WallsDocument, base_z_mm: int, elevation_mm: int | None
) -> dict[str, int]:
    """Верх конструкций по знакам отметок (парапеты), мм от 0.000 в действующих высотах."""
    if raw is None or not raw.construction_tops:
        return {}
    shift = _level_shift(document, base_z_mm, elevation_mm)
    return {top.id: top.top_mm + shift for top in raw.construction_tops}


def sort_floors(
    floors: Sequence[tuple[CadBuilding3dFloorRead, tuple[float, float, int, int]]],
) -> list[CadBuilding3dFloorRead]:
    """Известные отметки — по возрастанию, затем неизвестные в порядке документов и страниц."""
    known = sorted(
        (f for f in floors if f[0].elevation_known), key=lambda f: (f[0].base_z_mm, f[1])
    )
    unknown = sorted((f for f in floors if not f[0].elevation_known), key=lambda f: f[1])
    return [floor for floor, _order in (*known, *unknown)]


# --------------------------------------------------------------------------- оси и совмещение


def _natural_key(text: str) -> list[tuple[int, int, str]]:
    """Естественный порядок: «Корп. 2» раньше «Корп. 10»."""
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
        for part in re.split(r"(\d+)", text)
        if part
    ]


@dataclass(frozen=True, slots=True)
class FloorAxes:
    """Оси этажа в мм DXF: подпись -> координата (x у вертикальных, y у горизонтальных).

    `message` - почему оси непригодны для совмещения (нет блока, нет кадра, одно направление).
    """

    vertical: dict[str, float]
    horizontal: dict[str, float]
    message: str | None

    @property
    def usable(self) -> bool:
        return bool(self.vertical) and bool(self.horizontal)


NO_AXES: Final = FloorAxes({}, {}, MESSAGE_AXES_OUTDATED)


def _axis_rows(raw: Any) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        label, orient, pos = item.get("label"), item.get("orient"), item.get("pos_pt")
        if (
            isinstance(label, str)
            and label.strip()
            and orient in ("vertical", "horizontal")
            and isinstance(pos, int | float)
            and not isinstance(pos, bool)
            and math.isfinite(pos)
        ):
            rows.append((label.strip(), str(orient), float(pos)))
    return rows


def axes_in_mm(raw_walls: Any, frame: CadFrameRead) -> FloorAxes:
    """Оси листа из walls.json в мм DXF по кадру вида.

    `pt = origin + (x_mm, -y_mm) / mm_per_pdf_point`: вертикальная ось - x, горизонтальная - y.
    Подпись, встретившаяся на листе дважды с расхождением больше допуска, отбрасывается.
    """
    block = raw_walls.get("axes") if isinstance(raw_walls, dict) else None
    if not isinstance(block, dict):
        return NO_AXES
    rows = _axis_rows(block.get("items"))
    if not rows:
        message = block.get("message")
        return FloorAxes(
            {}, {}, message if isinstance(message, str) and message else MESSAGE_AXES_EMPTY
        )
    origin, factor = frame.origin_pt, frame.mm_per_pdf_point
    if not frame.confirmed or origin is None or factor is None or factor <= 0:
        return FloorAxes({}, {}, frame.reason or MESSAGE_FRAME_MISSING)
    values: dict[tuple[str, str], list[float]] = {}
    for label, orient, pos in rows:
        mm = (pos - origin[0]) * factor if orient == "vertical" else (origin[1] - pos) * factor
        values.setdefault((orient, label), []).append(mm)
    vertical: dict[str, float] = {}
    horizontal: dict[str, float] = {}
    for (orient, label), mms in values.items():
        if max(mms) - min(mms) > AXIS_TOLERANCE_MM:
            continue
        (vertical if orient == "vertical" else horizontal)[label] = sum(mms) / len(mms)
    if vertical and horizontal:
        return FloorAxes(vertical, horizontal, None)
    if not vertical and not horizontal:
        return FloorAxes({}, {}, MESSAGE_AXES_EMPTY)
    found = "вертикальные" if vertical else "горизонтальные"
    return FloorAxes(
        vertical, horizontal, f"найдены только {found} оси: для совмещения нужны оба направления"
    )


CoreRing = tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class BuiltFloor:
    floor: CadBuilding3dFloorRead
    order: tuple[float, float, int, int]
    axes: FloorAxes
    # Монолитные стены и пилоны листа (кольца, мм DXF): по ним скопления ставятся на объект.
    cores: tuple[CoreRing, ...] = ()


def _agreed(diffs: dict[str, float]) -> tuple[list[str], int]:
    """Наибольшая группа марок с одним сдвигом (в допуске) и размер следующей за ней группы.

    Тесные промежуточные оси подписаны кружками на выносках, и центр такого кружка на разных
    листах сдвинут на метры (лист 342: 15.3, 15.4, 15.Б, 15.В); главные оси совпадают точно.
    Поэтому сдвиг даёт согласное большинство, а не все общие марки.
    """
    labels = sorted(diffs, key=_natural_key)

    def around(center: str, pool: Sequence[str]) -> list[str]:
        return [m for m in pool if abs(diffs[m] - diffs[center]) <= AXIS_TOLERANCE_MM]

    best: list[str] = []
    for label in labels:
        group = around(label, labels)
        if len(group) > len(best):
            best = group
    rest = [label for label in labels if label not in best]
    second = max((len(around(label, rest)) for label in rest), default=0)
    return best, second


def _plurality(diffs: dict[str, float]) -> tuple[float, list[str]] | None:
    """Сдвиг (медиана) по согласному большинству, иначе `None`.

    Группа согласных марок не меньше чем вдвое больше следующей (две марки против двух с другим
    общим сдвигом - неоднозначность, а не выноска), а при двух и более общих марках в ней не
    меньше двух.
    """
    agreed, second = _agreed(diffs)
    if len(agreed) < max(2 * second, 1) or len(agreed) == second:
        return None
    if len(diffs) >= 2 and len(agreed) < 2:
        return None
    return statistics.median(diffs[label] for label in agreed), agreed


def _match_orient(
    reference: dict[str, float], other: dict[str, float], name: str
) -> tuple[float, list[str]] | str:
    """Смещение по одному направлению (по согласному большинству) и согласные подписи, либо
    причина отказа."""
    common = sorted(reference.keys() & other.keys(), key=_natural_key)
    if not common:
        return f"нет общих {name} осей с эталонным этажом"
    diffs = {label: reference[label] - other[label] for label in common}
    found = _plurality(diffs)
    if found is None:
        return f"{name} оси расходятся с эталоном: {', '.join(common)}"
    return found


def _shifted(floor: CadBuilding3dFloorRead, dx: float, dy: float) -> CadBuilding3dFloorRead:
    box = floor.bbox
    # Кольца стен - целые мм, поэтому round(x + d) = x + round(d): сдвиг округляется один раз.
    ix, iy = _round_mm(dx), _round_mm(dy)
    walls = (
        floor.walls
        if floor.walls is None or (ix == 0 and iy == 0)
        else [
            # Сдвиг уже проверенной стены: целые мм, без повторной проверки модели.
            CadBuilding3dWallRead.model_construct(
                id=wall.id,
                kind=wall.kind,
                shell=[[x + ix, y + iy] for x, y in wall.shell],
                top_mm=wall.top_mm,
            )
            for wall in floor.walls
        ]
    )
    levels = (
        floor.levels
        if not floor.levels or (ix == 0 and iy == 0)
        else [
            zone.model_copy(
                update={
                    "shell": [[x + ix, y + iy] for x, y in zone.shell],
                    "holes": [[[x + ix, y + iy] for x, y in ring] for ring in zone.holes],
                }
            )
            for zone in floor.levels
        ]
    )
    ox, oy = floor.offset_mm
    return floor.model_copy(
        update={
            "walls": walls,
            "levels": levels,
            "outline": [[x + dx, y + dy] for x, y in floor.outline],
            "bbox": None if box is None else [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy],
            "offset_mm": (round(ox + dx, 3), round(oy + dy, 3)),
        }
    )


def _center(box: Sequence[float] | None) -> Point | None:
    return None if box is None else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _fallback(
    item: BuiltFloor, reference: BuiltFloor | None, message: str
) -> CadBuilding3dFloorRead:
    """Не совмещён: центр bbox на центр эталона (или без смещения) и причина."""
    dx = dy = 0.0
    target, own = (
        (None if reference is None else _center(reference.floor.bbox)),
        _center(item.floor.bbox),
    )
    if target is not None and own is not None:
        dx, dy = target[0] - own[0], target[1] - own[1]
    return _shifted(item.floor, dx, dy).model_copy(
        update={"alignment": "none", "alignment_axes": [], "alignment_message": message}
    )


def _overlap_share(first: Sequence[float], second: Sequence[float]) -> float:
    """Площадь пересечения двух bbox / меньшая из их площадей; нулевая площадь даёт 0."""
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    smallest = min(
        (first[2] - first[0]) * (first[3] - first[1]),
        (second[2] - second[0]) * (second[3] - second[1]),
    )
    if width <= 0 or height <= 0 or smallest <= 0:
        return 0.0
    return width * height / smallest


def _shared_axes(first: BuiltFloor, second: BuiltFloor) -> int:
    """Число общих подписей осей двух этажей (вертикальные и горизонтальные по отдельности)."""
    return len(first.axes.vertical.keys() & second.axes.vertical.keys()) + len(
        first.axes.horizontal.keys() & second.axes.horizontal.keys()
    )


def _pick_reference(items: Sequence[BuiltFloor], usable: Sequence[int]) -> int | None:
    """Эталон - этаж с наибольшим числом общих подписей осей с остальными этажами группы
    (подземный этаж с другой сеткой эталоном не становится); при равенстве - самый нижний."""
    if not usable:
        return None
    return min(
        usable,
        key=lambda i: (
            -sum(_shared_axes(items[i], items[j]) for j in usable if j != i),
            not items[i].floor.elevation_known,
            items[i].floor.base_z_mm,
            items[i].order,
        ),
    )


def _split_unnamed(
    items: Sequence[BuiltFloor],
    indexes: Sequence[int],
    result: list[CadBuilding3dFloorRead | None],
) -> list[int]:
    """Листы без корпуса и секции с осями другой сетки - отдельные здания «Корпус не указан · …».

    Под «Корпус не указан» попадают и паркинг со своей сеткой («01», «0А»), и сводные планы секций
    (техэтаж, кровля стилобата): общих осей у них нет, и одним эталоном их не совместить. Этажи,
    не совместившиеся с эталоном, по очереди образуют свои группы со своим эталоном; каждая
    ставится на объект отдельно. Заполняет `result` для отделённых этажей и возвращает индексы,
    оставшиеся в основной группе.
    """
    usable = [i for i in indexes if items[i].axes.usable]
    ref = _pick_reference(items, usable)
    if ref is None:
        return list(indexes)
    joined = {i for i in usable if i != ref and _align_to(items[i], items[ref]).alignment == "axes"}
    pending = [i for i in usable if i != ref and i not in joined]
    number = 1
    while pending:
        number += 1
        sub_ref = _pick_reference(items, pending)
        if sub_ref is None:
            break
        members = [sub_ref] + [
            i
            for i in pending
            if i != sub_ref and _align_to(items[i], items[sub_ref]).alignment == "axes"
        ]
        key = f"{GROUP_NONE_KEY}-{number}"
        label = f"{GROUP_NONE_LABEL} · {items[sub_ref].floor.label}"
        renamed = [
            BuiltFloor(
                items[i].floor.model_copy(update={"group_key": key, "group_label": label}),
                items[i].order,
                items[i].axes,
                items[i].cores,
            )
            for i in members
        ]
        reference = renamed[0]
        result[sub_ref] = reference.floor.model_copy(
            update={"alignment": "reference", "alignment_axes": [], "alignment_message": None}
        )
        for i, item in zip(members[1:], renamed[1:], strict=True):
            result[i] = _align_to(item, reference)
        pending = [i for i in pending if i not in members]
    return [i for i in indexes if result[i] is None]


def align_floors(items: Sequence[BuiltFloor]) -> list[CadBuilding3dFloorRead]:
    """Совмещение этажей каждой группы с эталоном; порядок результата - как у входа.

    Группа «Корпус не указан» делится на отдельные здания по сеткам осей (`_split_unnamed`).
    """
    result: list[CadBuilding3dFloorRead | None] = [None] * len(items)
    groups: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        groups.setdefault(item.floor.group_key, []).append(index)
    for key, members in groups.items():
        indexes = _split_unnamed(items, members, result) if key == GROUP_NONE_KEY else members
        usable = [i for i in indexes if items[i].axes.usable]
        ref_index = _pick_reference(items, usable)
        reference = None if ref_index is None else items[ref_index]
        for i in indexes:
            item = items[i]
            if reference is None:
                message = MESSAGE_NO_REFERENCE
                if item.axes.message:
                    message = f"{message}; лист: {item.axes.message}"
                result[i] = _fallback(item, None, message)
            elif i == ref_index:
                result[i] = item.floor.model_copy(
                    update={
                        "alignment": "reference",
                        "alignment_axes": [],
                        "alignment_message": None,
                    }
                )
            elif not item.axes.usable:
                result[i] = _fallback(item, reference, item.axes.message or MESSAGE_AXES_EMPTY)
            else:
                result[i] = _align_to(item, reference)
    return [floor for floor in result if floor is not None]


def _align_to(item: BuiltFloor, reference: BuiltFloor) -> CadBuilding3dFloorRead:
    ours, base = item.axes, reference.axes
    along_x = _match_orient(base.vertical, ours.vertical, "вертикальных")
    along_y = _match_orient(base.horizontal, ours.horizontal, "горизонтальных")
    if isinstance(along_x, str) or isinstance(along_y, str):
        problems = [m for m in (along_x, along_y) if isinstance(m, str)]
        return _fallback(item, reference, "; ".join(problems))
    shifted = _shifted(item.floor, along_x[0], along_y[0])
    labels = [*along_x[1], *along_y[1]]
    if shifted.bbox is not None and reference.floor.bbox is not None:
        share = _overlap_share(shifted.bbox, reference.floor.bbox)
        if share < MIN_ALIGN_OVERLAP:
            return _fallback(
                item,
                reference,
                f"после совмещения по осям {', '.join(labels)} этаж не перекрывает эталон "
                f"({share:.0%})",
            )
    return shifted.model_copy(
        update={
            "alignment": "axes",
            "alignment_axes": labels,
            "alignment_message": None,
        }
    )


# --------------------------------------------------------------------------- здания на объекте


@dataclass(frozen=True, slots=True)
class GroupPlacement:
    """Постановка здания на объект: `точка объекта = R(rotation_deg) · точка группы + offset_mm`.

    `cluster` - опора скопления зданий, связанных осями (`place_groups`); скопления ставятся на
    объект по ядрам (`place_by_cores`).
    """

    placement: CadBuilding3dPlacement
    offset_mm: Point
    axes: tuple[str, ...]
    anchor_key: str | None
    message: str | None
    cluster: str | None = None
    rotation_deg: float = 0.0
    share: float | None = None


@dataclass(frozen=True, slots=True)
class _GroupInfo:
    key: str
    label: str
    axes: FloorAxes
    # Этажи с известной отметкой: (низ плиты, верх объёма, отметка, bbox) в системе группы.
    levels: tuple[tuple[int, int, int, tuple[float, float, float, float]], ...]


@dataclass(frozen=True, slots=True)
class _SiteMatch:
    """Совпадение осей двух зданий: сдвиг из системы `other` в систему `base` и общие марки."""

    shift: Point
    labels: tuple[str, ...]
    prefixed: bool


def _is_prefixed(label: str) -> bool:
    """Марка с номером секции («3.1», «2-А»): одна на весь объект, совпадение надёжно."""
    return SITE_PREFIXED_LABEL.match(label) is not None


def _group_axes(
    items: Sequence[BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> FloorAxes:
    """Оси группы в системе её эталона: оси совмещённых этажей со сдвигом совмещения.

    Марка, разошедшаяся между этажами больше допуска, отбрасывается: она не годится для постановки.
    """
    values: dict[tuple[str, str], list[float]] = {}
    for item, floor in zip(items, aligned, strict=True):
        if floor.alignment == "none" or not item.axes.usable:
            continue
        dx, dy = floor.offset_mm
        for label, x in item.axes.vertical.items():
            values.setdefault(("vertical", label), []).append(x + dx)
        for label, y in item.axes.horizontal.items():
            values.setdefault(("horizontal", label), []).append(y + dy)
    vertical: dict[str, float] = {}
    horizontal: dict[str, float] = {}
    for (orient, label), mms in values.items():
        if max(mms) - min(mms) <= AXIS_TOLERANCE_MM:
            (vertical if orient == "vertical" else horizontal)[label] = statistics.median(mms)
    return FloorAxes(vertical, horizontal, None)


def _consensus(base: dict[str, float], other: dict[str, float]) -> tuple[float, list[str]] | None:
    """Сдвиг по одному направлению по согласованным общим маркам; согласия нет - `None`.

    Марка с номером секции («15.1») одна на весь объект: случайного совпадения у неё нет, и
    сдвиг даёт согласное большинство (кружки тесных осей на выносках сдвинуты, `_agreed`). Без
    номера секции («1», «А») марки повторяются у типовых секций: согласованных должно быть не
    меньше `SITE_MIN_AGREEMENT` от общих.
    """
    common = sorted(base.keys() & other.keys(), key=_natural_key)
    if not common:
        return None
    diffs = {label: base[label] - other[label] for label in common}
    found = _plurality(diffs)
    if found is None:
        return None
    agreed = found[1]
    if not any(_is_prefixed(label) for label in agreed) and (
        len(agreed) < SITE_MIN_AGREEMENT * len(common)
    ):
        return None
    return found


def _site_match(base: FloorAxes, other: FloorAxes) -> _SiteMatch | None:
    """Совпадение осей двух зданий: нужны оба направления и не меньше `SITE_MIN_AXES` марок."""
    along_x = _consensus(base.vertical, other.vertical)
    along_y = _consensus(base.horizontal, other.horizontal)
    if along_x is None or along_y is None:
        return None
    labels = (*along_x[1], *along_y[1])
    if len(labels) < SITE_MIN_AXES:
        return None
    return _SiteMatch(
        (along_x[0], along_y[0]), labels, any(_is_prefixed(label) for label in labels)
    )


def _group_infos(
    items: Sequence[BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> dict[str, _GroupInfo]:
    by_group: dict[str, list[int]] = {}
    for index, floor in enumerate(aligned):
        by_group.setdefault(floor.group_key, []).append(index)
    infos: dict[str, _GroupInfo] = {}
    for key, indexes in by_group.items():
        levels = tuple(
            (
                aligned[i].base_z_mm - aligned[i].slab_thickness_mm,
                aligned[i].base_z_mm + aligned[i].floor_height_mm,
                aligned[i].base_z_mm,
                (box[0], box[1], box[2], box[3]),
            )
            for i in indexes
            if aligned[i].elevation_known and (box := aligned[i].bbox) is not None
        )
        infos[key] = _GroupInfo(
            key=key,
            label=aligned[indexes[0]].group_label,
            axes=_group_axes([items[i] for i in indexes], [aligned[i] for i in indexes]),
            levels=levels,
        )
    return infos


def _clash(
    first: _GroupInfo, first_offset: Point, second: _GroupInfo, second_offset: Point
) -> bool:
    """Этажи двух зданий на одной отметке занимают одно место в плане: постановка ложная."""
    for _low, _high, z1, b1 in first.levels:
        box1 = (
            b1[0] + first_offset[0],
            b1[1] + first_offset[1],
            b1[2] + first_offset[0],
            b1[3] + first_offset[1],
        )
        for _low2, _high2, z2, b2 in second.levels:
            if abs(z1 - z2) > SITE_SAME_LEVEL_MM:
                continue
            box2 = (
                b2[0] + second_offset[0],
                b2[1] + second_offset[1],
                b2[2] + second_offset[0],
                b2[3] + second_offset[1],
            )
            if _overlap_share(box1, box2) > SITE_MAX_OVERLAP:
                return True
    return False


def place_groups(
    items: Sequence[BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> dict[str, GroupPlacement]:
    """Постановка зданий на объект по общим маркам осей.

    Общей системы координат у зданий нет: у каждого - система его эталонного этажа. Здания с общими
    марками осей (план паркинга несёт оси всех корпусов) ставятся друг относительно друга. Опора -
    здание с наибольшим числом согласованных общих марок с остальными (обычно паркинг); дальше по
    одному присоединяется здание с самым надёжным совпадением с уже поставленными: сначала марки с
    номером секции, затем больше марок. Совпадение только по марке без номера секции («1», «А»)
    повторяется у типовых секций, поэтому оно не принимается, если этажи на одной отметке ложатся
    друг на друга в плане. Здание без совпадения остаётся не поставленным (`none`) с причиной.
    """
    infos = _group_infos(items, aligned)
    keys = sorted(infos, key=lambda k: (_natural_key(infos[k].label), k))
    if len(keys) == 1:
        return {keys[0]: GroupPlacement("reference", (0.0, 0.0), (), None, None, keys[0])}
    # Здание без этажей с отметкой (план 1 этажа, техэтаж без отметки) - тоже связка: марки с
    # номером секции ставят его без проверки наложения.
    with_axes = [k for k in keys if infos[k].axes.usable]
    matches: dict[tuple[str, str], _SiteMatch] = {}
    for base in with_axes:
        for other in with_axes:
            if base != other and (match := _site_match(infos[base].axes, infos[other].axes)):
                matches[(base, other)] = match
    result: dict[str, GroupPlacement] = {}
    rejected: dict[str, str] = {}
    # Скопления: опора - здание с наибольшим числом общих марок среди ещё не поставленных; к ней по
    # осям присоединяются остальные. Не присоединившиеся образуют следующее скопление.
    remaining = list(with_axes)
    while remaining:
        root = min(
            remaining,
            key=lambda k: (
                -sum(len(m.labels) for (b, o), m in matches.items() if b == k and o in remaining),
                -(len(infos[k].axes.vertical) + len(infos[k].axes.horizontal)),
                not infos[k].levels,
                min((level[0] for level in infos[k].levels), default=0),
                keys.index(k),
            ),
        )
        offsets: dict[str, Point] = {root: (0.0, 0.0)}
        # Опора следующего скопления: причина, по которой её не присоединили к прежним, сохраняется.
        result[root] = GroupPlacement("reference", (0.0, 0.0), (), None, rejected.get(root), root)
        while True:
            candidates = sorted(
                (
                    (base, other, match)
                    for (base, other), match in matches.items()
                    if base in offsets and other in remaining and other not in offsets
                ),
                key=lambda row: (
                    not row[2].prefixed,
                    -len(row[2].labels),
                    keys.index(row[1]),
                    keys.index(row[0]),
                ),
            )
            placed = False
            for base, other, match in candidates:
                offset = (
                    offsets[base][0] + match.shift[0],
                    offsets[base][1] + match.shift[1],
                )
                clash = None
                if not match.prefixed and not (infos[other].levels and infos[base].levels):
                    # Без отметок наложение не проверить, а марки без номера секции повторяются.
                    rejected[other] = (
                        f"совпадение по осям {', '.join(match.labels)} без номера секции, а этажей "
                        "с отметкой для проверки наложения нет"
                    )
                    continue
                if not match.prefixed:
                    clash = next(
                        (k for k in offsets if _clash(infos[k], offsets[k], infos[other], offset)),
                        None,
                    )
                if clash is not None:
                    rejected[other] = (
                        f"по осям {', '.join(match.labels)} здание ложится на "
                        f"«{infos[clash].label}» на той же отметке: совпадение марок случайное"
                    )
                    continue
                offsets[other] = offset
                result[other] = GroupPlacement(
                    "axes",
                    (round(offset[0], 3), round(offset[1], 3)),
                    tuple(sorted(match.labels, key=_natural_key)),
                    base,
                    None,
                    root,
                )
                rejected.pop(other, None)
                placed = True
                break
            if not placed:
                break
        remaining = [k for k in remaining if k not in offsets]
    for key in keys:
        if key in result:
            continue
        # Без осей в обоих направлениях здание - отдельное скопление: его ставят ядра.
        message = rejected.get(key) or (
            "у здания нет совмещённых по осям этажей с осями в обоих направлениях"
        )
        result[key] = GroupPlacement("reference", (0.0, 0.0), (), None, message, key)
    return result


# Кеш совмещений по ядрам: ключ - содержимое колец основы и скопления (их хеши); индекс основы
# (клетки и элементы) - отдельно, он общий для всех скоплений одного прохода.
_CORE_CACHE: OrderedDict[tuple[int, int], cad_site_cores.CoreMatch | None] = OrderedDict()
_BASE_CACHE: OrderedDict[int, cad_site_cores.BaseIndex] = OrderedDict()
CORE_CACHE_MAX: Final = 128
BASE_CACHE_MAX: Final = 8


def _register_cached(
    base: Sequence[CoreRing], other: Sequence[CoreRing]
) -> cad_site_cores.CoreMatch | None:
    base_key = hash(tuple(base))
    key = (base_key, hash(tuple(other)))
    if key in _CORE_CACHE:
        _CORE_CACHE.move_to_end(key)
        return _CORE_CACHE[key]
    index = _BASE_CACHE.get(base_key)
    if index is None:
        index = cad_site_cores.index_base(base)
        _BASE_CACHE[base_key] = index
        while len(_BASE_CACHE) > BASE_CACHE_MAX:
            _BASE_CACHE.popitem(last=False)
    else:
        _BASE_CACHE.move_to_end(base_key)
    found = cad_site_cores.register(index, other)
    _CORE_CACHE[key] = found
    while len(_CORE_CACHE) > CORE_CACHE_MAX:
        _CORE_CACHE.popitem(last=False)
    return found


def _moved_ring(ring: CoreRing, rotation: float, dx: float, dy: float) -> CoreRing:
    if rotation == 0.0:
        ix, iy = _round_mm(dx), _round_mm(dy)
        return tuple((x + ix, y + iy) for x, y in ring)
    moved: list[tuple[int, int]] = []
    for x, y in ring:
        px, py = cad_site_cores.transform_point(x, y, rotation, dx, dy)
        moved.append((_round_mm(px), _round_mm(py)))
    return tuple(moved)


def _floor_core_sets(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    placements: dict[str, GroupPlacement],
    keys: Sequence[str],
) -> list[list[CoreRing]]:
    """Ядра нижних этажей скопления по отдельности, в системе скопления (снизу вверх).

    Ядра проходят сквозь все этажи, но выше земли к ним добавляются монолитные стены квартир,
    которых в подземке нет; а сводный техуровень несёт монолит другого уровня. Поэтому этажи
    пробуются по одному (не больше `CORE_TRY_FLOORS`), и берётся лучший однозначный.
    """
    group_keys = set(keys)
    rows = sorted(
        (floor.alignment == "none", not floor.elevation_known, floor.base_z_mm, i)
        for i, floor in enumerate(aligned)
        if floor.group_key in group_keys and len(items[i].cores) >= CORE_MIN_RINGS
    )
    out: list[list[CoreRing]] = []
    for *_rank, index in rows[:CORE_TRY_FLOORS]:
        fx, fy = aligned[index].offset_mm
        ox, oy = placements[aligned[index].group_key].offset_mm
        out.append([_moved_ring(ring, 0.0, fx + ox, fy + oy) for ring in items[index].cores])
    return out


def _floor_area_m2(floor: CadBuilding3dFloorRead) -> int:
    box = floor.bbox
    return 0 if box is None else round((box[2] - box[0]) * (box[3] - box[1]) / 1e6)


def place_by_cores(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    placements: dict[str, GroupPlacement],
) -> dict[str, GroupPlacement]:
    """Постановка скоплений зданий на объект по совпадению ядер (`cad_site_cores`).

    Основа - самый большой этаж объекта (план подземной автостоянки несёт ядра всех корпусов) и
    его скопление. Остальные скопления, от большего к меньшему, совмещаются с монолитом уже
    поставленного (каждый из нижних этажей по отдельности, `_floor_core_sets`); поставленное
    добавляет ядра своего этажа к основе, и проход повторяется, пока что-то ставится. Не
    совместившееся скопление остаётся не поставленным (`none`) с причиной. Если по ядрам к основе
    не встало ничего, а скопление по осям больше её, опорой остаётся оно (как до постановки по
    ядрам).
    """
    clusters: dict[str, list[str]] = {}
    for key, placement in placements.items():
        clusters.setdefault(placement.cluster or key, []).append(key)
    if len(clusters) == 1:
        return placements
    labels = {floor.group_key: floor.group_label for floor in aligned}
    biggest = max(
        (i for i, floor in enumerate(aligned) if items[i].cores),
        key=lambda i: (_floor_area_m2(aligned[i]), -i),
        default=None,
    )
    if biggest is None:
        base_root = max(sorted(clusters), key=lambda r: len(clusters[r]))
        site: list[CoreRing] = []
    else:
        floor = aligned[biggest]
        base_root = placements[floor.group_key].cluster or floor.group_key
        fx, fy = floor.offset_mm
        ox, oy = placements[floor.group_key].offset_mm
        site = [_moved_ring(r, 0.0, fx + ox, fy + oy) for r in items[biggest].cores]
    placed: dict[str, cad_site_cores.CoreMatch] = {}
    tried: dict[str, cad_site_cores.CoreMatch | None] = {}
    sets = {
        root: _floor_core_sets(items, aligned, placements, keys) for root, keys in clusters.items()
    }
    pending = sorted((r for r in clusters if r != base_root), key=lambda r: (-len(clusters[r]), r))
    progress = True
    while progress and pending:
        progress = False
        for root in list(pending):
            best: tuple[cad_site_cores.CoreMatch, list[CoreRing]] | None = None
            for rings in sets[root] if site else []:
                found = _register_cached(site, rings)
                if found is None:
                    continue
                rank = (found.accepted, found.share)
                if best is None or rank > (best[0].accepted, best[0].share):
                    best = (found, rings)
            tried[root] = None if best is None else best[0]
            if best is None or not best[0].accepted:
                continue
            match, rings = best
            placed[root] = match
            site.extend(_moved_ring(r, match.rotation_deg, match.tx, match.ty) for r in rings)
            pending.remove(root)
            progress = True
    site_size = len(clusters[base_root]) + sum(len(clusters[r]) for r in placed)
    largest = max(sorted(clusters), key=lambda r: len(clusters[r]))
    if not placed and len(clusters[largest]) > site_size:
        # По ядрам не встало ничего: опорой остаётся большее скопление по осям, основа - в стороне.
        fallback: str | None = base_root
        base_root = largest
    else:
        fallback = None
    base_label = labels.get(base_root, base_root)
    result: dict[str, GroupPlacement] = {}
    for root, keys in clusters.items():
        site_match = placed.get(root)
        for key in keys:
            p = placements[key]
            if root == base_root:
                result[key] = p
            elif root == fallback:
                result[key] = GroupPlacement(
                    "none",
                    (0.0, 0.0),
                    (),
                    None,
                    f"ни одно скопление зданий не совпало с этим этажом по ядрам; опора объекта - "
                    f"«{base_label}» (по осям)",
                    root,
                )
            elif site_match is not None:
                ox, oy = cad_site_cores.transform_point(
                    p.offset_mm[0],
                    p.offset_mm[1],
                    site_match.rotation_deg,
                    site_match.tx,
                    site_match.ty,
                )
                result[key] = GroupPlacement(
                    "cores" if key == root else p.placement,
                    (round(ox, 3), round(oy, 3)),
                    p.axes,
                    base_root if key == root else p.anchor_key,
                    None,
                    root,
                    site_match.rotation_deg,
                    round(site_match.share, 3) if key == root else None,
                )
            else:
                result[key] = GroupPlacement(
                    "none",
                    (0.0, 0.0),
                    (),
                    None,
                    _cores_message(tried.get(root), root, key, labels, base_label, p.message),
                    root,
                    0.0,
                    None if (t := tried.get(root)) is None else round(t.share, 3),
                )
    return result


def _cores_message(
    found: cad_site_cores.CoreMatch | None,
    root: str,
    key: str,
    labels: dict[str, str],
    base_label: str,
    axes_message: str | None,
) -> str:
    if key != root:
        return (
            f"связано осями с «{labels.get(root, root)}», но это скопление не совмещено с "
            f"«{base_label}» по ядрам"
        )
    prefix = f"{axes_message}; " if axes_message else ""
    if found is None:
        return f"{prefix}мало монолитных стен и пилонов для совмещения по ядрам с «{base_label}»"
    return (
        f"{prefix}по ядрам не совмещено с «{base_label}»: совпадение {found.share:.0%}, у другого "
        f"варианта {found.second_share:.0%} (нужно не меньше {cad_site_cores.MIN_SHARE:.0%} и "
        f"вдвое больше; у листа с неверным масштабом ядра не совпадут)"
    )


def apply_placements(
    floors: Sequence[CadBuilding3dFloorRead], placements: dict[str, GroupPlacement]
) -> list[CadBuilding3dFloorRead]:
    """Сдвиг (и поворот) этажей поставленных зданий в систему объекта; не поставленные - в своей."""
    result: list[CadBuilding3dFloorRead] = []
    for floor in floors:
        placement = placements.get(floor.group_key)
        if placement is None or placement.placement == "none":
            result.append(floor)
        elif placement.rotation_deg != 0.0:
            result.append(_rotated(floor, placement.rotation_deg, *placement.offset_mm))
        elif placement.offset_mm == (0.0, 0.0):
            result.append(floor)
        else:
            result.append(_shifted(floor, *placement.offset_mm))
    return result


def _rotated(
    floor: CadBuilding3dFloorRead, rotation: float, dx: float, dy: float
) -> CadBuilding3dFloorRead:
    """Поворот на `rotation` градусов вокруг начала системы группы и сдвиг: постановка по ядрам."""

    def point(x: float, y: float) -> Point:
        return cad_site_cores.transform_point(x, y, rotation, dx, dy)

    def ints(ring: Sequence[Sequence[int]]) -> list[list[int]]:
        out: list[list[int]] = []
        for x, y in ring:
            px, py = point(x, y)
            out.append([_round_mm(px), _round_mm(py)])
        return out

    outline = [list(point(x, y)) for x, y in floor.outline]
    walls = (
        None
        if floor.walls is None
        else [
            CadBuilding3dWallRead.model_construct(
                id=wall.id, kind=wall.kind, shell=ints(wall.shell), top_mm=wall.top_mm
            )
            for wall in floor.walls
        ]
    )
    levels = [
        zone.model_copy(update={"shell": ints(zone.shell), "holes": [ints(h) for h in zone.holes]})
        for zone in floor.levels
    ]
    box = floor.bbox
    bbox = None
    if box is not None:
        corners = [point(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    ax, ay = floor.offset_mm
    ox, oy = point(ax, ay)
    return floor.model_copy(
        update={
            "outline": outline,
            "walls": walls,
            "levels": levels,
            "bbox": bbox,
            "offset_mm": (round(ox, 3), round(oy, 3)),
            "rotation_deg": round(floor.rotation_deg + rotation, 3),
        }
    )


def build_groups(
    floors: Sequence[CadBuilding3dFloorRead],
    placements: dict[str, GroupPlacement] | None = None,
) -> list[CadBuilding3dGroupRead]:
    """Здания для переключателя: по подписи в естественном порядке."""
    counts: dict[str, tuple[str, int, int]] = {}
    for floor in floors:
        label, total, aligned = counts.get(floor.group_key, (floor.group_label, 0, 0))
        counts[floor.group_key] = (label, total + 1, aligned + (floor.alignment != "none"))
    rows = sorted(counts.items(), key=lambda row: (_natural_key(row[1][0]), row[0]))
    groups: list[CadBuilding3dGroupRead] = []
    for key, (label, total, aligned) in rows:
        placement = (placements or {}).get(key)
        groups.append(
            CadBuilding3dGroupRead(
                key=key,
                label=label,
                floor_count=total,
                aligned_count=aligned,
                placement="none" if placement is None else placement.placement,
                site_offset_mm=(0.0, 0.0) if placement is None else placement.offset_mm,
                site_rotation_deg=0.0 if placement is None else placement.rotation_deg,
                placement_share=None if placement is None else placement.share,
                placement_axes=[] if placement is None else list(placement.axes),
                placement_anchor=None if placement is None else placement.anchor_key,
                placement_message=None if placement is None else placement.message,
            )
        )
    return groups


# --------------------------------------------------------------------------- база


def _revision_of(job: Job) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(job.payload.get("revision_id")))
    except ValueError:
        return None


def _view_numbers(job: Job, page_index: int) -> list[int]:
    """Виды страницы текущего итога, у которых есть DXF."""
    views: list[int] = []
    for page in cad_service.current_result(job).get("pages", []):
        if not isinstance(page, dict) or page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            view = row.get("view") if isinstance(row, dict) else None
            if type(view) is int and cad_walls.view_has_dxf(job, page_index, view) is not None:
                views.append(view)
    return views


def _pages_of(job: Job) -> list[int]:
    pages = cad_service.current_result(job).get("pages", [])
    return [p["index"] for p in pages if isinstance(p, dict) and type(p.get("index")) is int]


def _walls_key(job: Job | None, revision_id: uuid.UUID, page_index: int, view: int) -> str | None:
    """Ключ walls.json в итоге успешного `cad_walls`; как в `cad_constructions._load_walls`."""
    if job is None:
        return None
    attempt = cad_service.result_of(job).get("attempt")
    name = f"{cad_service.view_folder(page_index, view)}/{cad_walls.WALLS_JSON}"
    artifact = cad_service.find_artifact(job, name)
    if type(attempt) is not int or artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    return key if artifact.get("key") == key else None


def _parent_key(job: Job, revision_id: uuid.UUID, name: str) -> str | None:
    """Ключ артефакта родительского задания CAD в итоге текущей попытки; как в `cad_floor3d`."""
    attempt = cad_service.current_result(job).get("attempt")
    artifact = cad_service.find_artifact(job, name, attempt) if type(attempt) is int else None
    if type(attempt) is not int or artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    return key if artifact.get("key") == key else None


async def collect_sheets(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[list[SheetRef], list[CadBuilding3dWarningRead], ProjectSlab | None]:
    """Листы проекта с готовыми конструкциями. Всё из базы, последовательно."""
    converts = list(
        await session.scalars(
            select(Job)
            .where(
                Job.workspace_id == workspace_id,
                Job.project_id == project_id,
                Job.job_type == JobType.CAD_PDF_CONVERT,
                Job.status == JobStatus.SUCCEEDED,
            )
            .order_by(Job.created_at.desc(), Job.id)
        )
    )
    revision_ids = {rid for job in converts if (rid := _revision_of(job)) is not None}
    if not revision_ids:
        return [], [], None
    rows = await session.execute(
        select(DocumentRevision, Document)
        .join(Document, DocumentRevision.document_id == Document.id)
        .where(DocumentRevision.id.in_(revision_ids), Document.project_id == project_id)
    )
    revisions = {revision.id: (revision, document) for revision, document in rows.all()}
    walls_by_view: dict[tuple[str, int, int], Job] = {}
    for walls in await session.scalars(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_WALLS,
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.created_at.desc(), Job.id)
    ):
        page, view = walls.payload.get("page_index"), walls.payload.get("view")
        if type(page) is int and type(view) is int:
            walls_by_view.setdefault((str(walls.payload.get("parent_job_id")), page, view), walls)
    project_slab = await cad_construction_store.load_project_slab(session, project_id=project_id)
    # Высоты всех листов - одним запросом, а не запросом на каждый вид.
    levels = await cad_construction_store.load_levels_many(session, revision_ids=list(revisions))

    # Сначала новые ревизии, в ревизии — новые задания: страница документа берётся один раз,
    # у более ранней ревизии и более раннего задания она остаётся устаревшей и не показывается.
    candidates: list[tuple[Job, uuid.UUID]] = []
    for job in converts:
        rid = _revision_of(job)
        if rid is not None and rid in revisions:
            candidates.append((job, rid))
    ordered = sorted(
        candidates,
        key=lambda item: (revisions[item[1]][0].created_at, item[0].created_at),
        reverse=True,
    )
    taken: set[tuple[uuid.UUID, int]] = set()
    sheets: list[SheetRef] = []
    for job, revision_id in ordered:
        revision, document = revisions[revision_id]
        for page_index in _pages_of(job):
            if (document.id, page_index) in taken:
                continue
            views = _view_numbers(job, page_index)
            if not views:
                continue
            taken.add((document.id, page_index))
            for view in views:
                label = f"{document.display_name} · лист {page_index + 1}"
                if len(views) > 1:
                    label += f" · вид {view}"
                overrides = levels.get(
                    (revision_id, page_index, view), cad_construction_store.EMPTY_LEVELS
                )
                folder = cad_service.view_folder(page_index, view)
                sheets.append(
                    SheetRef(
                        job_id=job.id,
                        revision_id=revision_id,
                        document_id=document.id,
                        page_index=page_index,
                        view=view,
                        label=label,
                        order=(
                            document.created_at.timestamp(),
                            revision.created_at.timestamp(),
                            page_index,
                            view,
                        ),
                        overrides=overrides,
                        walls_key=_walls_key(
                            walls_by_view.get((str(job.id), page_index, view)),
                            revision_id,
                            page_index,
                            view,
                        ),
                        scale_key=_parent_key(job, revision_id, f"{folder}/scale.json"),
                        checks_key=_parent_key(job, revision_id, f"{folder}/cad_checks.json"),
                    )
                )
    return sheets, [], project_slab


# --------------------------------------------------------------------------- хранилище


async def _read_walls(
    storage: ObjectStorage, sheet: SheetRef, gate: asyncio.Semaphore
) -> tuple[Any, CadBuilding3dWarningRead | None]:
    if sheet.walls_key is None:
        return None, CadBuilding3dWarningRead(
            code="walls_not_ready",
            message=f"{sheet.label}: конструкции вида не посчитаны, лист пропущен.",
        )
    async with gate:
        try:
            return await cad_views.read_json(storage, sheet.walls_key), None
        except (
            ObjectNotFoundError,
            StorageUnavailableError,
            cad_views.ArtifactTooLargeError,
            ValueError,
        ):
            return None, CadBuilding3dWarningRead(
                code="walls_unreadable",
                message=f"{sheet.label}: walls.json не читается, лист пропущен.",
            )


async def _read_frame(
    storage: ObjectStorage, sheet: SheetRef, gate: asyncio.Semaphore
) -> tuple[CadFrameRead, bool]:
    """Кадр вида листа; не читается или не установлен - неподтверждённый кадр с причиной.

    Второе значение - можно ли запомнить итог: сбой хранилища преходящ, его в кеш не кладём.
    """

    def unconfirmed(reason: str) -> CadFrameRead:
        return CadFrameRead(
            confirmed=False, reason=reason, units=None, origin_pt=None, mm_per_pdf_point=None
        )

    if sheet.scale_key is None or sheet.checks_key is None:
        return unconfirmed("DXF в этой попытке нет: сравнивать с PDF нечего."), True
    async with gate:
        try:
            scale = cad_views.scale_from(await cad_views.read_json(storage, sheet.scale_key))
            checks = await cad_views.read_json(storage, sheet.checks_key)
        except StorageUnavailableError:
            return unconfirmed("масштаб или проверки вида не читаются"), False
        except (ObjectNotFoundError, cad_views.ArtifactTooLargeError, ValueError):
            return unconfirmed("масштаб или проверки вида не читаются"), True
    return cad_views.frame_from(scale, checks), True


# --------------------------------------------------------------------------- кеш этажей


@dataclass(frozen=True, slots=True)
class _SheetFloor:
    """Этаж листа до совмещения: этаж, его предупреждения и оси; `floor = None` - лист пропущен.

    `cost` - вес в кеше: число точек в кольцах стен и контуре (память растёт с точками).
    """

    floor: CadBuilding3dFloorRead | None
    warnings: tuple[CadBuilding3dWarningRead, ...]
    axes: FloorAxes
    cost: int = 1
    cores: tuple[CoreRing, ...] = ()


# Ключ - всё, от чего зависит этаж листа: адрес и подпись листа, ключи артефактов (неизменны в
# пределах попытки задания), высоты человека, плита проекта и `include_walls`. Новая попытка
# конструкций, правка высот или переименование документа дают новый ключ - устаревшее не отдаётся.
_SheetKey = tuple[object, ...]
# Предел кеша процесса: число этажей и суммарное число точек. Точка стены в памяти ~0,15 КБ:
# 300 тыс. точек - ~45 МБ на процесс (в бою 4 процесса uvicorn в общем лимите памяти).
FLOOR_CACHE_MAX_ENTRIES: Final = 512
FLOOR_CACHE_MAX_POINTS: Final = 300_000


class _FloorCache:
    """LRU этажей листов в памяти процесса с пределом по числу этажей и суммарному весу.

    Этажи, взятые или положенные текущим запросом (поколение не старше `begin`), им же не
    вытесняются: объект больше кеша не гоняет его по кругу с нулевым попаданием - часть этажей
    остаётся, остальные просто не кладутся.
    """

    def __init__(self) -> None:
        self._items: OrderedDict[_SheetKey, tuple[_SheetFloor, int]] = OrderedDict()
        self._cost = 0
        self._generation = 0

    def begin(self) -> int:
        """Поколение нового запроса."""
        self._generation += 1
        return self._generation

    def get(self, key: _SheetKey, generation: int) -> _SheetFloor | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items[key] = (entry[0], max(entry[1], generation))
        self._items.move_to_end(key)
        return entry[0]

    def put(self, key: _SheetKey, item: _SheetFloor, generation: int) -> None:
        if item.cost > FLOOR_CACHE_MAX_POINTS:
            return
        previous = self._items.pop(key, None)
        if previous is not None:
            self._cost -= previous[0].cost
        while self._items and (
            len(self._items) + 1 > FLOOR_CACHE_MAX_ENTRIES
            or self._cost + item.cost > FLOOR_CACHE_MAX_POINTS
        ):
            oldest_key = next(iter(self._items))
            oldest, used = self._items[oldest_key]
            if used >= generation:
                return
            del self._items[oldest_key]
            self._cost -= oldest.cost
        if self._cost + item.cost > FLOOR_CACHE_MAX_POINTS:
            return
        self._items[key] = (item, generation)
        self._cost += item.cost

    def clear(self) -> None:
        self._items.clear()
        self._cost = 0


floor_cache: Final = _FloorCache()


def _sheet_key(sheet: SheetRef, project_slab: ProjectSlab | None, include_walls: bool) -> _SheetKey:
    return (
        sheet.job_id,
        sheet.revision_id,
        sheet.document_id,
        sheet.page_index,
        sheet.view,
        sheet.label,
        sheet.walls_key,
        sheet.scale_key,
        sheet.checks_key,
        sheet.overrides.model_dump_json(),
        project_slab,
        include_walls,
    )


def _sheet_floor(
    sheet: SheetRef,
    raw: Any,
    frame: CadFrameRead | None,
    project_slab: ProjectSlab | None,
    include_walls: bool,
) -> _SheetFloor:
    """Этаж из прочитанного walls.json: проверка контракта и сборка. Чисто вычисление, без I/O."""
    try:
        document = WallsDocument.model_validate(raw)
        extras = WallsFloorExtras.model_validate(raw)
        floor, floor_warnings = build_floor(
            sheet, document, extras, project_slab, include_walls=include_walls
        )
    except (ValidationError, ValueError):
        warning = CadBuilding3dWarningRead(
            code="walls_invalid",
            message=f"{sheet.label}: walls.json вне контракта или без геометрии, лист пропущен.",
        )
        return _SheetFloor(None, (warning,), NO_AXES)
    axes = NO_AXES if frame is None else axes_in_mm(raw, frame)
    cores = core_rings(document)
    cost = (
        1
        + sum(len(ring) for ring in cores)
        + len(floor.outline)
        + sum(len(wall.shell) for wall in floor.walls or ())
        + sum(len(zone.shell) + sum(len(h) for h in zone.holes) for zone in floor.levels)
    )
    return _SheetFloor(floor, tuple(floor_warnings), axes, cost, cores)


def core_rings(document: WallsDocument) -> tuple[CoreRing, ...]:
    """Монолитные стены и пилоны листа (кольца в целых мм DXF) для постановки по ядрам."""
    out: list[CoreRing] = []
    for construction in document.constructions:
        if construction.kind not in CORE_KINDS:
            continue
        ring = wall_ring(construction.polygon.shell)
        if ring is not None:
            out.append(tuple((x, y) for x, y in ring))
    return tuple(out)


async def _load_sheet_floor(
    storage: ObjectStorage,
    sheet: SheetRef,
    project_slab: ProjectSlab | None,
    include_walls: bool,
    gate: asyncio.Semaphore,
    generation: int,
) -> _SheetFloor:
    """Этаж листа: из кеша, иначе чтение walls.json (и кадра, если есть оси) и сборка в потоке."""
    key = _sheet_key(sheet, project_slab, include_walls)
    cached = floor_cache.get(key, generation)
    if cached is not None:
        return cached
    raw, problem = await _read_walls(storage, sheet, gate)
    if problem is not None:
        # Не посчитан или не читается: состояние может смениться без смены ключа - не кешируем.
        return _SheetFloor(None, (problem,), NO_AXES)
    frame: CadFrameRead | None = None
    cacheable = True
    # Кадр нужен только листам, у которых в walls.json есть блок осей.
    if isinstance(raw, dict) and isinstance(raw.get("axes"), dict):
        frame, cacheable = await _read_frame(storage, sheet, gate)
    # Проверка контракта и сборка тысяч стен - в потоке: на event loop они останавливали бы
    # все запросы процесса.
    item = await asyncio.to_thread(_sheet_floor, sheet, raw, frame, project_slab, include_walls)
    if cacheable:
        floor_cache.put(key, item, generation)
    return item


async def build_building3d(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    include_walls: bool = False,
) -> CadBuilding3dRead:
    sheets, warnings, project_slab = await collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    gate = asyncio.Semaphore(READ_CONCURRENCY)
    generation = floor_cache.begin()
    loaded = await asyncio.gather(
        *(
            _load_sheet_floor(storage, sheet, project_slab, include_walls, gate, generation)
            for sheet in sheets
        )
    )
    built: list[BuiltFloor] = []
    for sheet, item in zip(sheets, loaded, strict=True):
        warnings.extend(item.warnings)
        if item.floor is not None:
            built.append(BuiltFloor(item.floor, sheet.order, item.axes, item.cores))
    aligned = align_floors(built)
    placements = place_groups(built, aligned)
    # Совмещение по ядрам - чистый расчёт на тысячах точек: в потоке, не на event loop.
    placements = await asyncio.to_thread(place_by_cores, built, aligned, placements)
    placed = apply_placements(aligned, placements)
    floors = sort_floors([(f, item.order) for f, item in zip(placed, built, strict=True)])
    groups = build_groups(floors, placements)
    lost = [g.label for g in groups if g.placement == "none"]
    if len(groups) > 1 and lost:
        warnings.append(
            CadBuilding3dWarningRead(
                code="groups_not_placed",
                message="Не поставлены на объект по осям и ядрам: "
                f"{', '.join(lost)}. В виде «Весь объект» они стоят рядом.",
            )
        )
    return CadBuilding3dRead(units="mm", floors=floors, groups=groups, warnings=warnings)
