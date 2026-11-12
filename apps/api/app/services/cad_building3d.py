"""Общий вид здания для 3D: этажи проекта (листы CAD) с отметками и контуром плиты.

Этаж — тройка (задание `cad_pdf_convert`, страница, вид) с последним успешным `cad_walls`.
Из `walls.json` берётся только контур плиты (или прямоугольник по стенам) и высоты; модель этажа
целиком (стены, двери, зоны) здесь не строится. Высоты — действующие значения листа, те же, что
в `cad_floor3d.build_floor3d` (`cad_constructions.effective_levels`).

Этажи делятся на здания по корпусу и секции из заголовка плана; этажи одного здания совмещаются
в плане по общим осям (`axes` в walls.json, pt -> мм по кадру вида): смещение уже применено к
контуру, клиент получает геометрию в системе эталонного этажа группы.

Порядок работы: сначала всё нужное из базы — последовательно (сессия не конкурентна), затем
`walls.json` листов читаются из хранилища параллельно с ограничением. Ошибка одного листа не
валит ответ: лист пропускается с предупреждением. В итоги обмера, calc и MEP вид не входит.
"""

from __future__ import annotations

import asyncio
import math
import re
import statistics
import uuid
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
    CadBuilding3dRead,
    CadBuilding3dWarningRead,
)
from app.contracts.cad_constructions import CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.domain import JobStatus, JobType
from app.models import Document, DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_construction_store, cad_views, cad_walls
from app.services.cad_constructions import ProjectSlab, effective_levels
from app.services.cad_floor_title import format_floor_title
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

MAX_OUTLINE_POINTS: Final = 200
READ_CONCURRENCY: Final = 6
# Для отрисовки, когда высота этажа или толщина плиты не определены (помечаются `*_known = false`).
DEFAULT_FLOOR_HEIGHT_MM: Final = 3000
DEFAULT_SLAB_THICKNESS_MM: Final = 200
# Допуск расхождения смещений по общим осям: больше - оси разных этажей «не сходятся».
AXIS_TOLERANCE_MM: Final = 150.0
GROUP_NONE_KEY: Final = "none"
GROUP_NONE_LABEL: Final = "Корпус не указан"
MESSAGE_AXES_OUTDATED: Final = "оси не распознаны: пересчитайте конструкции листа"
MESSAGE_AXES_EMPTY: Final = "оси на листе не распознаны"
MESSAGE_FRAME_MISSING: Final = "кадр вида не установлен"
MESSAGE_NO_REFERENCE: Final = "в группе нет этажа с осями в обоих направлениях"

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
) -> tuple[CadBuilding3dFloorRead, list[CadBuilding3dWarningRead]]:
    """Этаж по walls.json: высоты и контур плиты (или прямоугольник по стенам)."""
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
    rings = list(wall_rings)
    if extras.slab is not None:
        rings.append(extras.slab.shell)
    box = bbox_of(rings)
    outline: list[list[float]]
    source: str
    if extras.slab is not None and len(_open_ring(extras.slab.shell)) >= 3:
        outline, source = simplify_ring(extras.slab.shell), "slab"
    else:
        wall_box = bbox_of(wall_rings)
        if wall_box is None:
            raise ValueError("нет ни плиты, ни стен")
        outline, source = _rectangle(wall_box), "bbox"
    title = document.heights.title
    corps = _clean(title.corps) if title is not None else None
    section = _clean(title.section) if title is not None else None
    group_key, group_label = group_of(corps, section)
    floor = CadBuilding3dFloorRead(
        job_id=sheet.job_id,
        revision_id=sheet.revision_id,
        page_index=sheet.page_index,
        view=sheet.view,
        document_id=sheet.document_id,
        label=format_floor_title(document.heights.title, sheet.label),
        elevation_known=levels.elevation_mm is not None,
        base_z_mm=levels.elevation_mm if levels.elevation_mm is not None else 0,
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
    )
    return floor, warnings


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


@dataclass(frozen=True, slots=True)
class BuiltFloor:
    floor: CadBuilding3dFloorRead
    order: tuple[float, float, int, int]
    axes: FloorAxes


def _match_orient(
    reference: dict[str, float], other: dict[str, float], name: str
) -> tuple[float, list[str]] | str:
    """Смещение по одному направлению (медиана) и общие подписи, либо причина отказа."""
    common = sorted(reference.keys() & other.keys(), key=_natural_key)
    if not common:
        return f"нет общих {name} осей с эталонным этажом"
    diffs = {label: reference[label] - other[label] for label in common}
    median = statistics.median(diffs.values())
    if len(common) >= 2:
        bad = [label for label in common if abs(diffs[label] - median) > AXIS_TOLERANCE_MM]
        if bad:
            return f"{name} оси расходятся с эталоном: {', '.join(bad)}"
    return median, common


def _shifted(floor: CadBuilding3dFloorRead, dx: float, dy: float) -> CadBuilding3dFloorRead:
    box = floor.bbox
    return floor.model_copy(
        update={
            "outline": [[x + dx, y + dy] for x, y in floor.outline],
            "bbox": None if box is None else [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy],
            "offset_mm": (round(dx, 3), round(dy, 3)),
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


def _shared_axes(first: BuiltFloor, second: BuiltFloor) -> int:
    """Число общих подписей осей двух этажей (вертикальные и горизонтальные по отдельности)."""
    return len(first.axes.vertical.keys() & second.axes.vertical.keys()) + len(
        first.axes.horizontal.keys() & second.axes.horizontal.keys()
    )


def align_floors(items: Sequence[BuiltFloor]) -> list[CadBuilding3dFloorRead]:
    """Совмещение этажей каждой группы с эталоном; порядок результата - как у входа."""
    result: list[CadBuilding3dFloorRead | None] = [None] * len(items)
    groups: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        groups.setdefault(item.floor.group_key, []).append(index)
    for indexes in groups.values():
        usable = [i for i in indexes if items[i].axes.usable]
        # Эталон - этаж с наибольшим числом общих подписей осей с остальными этажами группы
        # (подземный этаж с другой сеткой эталоном не становится); при равенстве - самый нижний.
        ref_index = (
            min(
                usable,
                key=lambda i: (
                    -sum(_shared_axes(items[i], items[j]) for j in usable if j != i),
                    not items[i].floor.elevation_known,
                    items[i].floor.base_z_mm,
                    items[i].order,
                ),
            )
            if usable
            else None
        )
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
    return shifted.model_copy(
        update={
            "alignment": "axes",
            "alignment_axes": [*along_x[1], *along_y[1]],
            "alignment_message": None,
        }
    )


def build_groups(floors: Sequence[CadBuilding3dFloorRead]) -> list[CadBuilding3dGroupRead]:
    """Здания для переключателя: по подписи в естественном порядке."""
    counts: dict[str, tuple[str, int, int]] = {}
    for floor in floors:
        label, total, aligned = counts.get(floor.group_key, (floor.group_label, 0, 0))
        counts[floor.group_key] = (label, total + 1, aligned + (floor.alignment != "none"))
    rows = sorted(counts.items(), key=lambda row: (_natural_key(row[1][0]), row[0]))
    return [
        CadBuilding3dGroupRead(key=key, label=label, floor_count=total, aligned_count=aligned)
        for key, (label, total, aligned) in rows
    ]


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
                overrides = await cad_construction_store.load_levels(
                    session, revision_id=revision_id, page_index=page_index, view=view
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
) -> CadFrameRead:
    """Кадр вида листа; не читается или не установлен - неподтверждённый кадр с причиной."""

    def unconfirmed(reason: str) -> CadFrameRead:
        return CadFrameRead(
            confirmed=False, reason=reason, units=None, origin_pt=None, mm_per_pdf_point=None
        )

    if sheet.scale_key is None or sheet.checks_key is None:
        return unconfirmed("DXF в этой попытке нет: сравнивать с PDF нечего.")
    async with gate:
        try:
            scale = cad_views.scale_from(await cad_views.read_json(storage, sheet.scale_key))
            checks = await cad_views.read_json(storage, sheet.checks_key)
        except (
            ObjectNotFoundError,
            StorageUnavailableError,
            cad_views.ArtifactTooLargeError,
            ValueError,
        ):
            return unconfirmed("масштаб или проверки вида не читаются")
    return cad_views.frame_from(scale, checks)


async def build_building3d(
    session: AsyncSession, storage: ObjectStorage, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CadBuilding3dRead:
    sheets, warnings, project_slab = await collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    gate = asyncio.Semaphore(READ_CONCURRENCY)
    loaded = await asyncio.gather(*(_read_walls(storage, sheet, gate) for sheet in sheets))
    # Кадр нужен только листам, у которых в walls.json есть блок осей.
    needs_frame = [
        index
        for index, (raw, problem) in enumerate(loaded)
        if problem is None and isinstance(raw, dict) and isinstance(raw.get("axes"), dict)
    ]
    frames = dict(
        zip(
            needs_frame,
            await asyncio.gather(*(_read_frame(storage, sheets[i], gate) for i in needs_frame)),
            strict=True,
        )
    )
    built: list[BuiltFloor] = []
    for index, (sheet, (raw, problem)) in enumerate(zip(sheets, loaded, strict=True)):
        if problem is not None:
            warnings.append(problem)
            continue
        try:
            document = WallsDocument.model_validate(raw)
            extras = WallsFloorExtras.model_validate(raw)
            floor, floor_warnings = build_floor(sheet, document, extras, project_slab)
        except (ValidationError, ValueError):
            warnings.append(
                CadBuilding3dWarningRead(
                    code="walls_invalid",
                    message=f"{sheet.label}: walls.json вне контракта или без геометрии, "
                    "лист пропущен.",
                )
            )
            continue
        warnings.extend(floor_warnings)
        frame = frames.get(index)
        axes = NO_AXES if frame is None else axes_in_mm(raw, frame)
        built.append(BuiltFloor(floor, sheet.order, axes))
    aligned = align_floors(built)
    floors = sort_floors([(f, item.order) for f, item in zip(aligned, built, strict=True)])
    return CadBuilding3dRead(
        units="mm", floors=floors, groups=build_groups(floors), warnings=warnings
    )
