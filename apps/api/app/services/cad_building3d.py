"""Общий вид здания для 3D: этажи проекта (листы CAD) с отметками и контуром плиты.

Этаж — тройка (задание `cad_pdf_convert`, страница, вид) с последним успешным `cad_walls`.
Из `walls.json` берётся только контур плиты (или прямоугольник по стенам) и высоты; модель этажа
целиком (стены, двери, зоны) здесь не строится. Высоты — действующие значения листа, те же, что
в `cad_floor3d.build_floor3d` (`cad_constructions.effective_levels`).

Порядок работы: сначала всё нужное из базы — последовательно (сессия не конкурентна), затем
`walls.json` листов читаются из хранилища параллельно с ограничением. Ошибка одного листа не
валит ответ: лист пропускается с предупреждением. В итоги обмера, calc и MEP вид не входит.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_building3d import (
    CadBuilding3dFloorRead,
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


async def build_building3d(
    session: AsyncSession, storage: ObjectStorage, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CadBuilding3dRead:
    sheets, warnings, project_slab = await collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    gate = asyncio.Semaphore(READ_CONCURRENCY)
    loaded = await asyncio.gather(*(_read_walls(storage, sheet, gate) for sheet in sheets))
    built: list[tuple[CadBuilding3dFloorRead, tuple[float, float, int, int]]] = []
    for sheet, (raw, problem) in zip(sheets, loaded, strict=True):
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
        built.append((floor, sheet.order))
    return CadBuilding3dRead(units="mm", floors=sort_floors(built), warnings=warnings)
