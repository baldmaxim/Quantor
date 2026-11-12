"""Ведомость отделки помещений листа CAD (ADR-0042): количества по слоям шаблонов.

Количества считаются при чтении и нигде не хранятся: площади зон приходят от `cad_zones`
(геометрия страницы и калибровка листа), высота стен - из шаблона либо из уровней листа
(`cad_constructions.effective_levels`). Модель нигде не участвует. Ведомость - рабочая таблица
пилота, не ВОР Quantor и не смета; стоимости нет. Неопределённое - `None`, а не 0.

Шаг 2 ADR-0042 (п. 6): рёбра зоны привязываются к конструкциям листа (`cad_finish_edges`) -
стены считаются по основаниям (монолит, кладка, ГКЛ), двери вычитаются, считаются откосы. Нет
результата конструкций, кадра листа или контур зоны непригоден - поведение шага 1 (периметр x
высота) и предупреждение `edges_unlinked`. Окон в результате конструкций нет: при привязке
ведомость всегда несёт `windows_not_detected`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import CadConstructionProps, WallsDocument
from app.contracts.cad_finishes import (
    CadFinishAreaByBaseRead,
    CadFinishLayer,
    CadFinishLayerRead,
    CadFinishRoomTypeRead,
    CadFinishSheetRead,
    CadFinishTemplateRead,
    CadFinishTotalRead,
    CadFinishWallsBreakdownRead,
    CadFinishWarningRead,
    CadFinishZoneRead,
    FinishSurface,
    FinishTemplateSource,
    FinishWallHeightSource,
    FinishWarningCode,
)
from app.contracts.cad_floor3d import WallsFloorExtras
from app.contracts.cad_room_types import ROOM_TYPE_VALUES, CadRoomType
from app.contracts.cad_zones import CadZoneRead
from app.domain import JobStatus, JobType
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_construction_store, cad_floor3d, cad_views, cad_walls, cad_zones
from app.services.cad_constructions import effective_levels, effective_material
from app.services.cad_finish_edges import (
    BASES,
    Base,
    EdgeConstruction,
    EdgeIndex,
    EdgeOpening,
    Point,
    ZoneEdges,
    construction_base,
)
from app.services.cad_walls_version import walls_outdated
from app.services.cad_zones import ROOM_KINDS
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

MM_PER_M: Final = 1000.0
SURFACES: Final[tuple[FinishSurface, ...]] = ("floor", "walls", "ceiling")


# --------------------------------------------------------------------------- уровни листа


def _views_with_dxf(parent: Job, page_index: int) -> list[int]:
    """Виды страницы в текущем итоге родителя, у которых есть DXF (как в 3D-виде этажа)."""
    views: list[int] = []
    for page in cad_service.current_result(parent).get("pages", []):
        if not isinstance(page, dict) or page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            view = row.get("view") if isinstance(row, dict) else None
            if type(view) is int and cad_walls.view_has_dxf(parent, page_index, view) is not None:
                views.append(view)
    return sorted(views)


@dataclass(frozen=True, slots=True)
class _SheetWalls:
    document: WallsDocument
    # `None` - дополнение 3D-вида не читается по контракту: привязки рёбер нет.
    extras: WallsFloorExtras | None


async def _read_walls(
    storage: ObjectStorage, job: Job, revision_id: uuid.UUID, page_index: int, view: int
) -> _SheetWalls | None:
    """walls.json успешного задания вида; не читается или вне контракта - `None`."""
    attempt = cad_service.result_of(job).get("attempt")
    name = f"{cad_service.view_folder(page_index, view)}/{cad_walls.WALLS_JSON}"
    artifact = cad_service.find_artifact(job, name)
    if type(attempt) is not int or artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    if artifact.get("key") != key:
        return None
    try:
        raw = await cad_views.read_json(storage, key)
        document = WallsDocument.model_validate(raw)
    except (
        ObjectNotFoundError,
        StorageUnavailableError,
        cad_views.ArtifactTooLargeError,
        ValidationError,
        ValueError,
    ):
        return None
    try:
        extras: WallsFloorExtras | None = WallsFloorExtras.model_validate(raw)
    except ValidationError:
        extras = None
    return _SheetWalls(document, extras)


async def _artifact_json(
    storage: ObjectStorage, parent: Job, revision_id: uuid.UUID, attempt: int, name: str
) -> Any:
    """JSON-артефакт попытки родителя; нет или не читается - `None`."""
    artifact = cad_service.find_artifact(parent, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, parent.id, attempt, name)
    if artifact.get("key") != key:
        return None
    try:
        return await cad_views.read_json(storage, key)
    except (
        ObjectNotFoundError,
        StorageUnavailableError,
        cad_views.ArtifactTooLargeError,
        ValueError,
    ):
        return None


@dataclass(frozen=True, slots=True)
class FinishFrame:
    """Кадр листа: перевод нормализованных точек зоны в мм DXF (как в 3D-виде этажа)."""

    page_width_pt: float
    page_height_pt: float
    origin_pt: Point
    mm_per_pdf_point: float


@dataclass(frozen=True, slots=True)
class FinishWallsInput:
    """Результат конструкций листа для привязки рёбер зон."""

    constructions: Sequence[EdgeConstruction]
    openings: Sequence[EdgeOpening]
    frame: FinishFrame
    # Действующая высота двери листа (уровни); `None` - не определена.
    door_height_mm: int | None


@dataclass(frozen=True, slots=True)
class FinishSheetContext:
    """Что нужно ведомости от листа: высота стен из уровней и привязка рёбер (если возможна)."""

    wall_height_mm: int | None
    walls: FinishWallsInput | None


NO_SHEET = FinishSheetContext(None, None)


async def _sheet_frame(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> FinishFrame | None:
    """Кадр вида; не подтверждён или нет геометрии страницы - `None`."""
    attempt = cad_service.current_result(parent).get("attempt")
    if type(attempt) is not int:
        return None
    folder = cad_service.view_folder(page_index, view)
    scale = cad_views.scale_from(
        await _artifact_json(storage, parent, revision_id, attempt, f"{folder}/scale.json")
    )
    checks = await _artifact_json(
        storage, parent, revision_id, attempt, f"{folder}/cad_checks.json"
    )
    frame = cad_views.frame_from(scale, checks)
    page = (
        await cad_zones.page_scales(session, revision_id=revision_id, page_indexes={page_index})
    ).get(page_index)
    geometry = None if page is None else page.geometry
    if (
        not frame.confirmed
        or geometry is None
        or frame.origin_pt is None
        or frame.mm_per_pdf_point is None
    ):
        return None
    return FinishFrame(
        float(geometry.display_width_pt),
        float(geometry.display_height_pt),
        frame.origin_pt,
        frame.mm_per_pdf_point,
    )


def _points(ring: Sequence[Sequence[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in ring]


def _edge_input(
    sheet: _SheetWalls,
    props: Mapping[str, tuple[CadConstructionProps, bool]],
    current_generator: str | None,
) -> tuple[list[EdgeConstruction], list[EdgeOpening]] | None:
    """Стены с основаниями и проёмы с перемычками; `None` - файл устарел (нет плиты и перемычек
    либо построен генератором старше закреплённого)."""
    extras = sheet.extras
    if extras is None or walls_outdated(
        sheet.document.generator, extras.has_slab_key, current_generator
    ):
        return None
    constructions: list[EdgeConstruction] = []
    base_by_id: dict[str, Base] = {}
    for item in [*sheet.document.constructions, *sheet.document.frame_partitions]:
        material = effective_material(item, props.get(item.id, (CadConstructionProps(), False))[0])
        base = construction_base(item.kind, material.value)
        if base is None:
            continue
        base_by_id[item.id] = base
        constructions.append(
            EdgeConstruction(
                item.id,
                base,
                [_points(item.polygon.shell), *(_points(hole) for hole in item.polygon.holes)],
            )
        )
    lintel_by_id = {item.id: item.lintel for item in extras.openings}
    openings: list[EdgeOpening] = []
    for opening in sheet.document.openings:
        lintel = lintel_by_id.get(opening.id)
        if lintel is None or len(lintel) < 3:
            continue
        host = base_by_id.get(opening.host_id) if opening.host_id is not None else None
        openings.append(
            EdgeOpening(
                opening.id,
                opening.kind,
                _points(lintel),
                opening.width_mm,
                opening.thickness_mm,
                host,
            )
        )
    return constructions, openings


async def load_finish_context(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    current_generator: str | None = None,
) -> FinishSheetContext:
    """Высота стен листа и привязка рёбер: тот же путь, что у 3D-вида этажа.

    Берётся последнее успешное преобразование ревизии, первый его вид страницы с готовыми
    конструкциями; уровни - `effective_levels` (переопределения человека, уровень проекта,
    walls.json). Нет результата конструкций - `NO_SHEET`. Привязка рёбер (`walls`) есть, только
    если результат новый (с перемычками) и кадр вида подтверждён.
    """
    parents = await session.scalars(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_PDF_CONVERT,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["revision_id"].astext == str(revision_id),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    for parent in parents:
        for view in _views_with_dxf(parent, page_index):
            jobs = await cad_walls.walls_jobs_of_view(
                session, parent=parent, page_index=page_index, view=view
            )
            ready = next((job for job in jobs if job.status is JobStatus.SUCCEEDED), None)
            if ready is None:
                continue
            sheet = await _read_walls(storage, ready, revision_id, page_index, view)
            if sheet is None:
                continue
            overrides = await cad_construction_store.load_levels(
                session, revision_id=revision_id, page_index=page_index, view=view
            )
            project_slab = await cad_construction_store.load_project_slab(
                session, project_id=project_id
            )
            levels = effective_levels(sheet.document.heights, overrides, project_slab)
            walls: FinishWallsInput | None = None
            frame = await _sheet_frame(
                session,
                storage,
                parent=parent,
                revision_id=revision_id,
                page_index=page_index,
                view=view,
            )
            if frame is not None:
                props = await cad_construction_store.load_props(
                    session, revision_id=revision_id, page_index=page_index, view=view
                )
                linked = _edge_input(sheet, props, current_generator)
                if linked is not None:
                    walls = FinishWallsInput(
                        linked[0], linked[1], frame, levels.door_height.value_mm
                    )
            return FinishSheetContext(levels.wall_height_mm, walls)
    return NO_SHEET


# --------------------------------------------------------------------------- расчёт


def _wall_height(
    template: CadFinishTemplateRead | None, levels_height_mm: int | None
) -> tuple[float | None, FinishWallHeightSource | None]:
    """Высота стен под отделку: из шаблона, иначе уровни минус толщина слоёв пола шаблона."""
    if template is not None and template.wall_height_mm is not None:
        return float(template.wall_height_mm), "template"
    if levels_height_mm is None:
        return None, None
    floor_mm = (
        sum(layer.thickness_mm or 0.0 for layer in template.floor_layers)
        if template is not None
        else 0.0
    )
    height = levels_height_mm - floor_mm
    if height <= 0:
        return None, None
    return height, "levels"


def _material_qty(area_m2: float | None, layer: CadFinishLayer) -> float | None:
    """Площадь x расход (x толщина, если расход на мм) x число слоёв; без расхода - `None`."""
    if area_m2 is None or layer.consumption is None:
        return None
    quantity = area_m2 * layer.consumption
    if layer.consumption_per_mm and layer.thickness_mm is not None:
        quantity *= layer.thickness_mm
    return quantity * layer.coats


def _sum_known(values: Sequence[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _room_type_row(code: CadRoomType, group: Sequence[CadFinishZoneRead]) -> CadFinishRoomTypeRead:
    """Итог по типу помещения; зона с любой неопределённой площадью в сумму не вошла."""
    unknown = sum(
        1
        for row in group
        if row.floor_area_m2 is None or row.wall_area_m2 is None or row.ceiling_area_m2 is None
    )
    return CadFinishRoomTypeRead(
        room_type=code,
        zone_count=len(group),
        floor_area_m2=_sum_known([row.floor_area_m2 for row in group]),
        wall_area_m2=_sum_known([row.wall_area_m2 for row in group]),
        ceiling_area_m2=_sum_known([row.ceiling_area_m2 for row in group]),
        unknown_zone_count=unknown,
        incomplete=unknown > 0,
    )


@dataclass(slots=True)
class _Total:
    areas: list[float | None] = field(default_factory=list)
    quantities: list[float | None] = field(default_factory=list)
    zone_ids: set[uuid.UUID] = field(default_factory=set)
    # Зоны, у которых площадь или количество не определены: в сумму они не вошли.
    unknown_zone_ids: set[uuid.UUID] = field(default_factory=set)


def _template_for(
    zone: CadZoneRead,
    by_id: dict[uuid.UUID, CadFinishTemplateRead],
    by_type: dict[str, CadFinishTemplateRead],
) -> tuple[CadFinishTemplateRead | None, FinishTemplateSource | None]:
    if zone.finish_template_id is not None and zone.finish_template_id in by_id:
        return by_id[zone.finish_template_id], "explicit"
    if zone.room_type is not None and zone.room_type in by_type:
        return by_type[zone.room_type], "by_type"
    return None, None


@dataclass(slots=True)
class _WallsCalc:
    """Стены зоны по привязке рёбер: длины (м) и площади (м2), раздельно по основаниям."""

    base_m: dict[Base, float]
    door_m: float
    gap_m: float
    open_m: float
    has_gap: bool
    door_height_missing: bool
    # Площади известны только при известной высоте стен.
    base_area: dict[Base, float] | None
    # Надпроёмные части и откосы - по основанию стены-хозяина проёма (`None` - хозяин не найден).
    over_by_host: dict[Base | None, float] | None
    reveal_m: float | None
    # `None` - откосы не определены: у двери нет высоты или у проёма нет толщины стены.
    reveal_by_host: dict[Base | None, float] | None

    @property
    def wall_area(self) -> float | None:
        if self.base_area is None or self.over_by_host is None:
            return None
        return sum(self.base_area.values()) + sum(self.over_by_host.values())


def _door_height(
    opening: EdgeOpening,
    door_zones: Sequence[cad_floor3d.DoorZoneMm],
    default_mm: int | None,
) -> int | None:
    """Высота двери: зона двери человека рядом с перемычкой, иначе высота двери листа."""
    # Допуск и выбор ближайшей зоны - те же, что у перемычек в 3D-виде этажа.
    zone_height = cad_floor3d._zone_height_at(cad_floor3d.ring_centroid(opening.lintel), door_zones)
    return zone_height if zone_height is not None else default_mm


def _calc_walls(
    edges: ZoneEdges,
    height_mm: float | None,
    openings: Mapping[str, EdgeOpening],
    door_heights: Mapping[str, int | None],
) -> _WallsCalc:
    base_m = {base: edges.base_mm[base] / MM_PER_M for base in BASES}
    gap_mm = sum(edges.gap_mm.values())
    has_gap = gap_mm > 0
    door_m = 0.0
    door_height_missing = False
    over: dict[Base | None, float] = {}
    reveal_m = 0.0
    reveal_area: dict[Base | None, float] = {}
    reveal_defined = True
    for opening_id, span_mm in edges.door_mm.items():
        opening = openings[opening_id]
        door_height = door_heights[opening_id]
        if door_height is None:
            # Высота двери неизвестна: участок отделке не подлежит, как проём без двери.
            door_height_missing = True
            reveal_defined = False
            gap_mm += span_mm
            continue
        door_m += span_mm / MM_PER_M
        if height_mm is not None:
            over[opening.host_base] = over.get(opening.host_base, 0.0) + (
                span_mm / MM_PER_M * max(height_mm - door_height, 0.0) / MM_PER_M
            )
        length_m = (2.0 * door_height + min(span_mm, opening.width_mm)) / MM_PER_M
        reveal_m += length_m
        if opening.thickness_mm is None:
            reveal_defined = False
        else:
            reveal_area[opening.host_base] = reveal_area.get(opening.host_base, 0.0) + (
                length_m * (opening.thickness_mm / 2.0) / MM_PER_M
            )
    return _WallsCalc(
        base_m=base_m,
        door_m=door_m,
        gap_m=gap_mm / MM_PER_M,
        open_m=edges.open_mm / MM_PER_M,
        has_gap=has_gap,
        door_height_missing=door_height_missing,
        base_area=(
            None
            if height_mm is None
            else {base: base_m[base] * height_mm / MM_PER_M for base in BASES}
        ),
        over_by_host=None if height_mm is None else over,
        reveal_m=reveal_m if not door_height_missing else None,
        reveal_by_host=reveal_area if reveal_defined else None,
    )


def _breakdown(calc: _WallsCalc | None) -> CadFinishWallsBreakdownRead:
    if calc is None:
        return CadFinishWallsBreakdownRead(
            linked=False,
            monolith_m=None,
            masonry_m=None,
            gkl_m=None,
            door_m=None,
            gap_m=None,
            open_m=None,
            area_by_base=CadFinishAreaByBaseRead(monolith=None, masonry=None, gkl=None),
            door_over_area_m2=None,
            reveal_m=None,
            reveal_area_m2=None,
        )
    areas = calc.base_area
    return CadFinishWallsBreakdownRead(
        linked=True,
        monolith_m=calc.base_m["monolith"],
        masonry_m=calc.base_m["masonry"],
        gkl_m=calc.base_m["gkl"],
        door_m=calc.door_m,
        gap_m=calc.gap_m,
        open_m=calc.open_m,
        area_by_base=CadFinishAreaByBaseRead(
            monolith=None if areas is None else areas["monolith"],
            masonry=None if areas is None else areas["masonry"],
            gkl=None if areas is None else areas["gkl"],
        ),
        door_over_area_m2=None if calc.over_by_host is None else sum(calc.over_by_host.values()),
        reveal_m=calc.reveal_m,
        reveal_area_m2=None if calc.reveal_by_host is None else sum(calc.reveal_by_host.values()),
    )


def _wall_layer_area(
    calc: _WallsCalc | None,
    layer: CadFinishLayer,
    *,
    include_reveals: bool,
    plain_area: float | None,
) -> float | None:
    """Площадь слоя стен: участки его оснований и откосы шаблона; без привязки - периметр x высота.

    Без привязки основание неизвестно: слой, ограниченный основаниями, не определён.
    """
    if calc is None:
        return plain_area if layer.bases is None else None
    if calc.base_area is None or calc.over_by_host is None:
        return None
    allowed = set(BASES) if layer.bases is None else set(layer.bases)
    area = sum(calc.base_area[base] for base in BASES if base in allowed)
    hosts = [host for host in calc.over_by_host if layer.bases is None or host in allowed]
    area += sum(calc.over_by_host[host] for host in hosts)
    if include_reveals:
        if calc.reveal_by_host is None:
            return None
        area += sum(
            value
            for host, value in calc.reveal_by_host.items()
            if layer.bases is None or host in allowed
        )
    return area


def _zone_ring_mm(zone: CadZoneRead, frame: FinishFrame) -> list[Point] | None:
    """Контур зоны в мм DXF по кадру листа; непригодный контур - `None`."""
    if zone.calibration_missing or zone.geometry_issue is not None:
        return None
    mapped = cad_floor3d.room_zones_to_mm(
        [cad_floor3d.RoomZoneNormalized(zone.kind, [list(point) for point in zone.points])],
        page_width_pt=frame.page_width_pt,
        page_height_pt=frame.page_height_pt,
        origin_pt=frame.origin_pt,
        mm_per_pdf_point=frame.mm_per_pdf_point,
    )
    return mapped[0].shell if mapped else None


def build_finish_sheet(
    *,
    revision_id: uuid.UUID,
    page_index: int,
    zones: Sequence[CadZoneRead],
    templates: Sequence[CadFinishTemplateRead],
    levels_wall_height_mm: int | None,
    walls: FinishWallsInput | None = None,
) -> CadFinishSheetRead:
    """Ведомость по зонам листа; двери и машино-места не выводятся.

    `walls` - результат конструкций с кадром листа: стены считаются по рёбрам зон. Без него -
    периметр x высота и предупреждение `edges_unlinked`.
    """
    by_id = {template.id: template for template in templates}
    by_type: dict[str, CadFinishTemplateRead] = {}
    for item in templates:
        for code in item.room_types:
            by_type.setdefault(code, item)

    rooms = [zone for zone in zones if zone.kind in ROOM_KINDS]
    rows: list[CadFinishZoneRead] = []
    totals: dict[tuple[FinishSurface, str, str | None, str | None], _Total] = {}
    kinds: dict[CadRoomType, list[CadFinishZoneRead]] = {}
    no_calibration: list[uuid.UUID] = []
    geometry_issue: list[uuid.UUID] = []
    no_height: list[uuid.UUID] = []
    no_template: list[uuid.UUID] = []
    gap_unknown: list[uuid.UUID] = []
    no_door_height: list[uuid.UUID] = []
    linked_ids: list[uuid.UUID] = []
    unlinked_ids: list[uuid.UUID] = []

    index: EdgeIndex | None = None
    openings: dict[str, EdgeOpening] = {}
    door_zones: list[cad_floor3d.DoorZoneMm] = []
    door_heights: dict[str, int | None] = {}
    if walls is not None and rooms:
        index = EdgeIndex(walls.constructions, walls.openings)
        openings = {opening.id: opening for opening in walls.openings}
        door_zones = cad_floor3d.door_zones_to_mm(
            [
                cad_floor3d.DoorZoneNormalized(
                    [list(point) for point in zone.points], zone.door_height_mm
                )
                for zone in zones
                if zone.kind == "door" and zone.door_height_mm is not None
            ],
            page_width_pt=walls.frame.page_width_pt,
            page_height_pt=walls.frame.page_height_pt,
            origin_pt=walls.frame.origin_pt,
            mm_per_pdf_point=walls.frame.mm_per_pdf_point,
        )

    for zone in rooms:
        template, source = _template_for(zone, by_id, by_type)
        height, height_source = _wall_height(template, levels_wall_height_mm)
        area = zone.area_m2
        calc: _WallsCalc | None = None
        ring = _zone_ring_mm(zone, walls.frame) if walls is not None and index is not None else None
        if walls is not None and index is not None and ring is not None:
            edges = index.link_ring(ring)
            for opening_id in edges.door_mm:
                if opening_id not in door_heights:
                    door_heights[opening_id] = _door_height(
                        openings[opening_id], door_zones, walls.door_height_mm
                    )
            calc = _calc_walls(edges, height, openings, door_heights)
        if calc is not None:
            wall_area = calc.wall_area
            linked_ids.append(zone.id)
            if calc.has_gap:
                gap_unknown.append(zone.id)
            if calc.door_height_missing:
                no_door_height.append(zone.id)
        else:
            unlinked_ids.append(zone.id)
            wall_area = (
                zone.perimeter_m * height / MM_PER_M
                if zone.perimeter_m is not None and height is not None
                else None
            )
        surface_area: dict[FinishSurface, float | None] = {
            "floor": area,
            "walls": wall_area,
            "ceiling": area,
        }
        layers: list[CadFinishLayerRead] = []
        if template is not None:
            by_surface: dict[FinishSurface, list[CadFinishLayer]] = {
                "floor": template.floor_layers,
                "walls": template.wall_layers,
                "ceiling": template.ceiling_layers,
            }
            for surface in SURFACES:
                for layer in by_surface[surface]:
                    layer_area = (
                        _wall_layer_area(
                            calc,
                            layer,
                            include_reveals=template.walls_include_reveals,
                            plain_area=wall_area,
                        )
                        if surface == "walls"
                        else surface_area[surface]
                    )
                    quantity = _material_qty(layer_area, layer)
                    unit = layer.consumption_unit if layer.consumption is not None else None
                    layers.append(
                        CadFinishLayerRead(
                            surface=surface,
                            work=layer.work,
                            material=layer.material,
                            coats=layer.coats,
                            thickness_mm=layer.thickness_mm,
                            bases=layer.bases,
                            area_m2=layer_area,
                            material_qty=quantity,
                            material_unit=unit,
                        )
                    )
                    total = totals.setdefault((surface, layer.work, layer.material, unit), _Total())
                    total.areas.append(layer_area)
                    total.quantities.append(quantity)
                    total.zone_ids.add(zone.id)
                    if layer_area is None or quantity is None:
                        total.unknown_zone_ids.add(zone.id)
        row = CadFinishZoneRead(
            zone_id=zone.id,
            name=zone.name,
            apartment_no=zone.apartment_no,
            room_mark=zone.room_mark,
            kind=zone.kind,
            room_type=zone.room_type,
            template_id=None if template is None else template.id,
            template_source=source,
            floor_area_m2=area,
            ceiling_area_m2=area,
            perimeter_m=zone.perimeter_m,
            wall_height_mm=height,
            wall_height_source=height_source,
            wall_area_m2=wall_area,
            walls_breakdown=_breakdown(calc),
            layers=layers,
        )
        rows.append(row)
        if zone.room_type is not None:
            kinds.setdefault(zone.room_type, []).append(row)
        if zone.calibration_missing:
            no_calibration.append(zone.id)
        elif zone.geometry_issue is not None:
            geometry_issue.append(zone.id)
        if height is None:
            no_height.append(zone.id)
        if template is None:
            no_template.append(zone.id)

    surface_order = {surface: index for index, surface in enumerate(SURFACES)}
    total_rows = [
        CadFinishTotalRead(
            surface=surface,
            work=work,
            material=material,
            material_unit=unit,
            area_m2=_sum_known(total.areas),
            material_qty=_sum_known(total.quantities),
            zone_count=len(total.zone_ids),
            unknown_zone_count=len(total.unknown_zone_ids),
            incomplete=bool(total.unknown_zone_ids),
        )
        for (surface, work, material, unit), total in sorted(
            totals.items(),
            key=lambda item: (
                surface_order[item[0][0]],
                item[0][1],
                item[0][2] or "",
                item[0][3] or "",
            ),
        )
    ]
    type_order = {code: position for position, code in enumerate(ROOM_TYPE_VALUES)}
    by_room_type = [
        _room_type_row(code, group)
        for code, group in sorted(kinds.items(), key=lambda item: type_order[item[0]])
    ]

    candidates: list[tuple[FinishWarningCode, list[uuid.UUID]]] = [
        ("calibration_missing", no_calibration),
        ("geometry_issue", geometry_issue),
        ("wall_height_missing", no_height),
        ("no_template", no_template),
        ("gap_unknown_height", gap_unknown),
        ("door_height_missing", no_door_height),
        # В результате конструкций окон нет: наружные стены считаются без вычета окон.
        ("windows_not_detected", linked_ids),
    ]
    warnings = [CadFinishWarningRead(code=code, zone_ids=ids) for code, ids in candidates if ids]
    # Без привязки рёбер (нет конструкций или кадра листа) предупреждение идёт всегда, в том числе
    # без зон; при привязке - только по зонам, чей контур привязать не удалось.
    if walls is None or unlinked_ids:
        warnings.append(CadFinishWarningRead(code="edges_unlinked", zone_ids=unlinked_ids))
    return CadFinishSheetRead(
        revision_id=revision_id,
        page_index=page_index,
        zones=rows,
        totals=total_rows,
        by_room_type=by_room_type,
        warnings=warnings,
    )
