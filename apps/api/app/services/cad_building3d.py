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

В стопку идут только планы этажей и уровней (`plan_problem`): разрез или таблица с посчитанными
конструкциями - служебный лист. Сборку ответа (дубли планов, сведение групп одного корпуса, высота
по стопке, этажи типовых листов) ведёт `cad_building3d_assembly`.

Порядок работы: сначала всё нужное из базы — последовательно (сессия не конкурентна), затем
`walls.json` листов читаются из хранилища параллельно с ограничением, проверка контракта и сборка
этажа идут в потоке. Этаж листа до совмещения запоминается в памяти процесса (`floor_cache`) по
ключам артефактов и высотам: повторное открытие не читает и не разбирает walls.json заново.
Ошибка одного листа не валит ответ: лист пропускается с предупреждением. В итоги обмера, calc и
MEP вид не входит.
"""

from __future__ import annotations

import asyncio
import dataclasses
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
    CadBuilding3dWallRead,
    CadBuilding3dWarningRead,
)
from app.contracts.cad_constructions import (
    CadSheetFloorTitle,
    CadSheetLevelsRead,
    WallsDocument,
    WallsOpening,
)
from app.contracts.cad_floor3d import WallsFloorExtras, WallsLevels, WallsOpeningExtras
from app.domain import JobStatus, JobType
from app.models import Document, DocumentRevision, Job, Sheet, SheetPassport
from app.services import cad as cad_service
from app.services import cad_construction_store, cad_site_cores, cad_views, cad_walls
from app.services import cad_site_pins_math as pins_math
from app.services import documents as documents_service
from app.services.cad_constructions import EffectiveLevels, ProjectSlab, effective_levels
from app.services.cad_facade_windows import SheetLevel
from app.services.cad_floor_title import floors_text, format_floor_title
from app.services.cad_site_pins_math import SitePin
from app.services.consistency.dictionaries import SheetKind
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

MAX_OUTLINE_POINTS: Final = 200
# Контуры конструкций (`walls=true`): предел числа на этаж и точек в кольце.
MAX_WALLS_PER_FLOOR: Final = 4000
MAX_WALL_POINTS: Final = 64
# Участки уровней плиты этажа (cad_walls v1.15): число и точки кольца участка.
MAX_LEVEL_ZONES: Final = 300
MAX_LEVEL_POINTS: Final = 400
# Участок уровня меньше этого (мм²) - на основном уровне этажа; виды планов с участками.
LEVEL_MIN_AREA_MM2: Final = 25_000_000
LEVEL_KINDS: Final = frozenset({"roof", "roof_exit"})
READ_CONCURRENCY: Final = 6
# Для отрисовки, когда высота этажа или толщина плиты не определены (помечаются `*_known = false`).
DEFAULT_FLOOR_HEIGHT_MM: Final = 3000
DEFAULT_SLAB_THICKNESS_MM: Final = 200
# Допуск расхождения смещений по общим осям: больше - оси разных этажей «не сходятся».
AXIS_TOLERANCE_MM: Final = 150.0
# Минимальная доля перекрытия bbox совмещённого этажа с эталоном (от меньшего bbox).
MIN_ALIGN_OVERLAP: Final = 0.3
# Наклон шкалы лист - эталон (промилле): больше первого - предупреждение, больше второго - этаж
# не совмещается с причиной «масштаб листа». Оценка - по парам осей не ближе `SCALE_MIN_SPAN_MM`
# (на коротком отрезке сдвиг кружка на выноске даёт большой наклон), пар не меньше трёх.
SCALE_WARN_PERMILLE: Final = 0.5
SCALE_FAIL_PERMILLE: Final = 5.0
SCALE_MIN_SPAN_MM: Final = 5000.0
SCALE_MIN_PAIRS: Final = 3
# Виды планов этажей и уровней в заголовке (`title.kind`, cad_walls с v1.15): только они - этажи.
PLAN_KINDS: Final = frozenset({"floor", "roof", "roof_exit", "technical"})
KIND_SINCE: Final = (1, 15)
GENERATOR_VERSION: Final = re.compile(r"\.v(\d+)(?:\.(\d+))?")
SHEET_KIND_LABELS: Final = {
    SheetKind.SECTION.value: "разрез",
    SheetKind.FACADE.value: "фасад",
    SheetKind.SCHEME.value: "схема",
    SheetKind.TABLE.value: "таблица",
    SheetKind.TEXT.value: "текст",
    SheetKind.GENERAL_DATA.value: "общие данные",
}
GROUP_NONE_KEY: Final = "none"
GROUP_NONE_LABEL: Final = "Корпус не указан"
MESSAGE_AXES_OUTDATED: Final = "оси не распознаны: пересчитайте конструкции листа"
MESSAGE_AXES_EMPTY: Final = "оси на листе не распознаны"
MESSAGE_FRAME_MISSING: Final = "кадр вида не установлен"
MESSAGE_NO_REFERENCE: Final = "в группе нет этажа с осями в обоих направлениях"
# Постановка зданий на объект: не меньше марок всего и доля согласованных среди общих.
SITE_MIN_AXES: Final = 3
# Поворот этажа кратно 90 градусам по осям: шаг и минимум согласных подписей.
QUARTER_DEG: Final = 90.0
TURN_MIN_AXES: Final = 3
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
# Опора по ядрам: этажи здания площадью от этого (м², сводный план секций), не больше трёх.
CORE_PIN_MIN_AREA_M2: Final = 1200
CORE_PIN_FLOORS: Final = 3
# Резерв по ядрам (`CoreMatch.reserve`) принимается, только если контур здания лежит в пределах
# контура основы (доля вершин, с допуском у границы) и здание не ложится на поставленные.
CORE_RESERVE_INSIDE: Final = 0.9
CORE_RESERVE_EDGE_MM: Final = 2000.0
# Отсев мест перед сравнением с вторым вариантом (резерв по ядрам): место отбрасывается, если контур
# здания там ложится на этажи поставленных зданий на одной отметке или выходит за контур плиты
# основы больше чем на пятую часть своей площади. Пятая часть - допуск на неточность контуров
# листов и на выступы (лоджии, входные группы), которые у соседних зданий заходят друг на друга;
# ложное место ядер обычно занимает чужое здание целиком или лежит вне подземки. Башня на
# стилобате (контур внутри контура стилобата) - не наложение: у них разные отметки этажей.
CORE_VARIANT_MAX_OVERLAP: Final = 0.2
CORE_VARIANT_MAX_OUTSIDE: Final = 0.2

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
    # Название листа из штампа: по нему узнаётся сводный лист отдельных планов секций.
    stamp_title: str | None = None
    # Паспорт листа (не отклонённый): вид листа, корпус и секция; паспорта нет - `None`.
    passport_kind: str | None = None
    passport_building: str | None = None
    passport_section: str | None = None
    # Отметка из заголовка листа по паспорту (мм) и этажи листа «от - до» (номера этажей):
    # отметка этажа и типовые этажи, когда движок не нашёл отметок в заголовке (объект 346).
    passport_elevation_mm: int | None = None
    passport_floor_from: int | None = None
    passport_floor_to: int | None = None
    # Показан прежний прогон листа (у нового конструкций ещё нет): текст предупреждения.
    previous_run_note: str | None = None


# «Секции 8, 9, 10, 15-16, 17, …»: перечень секций через запятую в названии листа.
SUMMARY_SECTIONS: Final = re.compile(r"Секци[ия]\s+([\d\s,\-–]+)", re.IGNORECASE)
SUMMARY_MIN_SECTIONS: Final = 3
GROUP_SUMMARY_LABEL: Final = "Сводный лист"


def is_summary_sheet(stamp_title: str | None) -> bool:
    """Сводный лист: в названии три и больше секций через запятую.

    На таком листе планы секций (техпространства, кровли) разложены отдельными картинками, как
    удобно, а не как на объекте: его оси связывают секции ложно, и в здание одной секции его
    нельзя отнести по ближайшей подписи («План тех. пространства секции 17»).
    """
    if not stamp_title:
        return False
    found = SUMMARY_SECTIONS.search(stamp_title)
    if found is None:
        return False
    items = [item for item in found.group(1).split(",") if item.strip(" -–")]
    return len(items) >= SUMMARY_MIN_SECTIONS


def _knows_kind(generator: str) -> bool:
    """Версия `cad_walls` пишет вид плана в заголовок (с v1.15); не разобрать версию - нет."""
    found = GENERATOR_VERSION.search(generator)
    if found is None:
        return False
    return (int(found.group(1)), int(found.group(2) or 0)) >= KIND_SINCE


def plan_problem(document: WallsDocument, passport_kind: str | None) -> str | None:
    """Почему лист не план этажа или уровня (в стопку этажей не идёт); план - `None`.

    План - лист с видом плана в заголовке (`title.kind`) или с паспортом `floor_plan`: паспорт
    подземной автостоянки бывает «таблица» (экспликация на том же листе), а заголовок плана у неё
    есть. Паспорт с другим видом без заголовка плана - служебный лист (разрез с конструкциями).
    Без паспорта решает заголовок; файл `cad_walls` до v1.15 вида плана не пишет - по нему лист
    не отсеять, он остаётся этажом.
    """
    title = document.heights.title
    if title is not None and title.kind in PLAN_KINDS:
        return None
    if passport_kind == SheetKind.FLOOR_PLAN.value:
        return None
    if passport_kind is not None:
        kind = SHEET_KIND_LABELS.get(passport_kind, passport_kind)
        return f"не план этажа: по паспорту листа - {kind}"
    if _knows_kind(document.generator):
        return "не план этажа: заголовок плана на листе не найден"
    return None


@dataclass(frozen=True, slots=True)
class TypicalPlan:
    """Типовой лист на несколько этажей: подписи этажей и отметки остальных от этажа листа.

    `own` - подпись этажа самого листа («К10 · С12-14 · 5 эт. (по листу «5, 7 эт.»)»), `others` -
    остальные этажи листа: подпись и разность отметки с этажом листа, мм.
    """

    own: str
    others: tuple[tuple[str, int], ...]


def typical_plan(document: WallsDocument, fallback: str) -> TypicalPlan | None:
    """Этажи типового листа по заголовку: этажей несколько и у каждого своя отметка.

    Этаж листа - тот, чья отметка заголовка равна отметке листа (иначе первый). Числа этажей и
    отметок не сходятся - разнести нечем, `None`.
    """
    title = document.heights.title
    if title is None or len(title.floors) < 2 or len(title.marks_mm) != len(title.floors):
        return None
    marks = title.marks_mm
    elevation = document.heights.floor_elevation_mm
    own = marks.index(elevation) if elevation in marks else 0
    sheet = floors_text(title.floors)

    def label(index: int) -> str:
        single = CadSheetFloorTitle(
            corps=title.corps, section=title.section, floors=[title.floors[index]], kind=title.kind
        )
        return f"{format_floor_title(single, fallback)} (по листу «{sheet} эт.»)"

    others = tuple(
        (label(i), marks[i] - marks[own])
        for i in range(len(marks))
        if i != own and marks[i] != marks[own]
    )
    return TypicalPlan(label(own), others) if others else None


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
    if is_summary_sheet(sheet.stamp_title):
        group_key = f"summary-{sheet.document_id.hex[:8]}-{sheet.page_index}"
        group_label = f"{GROUP_SUMMARY_LABEL} · {sheet.label}"
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


def _ring_area(ring: Sequence[Sequence[int]]) -> float:
    total = 0.0
    for i, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(i + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def levels_apply(document: WallsDocument) -> bool:
    """Участки уровней показываются у кровель, выходов на кровлю и этажей с несколькими отметками.

    На типовом плане знаки отметок стоят у площадок лестниц, балконов, приямков: плита этажа по ним
    развалилась бы на ступени на полэтажа ниже - этаж остаётся одной плитой.
    """
    title = document.heights.title
    if title is None or title.kind is None:
        return False
    return title.kind in LEVEL_KINDS or (title.kind == "floor" and len(title.marks_mm) > 1)


def level_zones(
    raw: WallsLevels | None, document: WallsDocument, base_z_mm: int, elevation_mm: int | None
) -> list[CadBuilding3dLevelZoneRead]:
    """Участки уровней плиты листа для вида; нет блока, не тот вид плана или один уровень - пусто.

    Участок меньше `LEVEL_MIN_AREA_MM2` (площадка лестницы, приямок, фундамент под оборудование)
    встаёт на основной уровень этажа: дыры в плите нет, а мелкие ступени не рябят.
    """
    if raw is None or not raw.zones or not levels_apply(document):
        return []
    shift = _level_shift(document, base_z_mm, elevation_mm)
    out: list[CadBuilding3dLevelZoneRead] = []
    for zone in raw.zones[:MAX_LEVEL_ZONES]:
        shell = _level_ring(zone.shell)
        top = zone.slab_top_mm if zone.slab_top_mm is not None else zone.mark_mm
        if shell is None or top is None:
            continue
        holes = [ring for ring in (_level_ring(h) for h in zone.holes) if ring is not None]
        area = _ring_area(shell) - sum(_ring_area(h) for h in holes)
        small = area < LEVEL_MIN_AREA_MM2
        marked = zone.source == "marks" and not small
        out.append(
            CadBuilding3dLevelZoneRead(
                shell=shell,
                holes=holes,
                top_mm=top + shift if marked else base_z_mm,
                mark_mm=zone.mark_mm if marked else None,
                max_mm=zone.max_mm if marked else None,
                source="marks" if marked else "base",
            )
        )
    if all(zone.top_mm == base_z_mm for zone in out):
        return []
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
class ObliqueAxis:
    """Ось под углом к листу (cad_walls v1.19) в мм DXF: точка на оси и единичное направление."""

    label: str
    point_mm: tuple[float, float]
    direction: tuple[float, float]


@dataclass(frozen=True, slots=True)
class FloorAxes:
    """Оси этажа в мм DXF: подпись -> координата (x у вертикальных, y у горизонтальных).

    `message` - почему оси непригодны для совмещения (нет блока, нет кадра, одно направление).
    `oblique` - оси под углом к листу: в совмещение этажей не идут, только в координационный файл.
    """

    vertical: dict[str, float]
    horizontal: dict[str, float]
    message: str | None
    oblique: tuple[ObliqueAxis, ...] = ()

    @property
    def usable(self) -> bool:
        return bool(self.vertical) and bool(self.horizontal)


NO_AXES: Final = FloorAxes({}, {}, MESSAGE_AXES_OUTDATED)
MESSAGE_AXES_OBLIQUE_ONLY: Final = (
    "на листе только оси под углом к листу: для совмещения нужны вертикальные и горизонтальные"
)


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


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _oblique_rows(raw: Any) -> list[tuple[str, float, tuple[float, float]]]:
    """Оси под углом из блока `axes`: подпись, угол на листе (градусы), точка на оси (pt)."""
    rows: list[tuple[str, float, tuple[float, float]]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict) or item.get("orient") != "oblique":
            continue
        label, angle, point = item.get("label"), item.get("angle_deg"), item.get("point_pt")
        if (
            isinstance(label, str)
            and label.strip()
            and isinstance(angle, int | float)
            and _finite(angle)
            and isinstance(point, list)
            and len(point) == 2
            and all(_finite(v) for v in point)
        ):
            rows.append((label.strip(), float(angle), (float(point[0]), float(point[1]))))
    return rows


def _oblique_in_mm(
    rows: list[tuple[str, float, tuple[float, float]]],
    origin: tuple[float, float],
    factor: float,
) -> tuple[ObliqueAxis, ...]:
    """Оси под углом в мм DXF: y листа вниз, y DXF вверх - направление (cos, -sin)."""
    out: dict[str, ObliqueAxis] = {}
    for label, angle, (px, py) in rows:
        if label in out:
            continue
        a = math.radians(angle)
        out[label] = ObliqueAxis(
            label=label,
            point_mm=((px - origin[0]) * factor, (origin[1] - py) * factor),
            direction=(math.cos(a), -math.sin(a)),
        )
    return tuple(out.values())


def axes_in_mm(raw_walls: Any, frame: CadFrameRead) -> FloorAxes:
    """Оси листа из walls.json в мм DXF по кадру вида.

    `pt = origin + (x_mm, -y_mm) / mm_per_pdf_point`: вертикальная ось - x, горизонтальная - y.
    Подпись, встретившаяся на листе дважды с расхождением больше допуска, отбрасывается.
    """
    block = raw_walls.get("axes") if isinstance(raw_walls, dict) else None
    if not isinstance(block, dict):
        return NO_AXES
    rows = _axis_rows(block.get("items"))
    slanted = _oblique_rows(block.get("items"))
    if not rows and not slanted:
        message = block.get("message")
        return FloorAxes(
            {}, {}, message if isinstance(message, str) and message else MESSAGE_AXES_EMPTY
        )
    origin, factor = frame.origin_pt, frame.mm_per_pdf_point
    if not frame.confirmed or origin is None or factor is None or factor <= 0:
        return FloorAxes({}, {}, frame.reason or MESSAGE_FRAME_MISSING)
    oblique = _oblique_in_mm(slanted, (origin[0], origin[1]), factor)
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
        return FloorAxes(vertical, horizontal, None, oblique)
    if not vertical and not horizontal:
        message = MESSAGE_AXES_OBLIQUE_ONLY if oblique else MESSAGE_AXES_EMPTY
        return FloorAxes({}, {}, message, oblique)
    found = "вертикальные" if vertical else "горизонтальные"
    return FloorAxes(
        vertical,
        horizontal,
        f"найдены только {found} оси: для совмещения нужны оба направления",
        oblique,
    )


@dataclass(frozen=True, slots=True)
class WindowSource:
    """Окна листа для высот по фасадам (ADR-0048 п. 6) в системе DXF листа до совмещения.

    Лежит в кеше этажа рядом с этажом: виды фасадов меняются без смены ключа этажа, поэтому
    высоты считаются на каждый запрос здания (`cad_building3d_windows`), а не кешируются.
    `frame_problem` - кадр вида не подтверждён (причина); `axes` - оси плана в мм (пусты, если
    кадра нет или осей на плане нет).
    """

    openings: tuple[WallsOpening, ...]
    extras: tuple[WallsOpeningExtras, ...]
    slab_shell: list[list[float]] | None
    corps: str | None
    section: str | None
    level: SheetLevel
    opening_floor_z_mm: int
    manual_sill_mm: int | None
    manual_head_mm: int | None
    axes: FloorAxes
    frame_problem: str | None

    @property
    def points(self) -> int:
        """Вес в кеше этажа: число точек контуров проёмов, плиты листа и осей."""
        return (
            sum(len(item.lintel or ()) for item in self.extras)
            + len(self.slab_shell or ())
            + len(self.axes.vertical)
            + len(self.axes.horizontal)
        )


def window_source(
    document: WallsDocument,
    extras: WallsFloorExtras,
    raw: Any,
    frame: CadFrameRead | None,
    levels: EffectiveLevels,
) -> WindowSource | None:
    """Окна листа без `opening_height_mm`; нет таких окон - `None` (строить нечего)."""
    windows = tuple(o for o in document.openings if o.kind == "window")
    if not any(o.opening_height_mm is None for o in windows):
        return None
    ids = {o.id for o in windows}
    title = document.heights.title
    confirmed = frame is not None and frame.confirmed
    frame_problem: str | None = None
    if frame is not None and not frame.confirmed:
        frame_problem = frame.reason or MESSAGE_FRAME_MISSING
    return WindowSource(
        openings=windows,
        extras=tuple(item for item in extras.openings if item.id in ids),
        slab_shell=None if extras.slab is None else extras.slab.shell,
        corps=None if title is None else title.corps,
        section=None if title is None else title.section,
        level=SheetLevel(
            floor_z_mm=levels.opening_floor_z_mm,
            floor_height_mm=levels.floor_height.value_mm,
            elevation_known=levels.elevation_mm is not None,
        ),
        opening_floor_z_mm=levels.opening_floor_z_mm,
        manual_sill_mm=levels.window_sill.value_mm,
        manual_head_mm=levels.window_head.value_mm,
        axes=axes_in_mm(raw, frame) if frame is not None and confirmed else NO_AXES,
        frame_problem=frame_problem,
    )


CoreRing = tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class BuiltFloor:
    floor: CadBuilding3dFloorRead
    order: tuple[float, float, int, int]
    axes: FloorAxes
    # Монолитные стены и пилоны листа (кольца, мм DXF): по ним скопления ставятся на объект.
    cores: tuple[CoreRing, ...] = ()
    # Остальные этажи типового листа; лист одного этажа - `None`.
    typical: TypicalPlan | None = None
    # Корпус и секция паспорта листа: подсказка при сведении групп одного корпуса.
    hint: tuple[str | None, str | None] = (None, None)


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


@dataclass(frozen=True, slots=True)
class _OrientMatch:
    """Совмещение по одному направлению: сдвиг, согласные подписи, остатки согласных осей после
    сдвига (мм) и число общих подписей."""

    shift: float
    labels: list[str]
    residuals: list[float]
    common: int


def _match_orient(
    reference: dict[str, float], other: dict[str, float], name: str
) -> _OrientMatch | str:
    """Смещение по одному направлению (по согласному большинству) и согласные подписи, либо
    причина отказа."""
    common = sorted(reference.keys() & other.keys(), key=_natural_key)
    if not common:
        return f"нет общих {name} осей с эталонным этажом"
    diffs = {label: reference[label] - other[label] for label in common}
    found = _plurality(diffs)
    if found is None:
        return f"{name} оси расходятся с эталоном: {', '.join(common)}"
    shift, labels = found
    return _OrientMatch(shift, labels, [diffs[label] - shift for label in labels], len(common))


def _scale_ratio(
    base: FloorAxes, ours: FloorAxes, only: frozenset[str] | None = None
) -> float | None:
    """Отношение шкал эталон / лист: медиана отношений расстояний между общими осями.

    Берутся пары осей одного направления не ближе `SCALE_MIN_SPAN_MM` на листе; `only` - только
    эти подписи (согласные). Медиана не боится нескольких кружков на выносках. Пар меньше
    `SCALE_MIN_PAIRS` - оценки нет.
    """
    ratios: list[float] = []
    for ref, own in ((base.vertical, ours.vertical), (base.horizontal, ours.horizontal)):
        labels = sorted(label for label in ref.keys() & own.keys() if only is None or label in only)
        for i, first in enumerate(labels):
            for second in labels[i + 1 :]:
                span = own[second] - own[first]
                if abs(span) >= SCALE_MIN_SPAN_MM:
                    ratios.append((ref[second] - ref[first]) / span)
    return statistics.median(ratios) if len(ratios) >= SCALE_MIN_PAIRS else None


def _permille(ratio: float) -> float:
    return round((ratio - 1.0) * 1000.0, 2)


def _scale_message(ratio: float) -> str:
    drift = f"{_permille(ratio):+.1f}".replace(".", ",")
    times = f"{ratio:.3f}".replace(".", ",")
    return (
        f"масштаб листа: расстояния между осями расходятся с эталоном на {drift} ‰ "
        f"(в {times} раза) - проверьте калибровку листа и эталона"
    )


def _scale_explains(base: FloorAxes, ours: FloorAxes) -> float | None:
    """Отношение шкал, если расхождение осей с эталоном объясняется масштабом листа.

    Оси «расходятся», когда лист построен в другом масштабе: сдвиги марок растут вдоль листа.
    Масштаб - причина, если наклон шкалы больше `SCALE_FAIL_PERMILLE` и после поправки на него
    оси сходятся в обоих направлениях. Иначе - `None` (другая сетка осей, выноски).
    """
    ratio = _scale_ratio(base, ours)
    if ratio is None or ratio <= 0 or abs(_permille(ratio)) <= SCALE_FAIL_PERMILLE:
        return None
    for ref, own in ((base.vertical, ours.vertical), (base.horizontal, ours.horizontal)):
        scaled = {label: value * ratio for label, value in own.items()}
        if isinstance(_match_orient(ref, scaled, ""), str):
            return None
    return ratio


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
    windows = (
        floor.windows
        if floor.windows is None or (ix == 0 and iy == 0)
        else [
            window.model_copy(update={"shell": [[x + ix, y + iy] for x, y in window.shell]})
            for window in floor.windows
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
            "windows": windows,
            "levels": levels,
            "outline": [[x + dx, y + dy] for x, y in floor.outline],
            "bbox": None if box is None else [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy],
            "offset_mm": (round(ox + dx, 3), round(oy + dy, 3)),
        }
    )


def _center(box: Sequence[float] | None) -> Point | None:
    return None if box is None else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _fallback(
    item: BuiltFloor,
    reference: BuiltFloor | None,
    message: str,
    scale_permille: float | None = None,
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
        update={
            "alignment": "none",
            "alignment_axes": [],
            "alignment_message": message,
            "alignment_scale_permille": scale_permille,
        }
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
            dataclasses.replace(
                items[i],
                floor=items[i].floor.model_copy(update={"group_key": key, "group_label": label}),
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


def _quarters(rotation_deg: float) -> int:
    """Число четвертей оборота (0-3) для угла, кратного 90 градусам (поворот совмещения по осям)."""
    return round(rotation_deg / QUARTER_DEG) % 4


def _turn_axes(axes: FloorAxes, quarters: int) -> FloorAxes:
    """Оси после поворота вида на `quarters` · 90 градусов против часовой вокруг начала кадра.

    Поворот на 90 градусов: вертикальная ось `x = c` становится горизонтальной `y = c`, а
    горизонтальная `y = c` - вертикальной `x = -c`; на 180 - знаки обеих координат меняются; на
    270 - `x = c` становится `y = -c`, а `y = c` - `x = c`.
    """
    quarters %= 4
    vertical, horizontal = axes.vertical, axes.horizontal
    if quarters == 0:
        return axes
    if quarters == 1:
        return FloorAxes({k: -v for k, v in horizontal.items()}, dict(vertical), axes.message)
    if quarters == 2:
        return FloorAxes(
            {k: -v for k, v in vertical.items()},
            {k: -v for k, v in horizontal.items()},
            axes.message,
        )
    return FloorAxes(dict(horizontal), {k: -v for k, v in vertical.items()}, axes.message)


_TurnedMatch = tuple[int, FloorAxes, _OrientMatch, _OrientMatch]


def _turned_match(base: FloorAxes, ours: FloorAxes) -> _TurnedMatch | None:
    """Поворот этажа на 90, 180 или 270 градусов, при котором оси сходятся с эталоном.

    Подписи общих осей у повёрнутого листа меняют направление (вертикальные становятся
    горизонтальными). Берётся поворот с наибольшим числом согласных подписей; нужно не меньше
    `TURN_MIN_AXES` согласных подписей в сумме - случайное совпадение нескольких марок поворот не
    даёт. Нет такого поворота - `None`.
    """
    best: _TurnedMatch | None = None
    best_count = 0
    for quarters in (1, 2, 3):
        turned = _turn_axes(ours, quarters)
        along_x = _match_orient(base.vertical, turned.vertical, "")
        along_y = _match_orient(base.horizontal, turned.horizontal, "")
        if isinstance(along_x, str) or isinstance(along_y, str):
            continue
        count = len(along_x.labels) + len(along_y.labels)
        if count >= TURN_MIN_AXES and count > best_count:
            best, best_count = (quarters, turned, along_x, along_y), count
    return best


def _align_to(item: BuiltFloor, reference: BuiltFloor) -> CadBuilding3dFloorRead:
    """Совмещение этажа с эталоном: сдвиг по осям, а у повёрнутого на 90, 180 или 270 градусов
    листа - сначала поворот вокруг начала кадра (`rotation_deg`), потом сдвиг:
    `p_эталона = R(rotation_deg) · p_вида + offset_mm`."""
    ours, base = item.axes, reference.axes
    quarters = 0
    along_x = _match_orient(base.vertical, ours.vertical, "вертикальных")
    along_y = _match_orient(base.horizontal, ours.horizontal, "горизонтальных")
    if isinstance(along_x, str) or isinstance(along_y, str):
        turned = _turned_match(base, ours)
        if turned is not None:
            quarters, ours, along_x, along_y = turned
    if isinstance(along_x, str) or isinstance(along_y, str):
        wrong = _scale_explains(base, ours)
        if wrong is not None:
            return _fallback(item, reference, _scale_message(wrong), _permille(wrong))
        problems = [m for m in (along_x, along_y) if isinstance(m, str)]
        return _fallback(item, reference, "; ".join(problems))
    labels = [*along_x.labels, *along_y.labels]
    ratio = _scale_ratio(base, ours, frozenset(labels))
    permille = None if ratio is None else _permille(ratio)
    if ratio is not None and permille is not None and abs(permille) > SCALE_FAIL_PERMILLE:
        return _fallback(item, reference, _scale_message(ratio), permille)
    shifted = (
        _shifted(item.floor, along_x.shift, along_y.shift)
        if quarters == 0
        else _rotated(item.floor, quarters * QUARTER_DEG, along_x.shift, along_y.shift)
    )
    residuals = [*along_x.residuals, *along_y.residuals]
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
            "alignment_rms_mm": round(math.sqrt(sum(r * r for r in residuals) / len(residuals)), 1),
            "alignment_max_mm": round(max(abs(r) for r in residuals), 1),
            "alignment_axes_common": along_x.common + along_y.common,
            "alignment_scale_permille": permille,
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
    # Ручная привязка по двум парам точек (`placement = manual`): id применённого пина.
    pin_id: uuid.UUID | None = None


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
        axes = _turn_axes(item.axes, _quarters(floor.rotation_deg))
        for label, x in axes.vertical.items():
            values.setdefault(("vertical", label), []).append(x + dx)
        for label, y in axes.horizontal.items():
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
    key = (hash(tuple(base)), hash(tuple(other)))
    if key in _CORE_CACHE:
        _CORE_CACHE.move_to_end(key)
        return _CORE_CACHE[key]
    found = cad_site_cores.register(base_index(base), other)
    _CORE_CACHE[key] = found
    while len(_CORE_CACHE) > CORE_CACHE_MAX:
        _CORE_CACHE.popitem(last=False)
    return found


def base_index(base: Sequence[CoreRing]) -> cad_site_cores.BaseIndex:
    """Индекс монолита основы (клетки и элементы) из кеша процесса: ключ - содержимое колец."""
    base_key = hash(tuple(base))
    index = _BASE_CACHE.get(base_key)
    if index is None:
        index = cad_site_cores.index_base(base)
        _BASE_CACHE[base_key] = index
        while len(_BASE_CACHE) > BASE_CACHE_MAX:
            _BASE_CACHE.popitem(last=False)
    else:
        _BASE_CACHE.move_to_end(base_key)
    return index


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
        out.append(
            [
                _moved_ring(ring, aligned[index].rotation_deg, fx + ox, fy + oy)
                for ring in items[index].cores
            ]
        )
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
    if len(clusters) <= 1:
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
        site = [_moved_ring(r, floor.rotation_deg, fx + ox, fy + oy) for r in items[biggest].cores]
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


def _axis_links(
    infos: dict[str, _GroupInfo],
) -> dict[tuple[str, str], _SiteMatch]:
    """Совпадения осей всех пар зданий с осями в обоих направлениях: сдвиг из `other` в `base`."""
    with_axes = [k for k in infos if infos[k].axes.usable]
    links: dict[tuple[str, str], _SiteMatch] = {}
    for base in with_axes:
        for other in with_axes:
            if base != other and (match := _site_match(infos[base].axes, infos[other].axes)):
                links[(base, other)] = match
    return links


def _group_floor_cores(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    key: str,
    min_area_m2: int = CORE_PIN_MIN_AREA_M2,
) -> list[tuple[int, list[CoreRing]]]:
    """Ядра нижних больших этажей здания по отдельности, в системе эталона здания (снизу вверх),
    с индексом этажа.

    Пробуются только этажи от `min_area_m2`: сводный план нескольких секций по ядрам встаёт
    однозначно, а ядро одной башни похоже на многие места подземки - башня встаёт по осям от
    опоры (резерв пробует все нижние этажи, но с отрывом от второго варианта и проверками по
    месту). Не больше `CORE_PIN_FLOORS`: первый этаж может не совпасть (монолит другого уровня),
    а следующий - совпасть.
    """
    rows = sorted(
        (floor.alignment == "none", not floor.elevation_known, floor.base_z_mm, i)
        for i, floor in enumerate(aligned)
        if floor.group_key == key
        and len(items[i].cores) >= CORE_MIN_RINGS
        and _floor_area_m2(floor) >= min_area_m2
    )
    out: list[tuple[int, list[CoreRing]]] = []
    for *_rank, index in rows[:CORE_PIN_FLOORS]:
        fx, fy = aligned[index].offset_mm
        rotation = aligned[index].rotation_deg
        out.append((index, [_moved_ring(ring, rotation, fx, fy) for ring in items[index].cores]))
    return out


SiteLevel = tuple[int, tuple[float, float, float, float]]


def _site_levels(info: _GroupInfo, rotation_deg: float, offset: Point) -> list[SiteLevel]:
    """Этажи здания с отметкой в системе объекта: отметка и bbox после поворота и сдвига."""
    levels: list[SiteLevel] = []
    for _low, _high, z, box in info.levels:
        corners = [
            cad_site_cores.transform_point(x, y, rotation_deg, offset[0], offset[1])
            for x in (box[0], box[2])
            for y in (box[1], box[3])
        ]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        levels.append((z, (min(xs), min(ys), max(xs), max(ys))))
    return levels


def _site_clash(first: Sequence[SiteLevel], second: Sequence[SiteLevel]) -> bool:
    """Этажи двух зданий на одной отметке занимают одно место на объекте."""
    return any(
        abs(z1 - z2) <= SITE_SAME_LEVEL_MM and _overlap_share(box1, box2) > SITE_MAX_OVERLAP
        for z1, box1 in first
        for z2, box2 in second
    )


@dataclass(frozen=True, slots=True)
class _Reserve:
    """Итог резерва по ядрам: принятая опора (`key`, `pin`) и причины отказа по зданиям.

    `review` - пометка «на проверку» для посадки по согласию этажей или после отсева мест; у
    обычного резерва - `None`.
    """

    key: str | None
    pin: cad_site_cores.CoreMatch | None
    notes: dict[str, str]
    tried: dict[str, cad_site_cores.CoreMatch]
    review: str | None = None


# Этаж здания для отсева мест: отметка и контур (в системе здания либо объекта).
_LevelOutline = tuple[int, list[Point]]


@dataclass(frozen=True, slots=True)
class _Footprint:
    """Контур здания для отсева мест (в системе здания): выборка точек площади самого большого
    этажа, её центр и выборки точек этажей с известной отметкой."""

    samples: tuple[Point, ...]
    centre: Point
    levels: tuple[tuple[int, tuple[Point, ...]], ...]


def _group_outlines(
    aligned: Sequence[CadBuilding3dFloorRead], key: str
) -> list[CadBuilding3dFloorRead]:
    """Этажи здания с контуром; совмещённые по осям в приоритете (остальные лежат где попало)."""
    floors = [f for f in aligned if f.group_key == key and len(f.outline) >= 3]
    return [f for f in floors if f.alignment != "none"] or floors


def _footprint(aligned: Sequence[CadBuilding3dFloorRead], key: str) -> _Footprint | None:
    floors = _group_outlines(aligned, key)
    if not floors:
        return None
    biggest = max(floors, key=lambda f: (_polygon_area(f.outline), f.label))
    samples = cad_site_cores.area_samples(biggest.outline)
    if not samples:
        return None
    centre = (
        sum(x for x, _ in samples) / len(samples),
        sum(y for _, y in samples) / len(samples),
    )
    levels: dict[int, tuple[Point, ...]] = {}
    for floor in sorted(floors, key=lambda f: (f.base_z_mm, f.label)):
        if floor.elevation_known and floor.base_z_mm not in levels:
            own = cad_site_cores.area_samples(floor.outline)
            levels[floor.base_z_mm] = tuple(own[:: max(1, len(own) // 250)])
    return _Footprint(tuple(samples), centre, tuple(levels.items()))


def _polygon_area(outline: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for i, (x0, y0) in enumerate(outline):
        x1, y1 = outline[(i + 1) % len(outline)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def _placed_outlines(
    aligned: Sequence[CadBuilding3dFloorRead], placed: dict[str, GroupPlacement]
) -> list[_LevelOutline]:
    """Контуры этажей поставленных зданий (кроме основы) в системе объекта, по ключу здания."""
    outlines: list[_LevelOutline] = []
    for key in sorted(placed):
        p = placed[key]
        if p.placement == "reference":
            continue
        for floor in _group_outlines(aligned, key):
            if floor.elevation_known:
                outlines.append(
                    (
                        floor.base_z_mm,
                        [
                            cad_site_cores.transform_point(x, y, p.rotation_deg, *p.offset_mm)
                            for x, y in floor.outline
                        ],
                    )
                )
    return outlines


def _variant_verdict(
    variant: cad_site_cores.CoreVariant,
    footprint: _Footprint,
    taken: Sequence[_LevelOutline],
    base_outline: Sequence[Sequence[float]],
) -> str | None:
    """Почему место отсеивается; годится - `None`.

    `outside` - контур вне плиты основы больше `CORE_VARIANT_MAX_OUTSIDE`; `taken` - на какой-то
    отметке контур ложится на этажи поставленных зданий больше `CORE_VARIANT_MAX_OVERLAP`
    (на разных отметках здания делят место: башня на стилобате).
    """

    def moved(samples: Sequence[Point]) -> list[Point]:
        return [
            cad_site_cores.transform_point(x, y, variant.rotation_deg, variant.tx, variant.ty)
            for x, y in samples
        ]

    outside = 1.0 - cad_site_cores.covered_share(moved(footprint.samples), [base_outline])
    if outside > CORE_VARIANT_MAX_OUTSIDE:
        return "outside"
    for z, samples in footprint.levels:
        same = [o for zz, o in taken if abs(zz - z) <= SITE_SAME_LEVEL_MM]
        if same and cad_site_cores.covered_share(moved(samples), same) > CORE_VARIANT_MAX_OVERLAP:
            return "taken"
    return None


def _floor_choice(
    floor: int,
    match: cad_site_cores.CoreMatch,
    footprint: _Footprint,
    taken: Sequence[_LevelOutline],
    base_outline: Sequence[Sequence[float]],
    verdicts: dict[tuple[float, float, float], str | None],
) -> tuple[cad_site_cores.FloorChoice | None, dict[str, int]]:
    """Лучшее место этажа среди не отсеянных и сколько мест отсеяно по причинам."""
    dropped = {"taken": 0, "outside": 0}
    kept: list[cad_site_cores.CoreVariant] = []
    for variant in sorted(match.variants, key=lambda v: -v.share):
        mark = (variant.rotation_deg, variant.tx, variant.ty)
        if mark not in verdicts:
            verdicts[mark] = _variant_verdict(variant, footprint, taken, base_outline)
        reason = verdicts[mark]
        if reason is None:
            kept.append(variant)
        else:
            dropped[reason] += 1
    if not kept:
        return None, dropped
    best = kept[0]
    second = cad_site_cores.second_share(best, kept)
    return (
        cad_site_cores.FloorChoice(floor, match, best, second, sum(dropped.values())),
        dropped,
    )


def _review_note(decision: cad_site_cores.Decision, dropped: dict[str, int]) -> str:
    """Пометка «на проверку» с числами: сколько этажей согласны, доля, отрыв до и после отсева."""
    choice = decision.choice
    before = choice.match.second_share
    gap = (
        f"у другого места {choice.second:.0%} (до отсева {before:.0%}; отсеяно мест: "
        f"{dropped['taken']} на занятых зданиями, {dropped['outside']} вне плиты подземки)"
    )
    if decision.kind == "agreement":
        return (
            f"на проверку: посадка по согласию этажей, {decision.agreed} из {decision.floors} "
            f"этажей независимо дали одно место; совпадение {choice.best.share:.0%}, {gap}"
        )
    return (
        f"на проверку: посадка после отсева конкурентов; совпадение {choice.best.share:.0%}, {gap}"
    )


def _reserve_place_note(
    key: str,
    best: cad_site_cores.CoreVariant,
    matched: int,
    second: float,
    aligned: Sequence[CadBuilding3dFloorRead],
    infos: dict[str, _GroupInfo],
    placed: dict[str, GroupPlacement],
    base_outline: Sequence[Sequence[float]],
) -> str | None:
    """Проверки резерва по месту: контур в пределах основы и нет наложения на поставленные здания
    на той же отметке. Прошло - `None`, иначе причина отказа."""
    # Контур здания: этаж, давший совмещение, и совмещённые с ним по осям этажи группы.
    together = aligned[matched].alignment != "none"
    points = [
        cad_site_cores.transform_point(x, y, best.rotation_deg, best.tx, best.ty)
        for i, floor in enumerate(aligned)
        if i == matched or (together and floor.group_key == key and floor.alignment != "none")
        for x, y in floor.outline
    ]
    inside = cad_site_cores.inside_share(points, base_outline, CORE_RESERVE_EDGE_MM)
    if inside < CORE_RESERVE_INSIDE:
        return (
            f"совпадение по ядрам {best.share:.0%} (у другого варианта "
            f"{second:.0%}) не принято: контур здания выходит за контур основы "
            f"({inside:.0%} внутри)"
        )
    levels = _site_levels(infos[key], best.rotation_deg, (best.tx, best.ty))
    clash = next(
        (
            k
            for k, p in sorted(placed.items())
            if _site_clash(_site_levels(infos[k], p.rotation_deg, p.offset_mm), levels)
        ),
        None,
    )
    if clash is not None:
        return (
            f"совпадение по ядрам {best.share:.0%} (у другого варианта "
            f"{second:.0%}) не принято: здание ложится на «{infos[clash].label}» "
            "на той же отметке"
        )
    return None


def _reserve_pin(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    infos: dict[str, _GroupInfo],
    placed: dict[str, GroupPlacement],
    site: Sequence[CoreRing],
    base_outline: Sequence[Sequence[float]],
    skip: frozenset[str] = frozenset(),
) -> _Reserve:
    """Резерв по ядрам: первое не поставленное здание, которое можно поставить с проверками.

    `skip` - здания, ожидающие ручной привязки (ADR-0052): резерв их не ставит.

    Пробуются нижние этажи каждого не поставленного здания (любой площади), большие здания
    первыми. Совмещение годится, если оно резервное (`CoreMatch.reserve`: доля меньше обычной, но
    с большим отрывом от второго варианта), контур совмещённых этажей здания лежит в пределах
    контура основы и здание не ложится на уже поставленные на той же отметке. Одна доля ядер для
    башни ничего не значит: её ядро похоже на многие места подземки.

    Если так не встало ни одно здание, остальные пробуются по убыванию доли (`_reserve_choose`):
    места, занятые поставленными зданиями или лежащие вне плиты основы, отсеиваются, и здание
    встаёт, когда его этажи независимо дали одно место либо после отсева появился отрыв. Такая
    посадка принимается с пометкой «на проверку».
    """
    notes: dict[str, str] = {}
    tried: dict[str, cad_site_cores.CoreMatch] = {}
    matches: dict[str, list[tuple[int, cad_site_cores.CoreMatch]]] = {}
    sizes = {
        key: max((_floor_area_m2(f) for f in aligned if f.group_key == key), default=0)
        for key in infos
    }
    for key in sorted(
        (k for k in infos if k not in placed and k not in skip), key=lambda k: (-sizes[k], k)
    ):
        best: cad_site_cores.CoreMatch | None = None
        matched = -1
        for index, rings in _group_floor_cores(items, aligned, key, 0):
            found = _register_cached(site, rings)
            if found is None:
                continue
            matches.setdefault(key, []).append((index, found))
            if key not in tried or found.share > tried[key].share:
                tried[key] = found
            if found.reserve and (best is None or found.share > best.share):
                best, matched = found, index
        if best is None:
            continue
        note = _reserve_place_note(
            key,
            cad_site_cores.CoreVariant(best.rotation_deg, best.tx, best.ty, best.share),
            matched,
            best.second_share,
            aligned,
            infos,
            placed,
            base_outline,
        )
        if note is not None:
            notes[key] = note
            continue
        return _Reserve(key, best, notes, tried)
    return _reserve_choose(aligned, infos, placed, base_outline, matches, notes, tried)


def _reserve_choose(
    aligned: Sequence[CadBuilding3dFloorRead],
    infos: dict[str, _GroupInfo],
    placed: dict[str, GroupPlacement],
    base_outline: Sequence[Sequence[float]],
    matches: dict[str, list[tuple[int, cad_site_cores.CoreMatch]]],
    notes: dict[str, str],
    tried: dict[str, cad_site_cores.CoreMatch],
) -> _Reserve:
    """Вторая очередь резерва: согласие этажей и отсев мест (`cad_site_cores.choose`)."""
    taken = _placed_outlines(aligned, placed)
    rows: list[tuple[float, str, cad_site_cores.Decision, dict[str, int]]] = []
    for key in sorted(matches):
        footprint = _footprint(aligned, key)
        if footprint is None:
            continue
        verdicts: dict[tuple[float, float, float], str | None] = {}
        choices: list[cad_site_cores.FloorChoice] = []
        dropped: dict[int, dict[str, int]] = {}
        for index, match in matches[key]:
            choice, lost = _floor_choice(index, match, footprint, taken, base_outline, verdicts)
            if choice is not None:
                choices.append(choice)
                dropped[index] = lost
        decision = cad_site_cores.choose(choices, footprint.centre)
        if decision is not None:
            rows.append((decision.choice.best.share, key, decision, dropped[decision.choice.floor]))
    # Порядок посадки не зависит от обхода словарей: по убыванию доли, затем по ключу.
    for _share, key, decision, lost in sorted(rows, key=lambda r: (-r[0], r[1])):
        choice = decision.choice
        note = _reserve_place_note(
            key,
            choice.best,
            choice.floor,
            choice.second,
            aligned,
            infos,
            placed,
            base_outline,
        )
        if note is not None:
            notes[key] = note
            continue
        pin = cad_site_cores.CoreMatch(
            choice.best.rotation_deg,
            choice.best.tx,
            choice.best.ty,
            choice.best.share,
            choice.second,
            False,
            choice.match.variants,
        )
        return _Reserve(key, pin, notes, tried, _review_note(decision, lost))
    return _Reserve(None, None, notes, tried)


# --------------------------------------------------------------------------- ручная привязка


@dataclass(frozen=True, slots=True)
class PinIgnored:
    """Ручная привязка, не применённая при посадке: причина для человека (`site_pin_ignored`)."""

    pin_id: uuid.UUID
    message: str


@dataclass(frozen=True, slots=True)
class SiteResult:
    placements: dict[str, GroupPlacement]
    ignored: tuple[PinIgnored, ...] = ()


@dataclass(frozen=True, slots=True)
class _PinCandidate:
    pin: SitePin
    source: int
    target: int


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


class _ManualPins:
    """Ручные привязки корпусов к площадке за одну посадку (ADR-0052).

    Лист источника и лист цели узнаются в сборке по тройке (ревизия, страница, вид). Группа
    источника встаёт, когда группа цели уже поставлена: `G = S_цели ∘ T_пина ∘ A_источника⁻¹`
    (`pins_math.group_placement`). До этого группа «ожидает» (`held`): по осям и ядрам её не
    ставят, чтобы привязка не оказалась слабее автоматики. Не применённая привязка получает
    причину (`ignored`), а не молчание.
    """

    def __init__(
        self,
        pins: Sequence[SitePin],
        aligned: Sequence[CadBuilding3dFloorRead],
        infos: dict[str, _GroupInfo],
        base_key: str | None,
    ) -> None:
        self._aligned = aligned
        self._infos = infos
        self._ignored: dict[uuid.UUID, str] = {}
        self._order: list[uuid.UUID] = []
        self._groups: dict[str, list[_PinCandidate]] = {}
        self._done: set[str] = set()
        index: dict[pins_math.SheetKey, int] = {}
        for i, floor in enumerate(aligned):
            index.setdefault((floor.revision_id, floor.page_index, floor.view), i)
        for pin in sorted(pins, key=lambda p: (p.created_at, str(p.id))):
            self._order.append(pin.id)
            source, target = index.get(pin.source), index.get(pin.target)
            if source is None or target is None:
                which = pin.source if source is None else pin.target
                role = "источника" if source is None else "цели"
                self._ignore(
                    pin.id,
                    f"лист {role} (стр. {which[1] + 1}, вид {which[2]}) не найден среди этажей "
                    "сборки: ревизия документа заменена или лист не построен",
                )
                continue
            source_key, target_key = aligned[source].group_key, aligned[target].group_key
            label = self._label(source_key)
            if source_key == base_key:
                self._ignore(pin.id, f"«{label}» - основа площадки, привязывать её не нужно")
            elif source_key == target_key:
                self._ignore(pin.id, f"оба листа привязки входят в здание «{label}»")
            else:
                self._groups.setdefault(source_key, []).append(_PinCandidate(pin, source, target))

    def _label(self, key: str) -> str:
        info = self._infos.get(key)
        return key if info is None else info.label

    def _ignore(self, pin_id: uuid.UUID, message: str) -> None:
        self._ignored.setdefault(pin_id, message)

    def held(self, placed: dict[str, GroupPlacement]) -> frozenset[str]:
        """Здания, ожидающие цели своей привязки."""
        return frozenset(k for k in self._groups if k not in self._done and k not in placed)

    def _candidate_placement(
        self, candidate: _PinCandidate, target: GroupPlacement
    ) -> tuple[float, Point]:
        s, t = self._aligned[candidate.source], self._aligned[candidate.target]
        t_rotation = t.rotation_deg + target.rotation_deg
        rx, ry = pins_math.rotate(t.offset_mm, target.rotation_deg)
        rotation, offset = pins_math.group_placement(
            source_rotation_deg=s.rotation_deg,
            source_offset_mm=s.offset_mm,
            target_rotation_deg=t_rotation,
            target_offset_mm=(rx + target.offset_mm[0], ry + target.offset_mm[1]),
            pin_rotation_deg=candidate.pin.rotation_deg,
            pin_offset_mm=candidate.pin.offset_mm,
        )
        return rotation, offset

    def apply(self, placed: dict[str, GroupPlacement], hops: dict[str, int]) -> bool:
        """Ставит одно здание по привязке, цель которой уже поставлена; нечего ставить - `False`."""
        for key in sorted(self._groups):
            if key in self._done or key in placed:
                continue
            ready = [c for c in self._groups[key] if self._aligned[c.target].group_key in placed]
            if not ready:
                continue
            options = [
                (c, *self._candidate_placement(c, placed[self._aligned[c.target].group_key]))
                for c in ready
            ]
            self._done.add(key)
            problem = self._disagreement(key, options)
            if problem is not None:
                for candidate in self._groups[key]:
                    self._ignore(candidate.pin.id, problem)
                return True
            chosen, rotation, offset = options[-1]
            pin = chosen.pin
            placed[key] = GroupPlacement(
                "manual",
                (round(offset[0], 3), round(offset[1], 3)),
                (),
                self._aligned[chosen.target].group_key,
                f"привязано вручную: невязка {round(pin.residual_mm)} мм, "
                f"база {_decimal(pin.baseline_mm / 1000)} м",
                key,
                rotation,
                None,
                pin.id,
            )
            hops[key] = 0
            return True
        return False

    def _disagreement(
        self, key: str, options: Sequence[tuple[_PinCandidate, float, tuple[float, float]]]
    ) -> str | None:
        """Привязки одного здания по разным листам должны давать одно место: поворот и точка."""
        if len(options) < 2:
            return None
        floor = self._aligned[options[0][0].source]
        box = floor.bbox
        centre = (0.0, 0.0) if box is None else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        sites = [
            pins_math.apply_transform(rotation, offset, centre) for _c, rotation, offset in options
        ]
        for i, (_a, rotation_a, _oa) in enumerate(options):
            for j in range(i + 1, len(options)):
                turn = cad_site_cores._turn_gap(rotation_a, options[j][1])
                shift = math.dist(sites[i], sites[j])
                if (
                    turn > cad_site_cores.AGREE_ROTATION_DEG
                    or shift > cad_site_cores.AGREE_SHIFT_MM
                ):
                    return (
                        f"привязки здания «{self._label(key)}» по разным листам расходятся: "
                        f"поворот на {_decimal(turn)}°, положение на {_decimal(shift / 1000)} м"
                    )
        return None

    def release(self, placed: dict[str, GroupPlacement]) -> list[str]:
        """Цели ожидающих привязок не поставлены: привязки не применяются, здания свободны."""
        released = sorted(self.held(placed))
        for key in released:
            self._done.add(key)
            for candidate in self._groups[key]:
                target = self._label(self._aligned[candidate.target].group_key)
                self._ignore(
                    candidate.pin.id,
                    f"здание «{target}», к которому привязано «{self._label(key)}», "
                    "не поставлено на объект",
                )
        return released

    def finish(self, placed: dict[str, GroupPlacement]) -> tuple[PinIgnored, ...]:
        """Итог посадки: привязки, которым не нашлось места, получают причину."""
        for key, candidates in sorted(self._groups.items()):
            current = placed.get(key)
            if current is None or current.placement == "manual":
                continue
            for candidate in candidates:
                self._ignore(
                    candidate.pin.id,
                    f"«{self._label(key)}» уже поставлено автоматически "
                    f"({current.placement}), ручная привязка к нему не применена",
                )
        return tuple(PinIgnored(i, self._ignored[i]) for i in self._order if i in self._ignored)


def _site_fallback(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    infos: dict[str, _GroupInfo],
    pins: Sequence[SitePin],
    base_key: str | None,
) -> SiteResult:
    """Постановка без основы по ядрам (осями и скоплениями); ручные привязки - только зданиям,
    которые автоматика не поставила (`none`)."""
    manual = _ManualPins(pins, aligned, infos, base_key)
    placements = place_by_cores(items, aligned, place_groups(items, aligned))
    live = {k: p for k, p in placements.items() if p.placement != "none"}
    hops: dict[str, int] = {}
    while manual.apply(live, hops):
        pass
    manual.release(live)
    for key, found in live.items():
        if found.placement == "manual":
            placements[key] = found
    return SiteResult(placements, manual.finish(live))


def place_site(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    pins: Sequence[SitePin] = (),
) -> dict[str, GroupPlacement]:
    """Постановка зданий на объект (`place_site_report` без отчёта о ручных привязках)."""
    return place_site_report(items, aligned, pins).placements


def place_site_report(
    items: Sequence[BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    pins: Sequence[SitePin] = (),
) -> SiteResult:
    """Постановка зданий на объект: опоры по ядрам, остальные - по осям от ближайшей опоры.

    Основа - здание с самым большим этажом (план подземной автостоянки несёт ядра всех корпусов).
    Каждое здание пробует встать на неё по ядрам своего нижнего этажа (`cad_site_cores`): сводные
    первые этажи секций ставятся однозначно и становятся опорами, отдельные башни обычно нет. Затем
    здания присоединяются по общим маркам осей к уже поставленным - сначала к опорам, потом дальше
    по цепочке (ближайшая опора выигрывает): сводный лист, на котором крыло комплекса нарисовано не
    в той ориентации, что на объекте, не уводит крыло, у которого есть своя опора. Совпадение марок
    без номера секции принимается только без наложения этажей на одной отметке.

    Здание, не вставшее ни так, ни так, пробует резерв по ядрам (`_reserve_pin`): совмещение с
    меньшей долей, но с большим отрывом от второго варианта, принятое только в пределах контура
    основы и без наложения на поставленные здания. Вставшее по резерву - тоже опора: к нему по осям
    присоединяются остальные.

    Ручные привязки (`pins`, ADR-0052) сильнее автоматики для своего здания: оно встаёт сразу,
    как только поставлено здание цели, до резерва и присоединения по осям, и становится опорой
    для соседей. Непригодная привязка называется в `SiteResult.ignored`.

    Если ни одно здание по ядрам не встало, постановка - как раньше, только по осям
    (`place_groups` и `place_by_cores`).
    """
    infos = _group_infos(items, aligned)
    keys = sorted(infos, key=lambda k: (_natural_key(infos[k].label), k))
    if not keys:
        return SiteResult({}, _ManualPins(pins, aligned, infos, None).finish({}))
    if len(keys) == 1:
        placed_one = {keys[0]: GroupPlacement("reference", (0.0, 0.0), (), None, None, keys[0])}
        return SiteResult(placed_one, _ManualPins(pins, aligned, infos, keys[0]).finish(placed_one))
    biggest = max(
        (i for i, floor in enumerate(aligned) if len(items[i].cores) >= CORE_MIN_RINGS),
        key=lambda i: (_floor_area_m2(aligned[i]), -i),
        default=None,
    )
    if biggest is None:
        return _site_fallback(items, aligned, infos, pins, None)
    base_key = aligned[biggest].group_key
    manual = _ManualPins(pins, aligned, infos, base_key)
    fx, fy = aligned[biggest].offset_mm
    site = [_moved_ring(r, aligned[biggest].rotation_deg, fx, fy) for r in items[biggest].cores]
    core_pins: dict[str, cad_site_cores.CoreMatch] = {}
    tried: dict[str, cad_site_cores.CoreMatch | None] = {}
    for key in keys:
        if key == base_key:
            continue
        best: cad_site_cores.CoreMatch | None = None
        for _index, rings in _group_floor_cores(items, aligned, key):
            found = _register_cached(site, rings)
            if found is not None and (
                best is None or (found.accepted, found.share) > (best.accepted, best.share)
            ):
                best = found
        if best is None:
            continue
        tried[key] = best
        if best.accepted:
            core_pins[key] = best
    placed: dict[str, GroupPlacement] = {
        base_key: GroupPlacement("reference", (0.0, 0.0), (), None, None, base_key)
    }
    hops: dict[str, int] = {base_key: 0}

    def pin_group(key: str, pin: cad_site_cores.CoreMatch, review: str | None = None) -> None:
        placed[key] = GroupPlacement(
            "cores",
            (pin.tx, pin.ty),
            (),
            base_key,
            review,
            key,
            pin.rotation_deg,
            round(pin.share, 3),
        )
        hops[key] = 0

    base_outline = aligned[biggest].outline
    reserve_notes: dict[str, str] = {}
    reviews: dict[str, str] = {}
    while manual.apply(placed, hops):
        pass
    waiting = manual.held(placed)
    if not core_pins and len(placed) == 1:
        first = _reserve_pin(items, aligned, infos, placed, site, base_outline, waiting)
        if (first.key is None or first.pin is None) and waiting:
            # Ждать привязкам нечего: цели не из чего поставить.
            manual.release(placed)
            first = _reserve_pin(items, aligned, infos, placed, site, base_outline)
        if first.key is None or first.pin is None:
            return _site_fallback(items, aligned, infos, pins, base_key)
        core_pins[first.key] = first.pin
        if first.review is not None:
            reviews[first.key] = first.review
    links = _axis_links(infos)
    for key, found in core_pins.items():
        if key not in placed and key not in manual.held(placed):
            pin_group(key, found, reviews.get(key))
    rejected: dict[str, str] = {}
    while True:
        if manual.apply(placed, hops):
            continue
        held = manual.held(placed)
        if _attach_by_axes(infos, keys, links, placed, hops, rejected, held):
            continue
        reserve = _reserve_pin(items, aligned, infos, placed, site, base_outline, held)
        reserve_notes = reserve.notes
        for key, found in reserve.tried.items():
            previous = tried.get(key)
            if previous is None or found.share > previous.share:
                tried[key] = found
        if reserve.key is None or reserve.pin is None:
            if not held:
                break
            for key in manual.release(placed):
                if key in core_pins and key not in placed:
                    pin_group(key, core_pins[key], reviews.get(key))
            continue
        pin_group(reserve.key, reserve.pin, reserve.review)
    base_label = infos[base_key].label
    for key in keys:
        if key in placed:
            continue
        found = tried.get(key)
        message = rejected.get(key) or reserve_notes.get(key)
        if message is None and found is not None:
            message = (
                f"по ядрам не совмещено с «{base_label}»: совпадение {found.share:.0%}, у другого "
                f"варианта {found.second_share:.0%} (нужно не меньше "
                f"{cad_site_cores.MIN_SHARE:.0%} и вдвое больше либо от "
                f"{cad_site_cores.RESERVE_SHARE:.0%} при отрыве в "
                f"{cad_site_cores.RESERVE_RATIO:g} раза; у листа с неверным масштабом ядра "
                "не совпадут), общих осей с поставленными зданиями нет"
            )
        elif message is None:
            message = (
                "нет общих осей с поставленными зданиями, монолитных стен и пилонов для "
                "совмещения по ядрам мало"
            )
        placed[key] = GroupPlacement(
            "none",
            (0.0, 0.0),
            (),
            None,
            message,
            key,
            0.0,
            None if found is None else round(found.share, 3),
        )
    return SiteResult(placed, manual.finish(placed))


def _attach_by_axes(
    infos: dict[str, _GroupInfo],
    keys: Sequence[str],
    links: dict[tuple[str, str], _SiteMatch],
    placed: dict[str, GroupPlacement],
    hops: dict[str, int],
    rejected: dict[str, str],
    held: frozenset[str] = frozenset(),
) -> bool:
    """Присоединение одного здания по осям к уже поставленным; некого присоединить - `False`.

    `held` - здания, ожидающие ручной привязки (ADR-0052): по осям они не присоединяются.

    Сначала к опорам, потом дальше по цепочке (ближайшая опора выигрывает); совпадение марок без
    номера секции принимается только без наложения этажей на одной отметке.
    """
    candidates = sorted(
        (
            (base, other, match)
            for (base, other), match in links.items()
            if base in placed and other not in placed and other not in held
        ),
        key=lambda row: (
            hops[row[0]],
            not row[2].prefixed,
            -len(row[2].labels),
            keys.index(row[1]),
            keys.index(row[0]),
        ),
    )
    for base, other, match in candidates:
        anchor_p = placed[base]
        sx, sy = cad_site_cores.transform_point(
            match.shift[0], match.shift[1], anchor_p.rotation_deg, 0.0, 0.0
        )
        offset = (anchor_p.offset_mm[0] + sx, anchor_p.offset_mm[1] + sy)
        if not match.prefixed:
            if not (infos[other].levels and infos[base].levels):
                rejected[other] = (
                    f"совпадение по осям {', '.join(match.labels)} без номера секции, а этажей "
                    "с отметкой для проверки наложения нет"
                )
                continue
            clash = next(
                (
                    k
                    for k, p in placed.items()
                    if p.rotation_deg == anchor_p.rotation_deg
                    and _clash(infos[k], p.offset_mm, infos[other], offset)
                ),
                None,
            )
            if clash is not None:
                rejected[other] = (
                    f"по осям {', '.join(match.labels)} здание ложится на "
                    f"«{infos[clash].label}» на той же отметке: совпадение марок случайное"
                )
                continue
        placed[other] = GroupPlacement(
            "axes",
            (round(offset[0], 3), round(offset[1], 3)),
            tuple(sorted(match.labels, key=_natural_key)),
            base,
            None,
            anchor_p.cluster,
            anchor_p.rotation_deg,
        )
        hops[other] = hops[base] + 1
        rejected.pop(other, None)
        return True
    return False


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
    """Поворот на `rotation` градусов вокруг начала системы и сдвиг: постановка по ядрам и поворот
    этажа по осям. К этажу применяется как `R(rotation) · p + (dx, dy)` поверх уже сделанного:
    итоговые `rotation_deg` и `offset_mm` остаются в формуле
    `R(rotation_deg) · p_вида + offset_mm`."""

    def point(x: float, y: float) -> Point:
        if rotation % QUARTER_DEG == 0.0:
            # Кратный 90 поворот точный: без остатка sin/cos в десятичных знаках.
            rx, ry = ((x, y), (-y, x), (-x, -y), (y, -x))[_quarters(rotation)]
            return rx + dx, ry + dy
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
    windows = (
        None
        if floor.windows is None
        else [window.model_copy(update={"shell": ints(window.shell)}) for window in floor.windows]
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
            "windows": windows,
            "levels": levels,
            "bbox": bbox,
            "offset_mm": (round(ox, 3), round(oy, 3)),
            "rotation_deg": round(math.fmod(floor.rotation_deg + rotation, 360.0), 3),
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
                site_pin_id=None if placement is None else placement.pin_id,
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
    # Самое новое задание конструкций вида любого статуса: по нему называется причина,
    # почему у нового прогона листа конструкций ещё нет.
    walls_latest: dict[tuple[str, int, int], Job] = {}
    for walls in await session.scalars(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_WALLS,
        )
        .order_by(Job.created_at.desc(), Job.id)
    ):
        page, view = walls.payload.get("page_index"), walls.payload.get("view")
        if type(page) is int and type(view) is int:
            wkey = (str(walls.payload.get("parent_job_id")), page, view)
            walls_latest.setdefault(wkey, walls)
            if walls.status == JobStatus.SUCCEEDED:
                walls_by_view.setdefault(wkey, walls)
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
    sheet_ids = {
        (row.revision_id, row.page_index): row.id
        for row in (
            await session.execute(
                select(Sheet.id, Sheet.revision_id, Sheet.page_index).where(
                    Sheet.revision_id.in_(list(revisions))
                )
            )
        ).all()
    }
    stamp_titles = await documents_service.sheet_titles(session, sheet_ids=list(sheet_ids.values()))
    # Паспорта листов (не отклонённые человеком): вид листа отсеивает разрезы и таблицы, корпус и
    # секция - подсказка при сведении групп одного корпуса.
    passports = {
        (row.revision_id, row.page_index): row
        for row in (
            await session.execute(
                select(
                    SheetPassport.revision_id,
                    SheetPassport.page_index,
                    SheetPassport.sheet_kind,
                    SheetPassport.building,
                    SheetPassport.section,
                    SheetPassport.elevation_m,
                    SheetPassport.level_from_ordinal,
                    SheetPassport.level_to_ordinal,
                ).where(
                    SheetPassport.project_id == project_id,
                    SheetPassport.revision_id.in_(list(revisions)),
                    SheetPassport.status != "rejected",
                )
            )
        ).all()
    }
    older_by_revision: dict[uuid.UUID, list[Job]] = {}
    for job, rid in ordered:
        older_by_revision.setdefault(rid, []).append(job)
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
            passport = passports.get((revision_id, page_index))
            for view in views:
                label = f"{document.display_name} · лист {page_index + 1}"
                if len(views) > 1:
                    label += f" · вид {view}"
                overrides = levels.get(
                    (revision_id, page_index, view), cad_construction_store.EMPTY_LEVELS
                )
                # Вид берётся из самого нового прогона, у которого есть успешные конструкции
                # (та же ревизия): конвертация и конструкции - согласованная пара.
                source, walls_key, note = _pick_run(
                    job,
                    older_by_revision.get(revision_id, []),
                    revision_id,
                    page_index,
                    view,
                    walls_by_view,
                    walls_latest,
                    label,
                )
                folder = cad_service.view_folder(page_index, view)
                sheets.append(
                    SheetRef(
                        job_id=source.id,
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
                        walls_key=walls_key,
                        scale_key=_parent_key(source, revision_id, f"{folder}/scale.json"),
                        checks_key=_parent_key(source, revision_id, f"{folder}/cad_checks.json"),
                        stamp_title=stamp_titles.get(sheet_id)
                        if (sheet_id := sheet_ids.get((revision_id, page_index))) is not None
                        else None,
                        passport_kind=None if passport is None else passport.sheet_kind,
                        passport_building=None if passport is None else _clean(passport.building),
                        passport_section=None if passport is None else _clean(passport.section),
                        passport_elevation_mm=_passport_mm(passport),
                        passport_floor_from=None
                        if passport is None
                        else passport.level_from_ordinal,
                        passport_floor_to=None if passport is None else passport.level_to_ordinal,
                        previous_run_note=note,
                    )
                )
    return sheets, [], project_slab


def _passport_mm(passport: Any) -> int | None:
    """Отметка из заголовка листа по паспорту, мм; нет паспорта или отметки - `None`."""
    value = None if passport is None else passport.elevation_m
    if not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(value * 1000)


def _walls_state(walls: Job | None) -> str:
    """Почему у нового прогона вида нет готовых конструкций."""
    if walls is None or walls.status == JobStatus.QUEUED:
        return "ещё не посчитаны"
    if walls.status == JobStatus.RUNNING:
        return "считаются"
    if walls.status == JobStatus.FAILED:
        return f"завершились ошибкой: {walls.error_code or 'без кода'}"
    if walls.status == JobStatus.CANCELLED:
        return "отменены"
    return "не читаются"


def _pick_run(
    head: Job,
    revision_jobs: Sequence[Job],
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    walls_by_view: dict[tuple[str, int, int], Job],
    walls_latest: dict[tuple[str, int, int], Job],
    label: str,
) -> tuple[Job, str | None, str | None]:
    """Прогон вида для сборки: самый новый с успешными конструкциями, иначе самый новый.

    Возвращает конвертацию-источник, ключ walls.json и предупреждение о прежнем результате.
    Прежний прогон ищется в той же ревизии: новая ревизия - другой чертёж, а не пересчёт.
    """
    head_key = _walls_key(
        walls_by_view.get((str(head.id), page_index, view)), revision_id, page_index, view
    )
    if head_key is not None:
        return head, head_key, None
    for older in revision_jobs:
        if older.id == head.id or older.created_at >= head.created_at:
            continue
        if view not in _view_numbers(older, page_index):
            continue
        key = _walls_key(
            walls_by_view.get((str(older.id), page_index, view)), revision_id, page_index, view
        )
        if key is None:
            continue
        state = _walls_state(walls_latest.get((str(head.id), page_index, view)))
        note = (
            f"{label}: конструкции нового прогона {state}, "
            f"показан прежний результат от {older.created_at:%d.%m.%Y}."
        )
        return older, key, note
    return head, None, None


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
    typical: TypicalPlan | None = None
    # Почему лист служебный (не план этажа): в стопку не идёт, но и не ошибка.
    service: str | None = None
    # Окна листа без высоты в плане (только при `include_walls`); высоты - на каждый запрос.
    windows: WindowSource | None = None
    # Этажи заголовка плана (cad_walls) и есть ли в заголовке отметки: без отметок отметку этажа
    # и типовые этажи даёт паспорт листа и схемы КР (`cad_project_levels`).
    title_floors: tuple[str, ...] = ()
    title_marked: bool = False


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
        sheet.stamp_title,
        sheet.passport_kind,
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
    invalid = _SheetFloor(
        None,
        (
            CadBuilding3dWarningRead(
                code="walls_invalid",
                message=f"{sheet.label}: walls.json вне контракта или без геометрии, "
                "лист пропущен.",
            ),
        ),
        NO_AXES,
    )
    try:
        document = WallsDocument.model_validate(raw)
        extras = WallsFloorExtras.model_validate(raw)
    except ValidationError:
        return invalid
    service = plan_problem(document, sheet.passport_kind)
    if service is not None:
        return _SheetFloor(None, (), NO_AXES, service=service)
    try:
        floor, floor_warnings = build_floor(
            sheet, document, extras, project_slab, include_walls=include_walls
        )
    except (ValidationError, ValueError):
        return invalid
    typical = typical_plan(document, sheet.label)
    title = document.heights.title
    if typical is None and title is not None and len(title.floors) > 1:
        floor_warnings.append(
            CadBuilding3dWarningRead(
                code="typical_floors_unplaced",
                message=f"{floor.label}: лист на несколько этажей, но отметок остальных этажей "
                "в заголовке нет - этаж показан один раз.",
            )
        )
    # Оси сводного листа не связывают здания: планы секций на нём разложены не как на объекте.
    summary = is_summary_sheet(sheet.stamp_title)
    axes = NO_AXES if frame is None or summary else axes_in_mm(raw, frame)
    cores = core_rings(document)
    windows = (
        window_source(
            document,
            extras,
            raw,
            frame,
            effective_levels(document.heights, sheet.overrides, project_slab),
        )
        if include_walls
        else None
    )
    cost = (
        1
        + (0 if windows is None else windows.points)
        + sum(len(ring) for ring in cores)
        + len(floor.outline)
        + sum(len(wall.shell) for wall in floor.walls or ())
        + sum(len(zone.shell) + sum(len(h) for h in zone.holes) for zone in floor.levels)
    )
    return _SheetFloor(
        floor,
        tuple(floor_warnings),
        axes,
        cost,
        cores,
        typical,
        windows=windows,
        title_floors=tuple(title.floors) if title is not None else (),
        title_marked=title is not None and bool(title.marks_mm),
    )


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
    """Этаж листа; если взят прежний прогон - с предупреждением `floor_previous_run`."""
    item = await _load_sheet_floor_cached(
        storage, sheet, project_slab, include_walls, gate, generation
    )
    if sheet.previous_run_note is None or item.floor is None:
        return item
    warning = CadBuilding3dWarningRead(code="floor_previous_run", message=sheet.previous_run_note)
    return dataclasses.replace(item, warnings=(*item.warnings, warning))


async def _load_sheet_floor_cached(
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
