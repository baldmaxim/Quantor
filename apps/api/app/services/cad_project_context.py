"""Сборка полного проектного контекста CAD (`quantor.cad_project_context.v1`).

Объединяет в один снимок:
- координационную сетку осей и этажей объекта (`building_mm`): из действующего выпуска базы
  (`coordination.json`), либо «на лету» из совмещённых этажей `cad_building3d` тем же
  `tender_base_coordination.build_coordination`;
- группы зданий (`placement`, `site_offset_mm`, `site_rotation_deg`) и положения видов/этажей
  (`offset_mm`, `rotation_deg`, `frame`) для сквозного перевода
  `px (plan.png) -> pt (PDF) -> view_mm (DXF) -> building_mm (3D / ВИС)`;
- уровни и толщины плит из разрезов АР (`cad_section_levels`, только последние ревизии PDF),
  схем КР (`cad_project_levels`) и проектного ввода плиты (`cad_project_levels` БД);
- виды фасадов (`cad_facade_views`, только последние ревизии PDF) с осями и окнами;
- зоны помещений (включая балконы/террасы и МОП) и вертикальных соседей фокусного вида.

Сбой чтения одного артефакта не роняет сборку: проблемный слой пропускается с пометкой.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections.abc import Sequence
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import CadFrameRead
from app.contracts.cad_building3d import CadBuilding3dFloorRead, CadBuilding3dRead
from app.contracts.cad_project_context import (
    CadProjectContextRead,
    CadProjectCoordinationContext,
    CadProjectFacadeView,
    CadProjectFacadeWindowSample,
    CadProjectFocusView,
    CadProjectKrLevel,
    CadProjectSectionLevel,
    CadProjectViewPlacement,
    CadProjectZoneSummary,
)
from app.contracts.tender_exchange import ObjectBaseAxis, ObjectBaseCoordination, make_view_key
from app.core.logging import get_logger
from app.models import (
    CadFacadeView,
    CadProjectLevels,
    CadSectionLevel,
    CadZone,
    Project,
    TenderBaseRelease,
)
from app.services import (
    cad_building3d,
    cad_building3d_assembly,
    cad_project_levels,
    cad_views,
    cad_zones,
    sheet_passports,
    tender_base,
)
from app.services.tender_base_coordination import CoordinationFloor, build_coordination
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

_READ_CONCURRENCY: Final = 6
_MAX_FACADE_WINDOWS_SAMPLE: Final = 60
_VIEW_ZONE_MARGIN_MM: Final = 1500.0
_BALCONY_KEYWORDS: Final = ("балкон", "лодж", "террас", "кровл", "стилобат")
_COORDINATE_BRIDGE_NOTE: Final = (
    "Сквозной перевод координат: "
    "1) px (plan.png/overlay.png/slab_overlay.png) -> pt PDF: "
    "x_pt = clip[0] + x_px / zoom, y_pt = clip[1] + y_px / zoom (из render.json); "
    "2) pt PDF -> view_mm (DXF вида): "
    "x_mm = (x_pt - ox) * k, y_mm = (oy - y_pt) * k (из frame = [ox, oy, k]); "
    "3) view_mm -> building_mm (общая сетка осей для ВИС и 3D): "
    "p_building = R(rotation_deg) * p_view + offset_mm, Z = base_z_mm + z_local_mm."
)


def _slab_area_m2(floor: CadBuilding3dFloorRead) -> float | None:
    """Площадь плиты листа: основной контур плюс остальные части многочастной плиты."""
    areas = [_polygon_area_m2(ring) for ring in (floor.outline, *floor.outline_parts)]
    known = [area for area in areas if area is not None]
    return round(sum(known), 2) if known else None


def _polygon_area_m2(ring: Sequence[Sequence[float]]) -> float | None:
    if len(ring) < 3:
        return None
    twice = 0.0
    count = len(ring)
    for index in range(count):
        x0, y0 = ring[index][0], ring[index][1]
        x1, y1 = ring[(index + 1) % count][0], ring[(index + 1) % count][1]
        twice += x0 * y1 - x1 * y0
    area = abs(twice) / 2.0 / 1_000_000.0
    return round(area, 2) if area > 0 else None


def _is_balcony_or_terrace(room_type: str | None, name: str | None) -> bool:
    if room_type == "balcony":
        return True
    low = (name or "").casefold()
    return any(word in low for word in _BALCONY_KEYWORDS)


def _finite_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    num = float(value)
    return round(num) if math.isfinite(num) else None


async def _active_release_coordination(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> CadProjectCoordinationContext | None:
    release = await session.scalar(
        select(TenderBaseRelease)
        .where(
            TenderBaseRelease.workspace_id == workspace_id,
            TenderBaseRelease.project_id == project_id,
            TenderBaseRelease.revoked_at.is_(None),
        )
        .order_by(TenderBaseRelease.number.desc())
        .limit(1)
    )
    if release is None:
        return None
    try:
        raw = await tender_base.read_package_member(
            storage, release.package_key, "coordination.json"
        )
    except (ObjectNotFoundError, StorageUnavailableError, OSError):
        log.warning("cad_project_context_release_read_failed", release_id=str(release.id))
        return None
    if raw is None:
        return None
    try:
        coordination = ObjectBaseCoordination.model_validate(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, ValidationError):
        log.warning("cad_project_context_release_invalid", release_id=str(release.id))
        return None
    return CadProjectCoordinationContext(
        source="base_release",
        release_id=release.id,
        release_number=release.number,
        coordination=coordination,
        note=f"Замороженная координационная сетка действующего выпуска базы №{release.number}.",
    )


async def _read_frame_and_axes(
    storage: ObjectStorage,
    sheet: cad_building3d.SheetRef,
    *,
    need_axes: bool,
) -> tuple[CadFrameRead | None, cad_building3d.FloorAxes]:
    if sheet.scale_key is None or sheet.checks_key is None:
        return None, cad_building3d.NO_AXES
    try:
        scale_raw = await cad_views.read_json(storage, sheet.scale_key)
        checks_raw = await cad_views.read_json(storage, sheet.checks_key)
        frame = cad_views.frame_from(cad_views.scale_from(scale_raw), checks_raw)
        if not need_axes:
            return frame, cad_building3d.NO_AXES
        if (
            not frame.confirmed
            or frame.origin_pt is None
            or not frame.mm_per_pdf_point
            or sheet.walls_key is None
            or cad_building3d.is_summary_sheet(sheet.stamp_title)
        ):
            return frame, cad_building3d.NO_AXES
        walls_raw = await cad_views.read_json(storage, sheet.walls_key)
    except (
        ObjectNotFoundError,
        StorageUnavailableError,
        cad_views.ArtifactTooLargeError,
        ValueError,
    ):
        return None, cad_building3d.NO_AXES
    return frame, cad_building3d.axes_in_mm(walls_raw, frame)


def _object_axes(axes: cad_building3d.FloorAxes) -> list[ObjectBaseAxis]:
    return [
        ObjectBaseAxis(label=label, orient="vertical", pos_mm=round(pos))
        for label, pos in sorted(axes.vertical.items())
    ] + [
        ObjectBaseAxis(label=label, orient="horizontal", pos_mm=round(pos))
        for label, pos in sorted(axes.horizontal.items())
    ]


async def _live_coordination_and_frames(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    building: CadBuilding3dRead,
    build_grid: bool,
) -> tuple[
    CadProjectCoordinationContext | None,
    dict[tuple[uuid.UUID, int, int], list[float]],
]:
    if not building.floors:
        return None, {}
    sheets, _warnings, _slab = await cad_building3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    sheet_by_key = {(s.revision_id, s.page_index, s.view): s for s in sheets}

    unique_keys: list[tuple[uuid.UUID, int, int]] = []
    seen: set[tuple[uuid.UUID, int, int]] = set()
    for floor in building.floors:
        key = (floor.revision_id, floor.page_index, floor.view)
        if key not in seen and key in sheet_by_key:
            seen.add(key)
            unique_keys.append(key)

    gate = asyncio.Semaphore(_READ_CONCURRENCY)

    async def load_one(
        key: tuple[uuid.UUID, int, int],
    ) -> tuple[tuple[uuid.UUID, int, int], CadFrameRead | None, cad_building3d.FloorAxes]:
        async with gate:
            frame, axes = await _read_frame_and_axes(
                storage, sheet_by_key[key], need_axes=build_grid
            )
            return key, frame, axes

    loaded = await asyncio.gather(*(load_one(key) for key in unique_keys))
    frames_by_key: dict[tuple[uuid.UUID, int, int], list[float]] = {}
    axes_by_key: dict[tuple[uuid.UUID, int, int], cad_building3d.FloorAxes] = {}
    for key, frame, axes in loaded:
        axes_by_key[key] = axes
        if (
            frame is not None
            and frame.confirmed
            and frame.origin_pt is not None
            and frame.mm_per_pdf_point is not None
        ):
            frames_by_key[key] = [
                round(frame.origin_pt[0], 4),
                round(frame.origin_pt[1], 4),
                round(frame.mm_per_pdf_point, 6),
            ]

    if not build_grid:
        return None, frames_by_key

    coord_floors: list[CoordinationFloor] = []
    for floor in building.floors:
        if floor.typical_of is not None:
            continue
        key = (floor.revision_id, floor.page_index, floor.view)
        axes = axes_by_key.get(key, cad_building3d.NO_AXES)
        coord_floors.append(
            CoordinationFloor(
                view_key=make_view_key(floor.revision_id, floor.page_index, floor.view),
                label=floor.label,
                group_key=floor.group_key,
                group_label=floor.group_label,
                base_z_mm=floor.base_z_mm,
                floor_height_mm=floor.floor_height_mm,
                offset_mm=(floor.offset_mm[0], floor.offset_mm[1]),
                rotation_deg=floor.rotation_deg,
                alignment=floor.alignment,
                axes=_object_axes(axes),
                oblique=[(item.label, item.point_mm, item.direction) for item in axes.oblique],
                elevation_known=floor.elevation_known,
            )
        )
    coordination = build_coordination(coord_floors)
    return (
        CadProjectCoordinationContext(
            source="live_building3d",
            coordination=coordination,
            note=(
                "Рабочая координационная сетка собрана на лету из cad_building3d "
                "(выпуск базы ещё не оформлен; формат идентичен coordination.json)."
            ),
        ),
        frames_by_key,
    )


def _placement_from(
    floor: CadBuilding3dFloorRead,
    frames_by_key: dict[tuple[uuid.UUID, int, int], list[float]],
) -> CadProjectViewPlacement:
    key = (floor.revision_id, floor.page_index, floor.view)
    return CadProjectViewPlacement(
        view_key=make_view_key(floor.revision_id, floor.page_index, floor.view),
        job_id=floor.job_id,
        revision_id=floor.revision_id,
        page_index=floor.page_index,
        view=floor.view,
        label=floor.label,
        group_key=floor.group_key,
        group_label=floor.group_label,
        corps=floor.corps,
        section=floor.section,
        kind=floor.kind,
        typical_of=floor.typical_of,
        base_z_mm=floor.base_z_mm,
        elevation_known=floor.elevation_known,
        floor_height_mm=floor.floor_height_mm,
        floor_height_known=floor.floor_height_known,
        floor_height_source=floor.floor_height_source,
        slab_thickness_mm=floor.slab_thickness_mm,
        slab_thickness_known=floor.slab_thickness_known,
        offset_mm=[round(floor.offset_mm[0], 1), round(floor.offset_mm[1], 1)],
        rotation_deg=floor.rotation_deg,
        alignment=floor.alignment,
        alignment_axes=list(floor.alignment_axes),
        outline_source=floor.outline_source,
        slab_area_m2=_slab_area_m2(floor) if floor.outline_source == "slab" else None,
        windows_count=len(floor.windows or ()),
        level_zones_count=len(floor.levels),
        frame=frames_by_key.get(key),
    )


def _facade_axes_labels(raw_axes: Sequence[Any]) -> list[str]:
    labels: list[str] = []
    for item in raw_axes:
        if isinstance(item, dict):
            label = str(item.get("label_full") or item.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _facade_windows_sample(raw_windows: Sequence[Any]) -> list[CadProjectFacadeWindowSample]:
    sample: list[CadProjectFacadeWindowSample] = []
    for item in raw_windows[:_MAX_FACADE_WINDOWS_SAMPLE]:
        if not isinstance(item, dict):
            continue
        sample.append(
            CadProjectFacadeWindowSample(
                z_bottom_mm=_finite_int(item.get("z_bottom_mm")),
                z_top_mm=_finite_int(item.get("z_top_mm")),
                width_mm=_finite_int(item.get("width_mm")),
            )
        )
    return sample


def _vertical_neighbors(
    target: CadProjectViewPlacement | None,
    views: Sequence[CadProjectViewPlacement],
) -> tuple[str | None, int | None, str | None, int | None]:
    if target is None or not target.elevation_known:
        return None, None, None, None
    same_group = [
        v
        for v in views
        if v.group_key == target.group_key and v.elevation_known and v.base_z_mm != target.base_z_mm
    ]
    below = [v for v in same_group if v.base_z_mm < target.base_z_mm]
    above = [v for v in same_group if v.base_z_mm > target.base_z_mm]
    nearest_below = max(below, key=lambda v: v.base_z_mm) if below else None
    nearest_above = min(above, key=lambda v: v.base_z_mm) if above else None
    return (
        nearest_below.label if nearest_below else None,
        nearest_below.base_z_mm if nearest_below else None,
        nearest_above.label if nearest_above else None,
        nearest_above.base_z_mm if nearest_above else None,
    )


def _bbox_in_view_mm(
    bbox: Sequence[float] | None, offset_mm: Sequence[float], rotation_deg: float
) -> tuple[float, float, float, float] | None:
    if bbox is None or len(bbox) != 4:
        return None
    angle = math.radians(-rotation_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    xs: list[float] = []
    ys: list[float] = []
    for px, py in (
        (bbox[0], bbox[1]),
        (bbox[2], bbox[1]),
        (bbox[2], bbox[3]),
        (bbox[0], bbox[3]),
    ):
        dx, dy = px - offset_mm[0], py - offset_mm[1]
        xs.append(dx * cos_a - dy * sin_a)
        ys.append(dx * sin_a + dy * cos_a)
    return (min(xs), min(ys), max(xs), max(ys))


async def _filter_zones_for_multiview_page(
    session: AsyncSession,
    *,
    zone_rows: Sequence[CadZone],
    revision_id: uuid.UUID,
    page_index: int,
    target_floor: CadBuilding3dFloorRead | None,
    frame: list[float] | None,
) -> list[CadZone]:
    """На странице с несколькими видами оставляет только зоны в пределах bbox фокусного вида."""
    if target_floor is None or frame is None or len(frame) != 3 or target_floor.bbox is None:
        return list(zone_rows)
    view_bbox = _bbox_in_view_mm(
        target_floor.bbox, target_floor.offset_mm, target_floor.rotation_deg
    )
    if view_bbox is None:
        return list(zone_rows)
    scales = await cad_zones.page_scales(
        session, revision_id=revision_id, page_indexes={page_index}
    )
    scale = scales.get(page_index)
    if scale is None or scale.geometry is None:
        return list(zone_rows)
    pw = float(scale.geometry.display_width_pt)
    ph = float(scale.geometry.display_height_pt)
    ox, oy, k = frame
    kept: list[CadZone] = []
    for row in zone_rows:
        if not row.points:
            continue
        pts = [
            ((float(p[0]) * pw - ox) * k, (oy - float(p[1]) * ph) * k)
            for p in row.points
            if len(p) >= 2
        ]
        if not pts:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if (
            view_bbox[0] - _VIEW_ZONE_MARGIN_MM <= cx <= view_bbox[2] + _VIEW_ZONE_MARGIN_MM
            and view_bbox[1] - _VIEW_ZONE_MARGIN_MM <= cy <= view_bbox[3] + _VIEW_ZONE_MARGIN_MM
        ):
            kept.append(row)
    return kept


async def build_project_context(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project: Project,
    focus_revision_id: uuid.UUID | None = None,
    focus_page_index: int | None = None,
    focus_view: int | None = None,
) -> CadProjectContextRead:
    """Собирает полный контекст CAD проекта (координатная сетка, уровни, фасады, зоны)."""
    building = await cad_building3d_assembly.build_building3d(
        session,
        storage,
        workspace_id=project.workspace_id,
        project_id=project.id,
        include_walls=False,
    )

    release_coord = await _active_release_coordination(
        session, storage, workspace_id=project.workspace_id, project_id=project.id
    )
    live_coord, frames_by_key = await _live_coordination_and_frames(
        session,
        storage,
        workspace_id=project.workspace_id,
        project_id=project.id,
        building=building,
        build_grid=release_coord is None,
    )
    coordination = (
        release_coord
        or live_coord
        or CadProjectCoordinationContext(
            source="empty",
            note="В проекте ещё нет готовых видов CAD с конструкциями для сборки сетки.",
        )
    )

    views = [_placement_from(floor, frames_by_key) for floor in building.floors]

    latest_revisions = [
        rev.id for rev in await sheet_passports.latest_pdf_revisions(session, project_id=project.id)
    ]

    section_rows: list[CadSectionLevel] = []
    if latest_revisions:
        section_rows = list(
            await session.scalars(
                select(CadSectionLevel)
                .where(
                    CadSectionLevel.workspace_id == project.workspace_id,
                    CadSectionLevel.project_id == project.id,
                    CadSectionLevel.revision_id.in_(latest_revisions),
                    CadSectionLevel.status != "rejected",
                )
                .order_by(
                    CadSectionLevel.elevation_mm, CadSectionLevel.page_index, CadSectionLevel.seq
                )
            )
        )
    sections = [
        CadProjectSectionLevel(
            id=row.id,
            revision_id=row.revision_id,
            page_index=row.page_index,
            cut=row.cut,
            corps=row.corps,
            section=row.section,
            floor=row.floor,
            elevation_mm=row.elevation_mm,
            upper_elevation_mm=row.upper_elevation_mm,
            clear_height_mm=row.clear_height_mm,
            structure_mm=row.structure_mm,
            status=row.status,
            auto_accepted=row.auto_accepted,
            evidence=row.evidence,
        )
        for row in section_rows
    ]

    kr_map = await cad_project_levels.load_project_levels(session, project_id=project.id)
    kr_levels = [
        CadProjectKrLevel(
            corps=corps,
            floor=floor_no,
            z_mm=entry.z_mm,
            ref=entry.ref,
            source=entry.source,
        )
        for (corps, floor_no), entry in sorted(kr_map.items())
    ]

    project_levels_row = await session.scalar(
        select(CadProjectLevels).where(
            CadProjectLevels.workspace_id == project.workspace_id,
            CadProjectLevels.project_id == project.id,
        )
    )

    facade_rows: list[CadFacadeView] = []
    if latest_revisions:
        facade_rows = list(
            await session.scalars(
                select(CadFacadeView)
                .where(
                    CadFacadeView.workspace_id == project.workspace_id,
                    CadFacadeView.project_id == project.id,
                    CadFacadeView.revision_id.in_(latest_revisions),
                    CadFacadeView.status != "rejected",
                )
                .order_by(CadFacadeView.page_index, CadFacadeView.seq)
            )
        )
    facades = [
        CadProjectFacadeView(
            id=row.id,
            revision_id=row.revision_id,
            page_index=row.page_index,
            view_key=row.view_key,
            title=row.title,
            corps=row.corps,
            section=row.section,
            axis_from=row.axis_from,
            axis_to=row.axis_to,
            status=row.status,
            scale_status=row.scale_status,
            axes=_facade_axes_labels(row.axes),
            window_count=row.window_count,
            windows_sample=_facade_windows_sample(row.windows),
        )
        for row in facade_rows
    ]

    focus: CadProjectFocusView | None = None
    if focus_revision_id is not None and focus_page_index is not None and focus_view is not None:
        focus_key = make_view_key(focus_revision_id, focus_page_index, focus_view)
        placement = next(
            (v for v in views if v.view_key == focus_key and v.typical_of is None),
            next((v for v in views if v.view_key == focus_key), None),
        )
        target_floor = next(
            (
                f
                for f in building.floors
                if (f.revision_id, f.page_index, f.view)
                == (focus_revision_id, focus_page_index, focus_view)
                and f.typical_of is None
            ),
            None,
        )
        below_label, below_z, above_label, above_z = _vertical_neighbors(placement, views)
        zone_rows = list(
            await session.scalars(
                select(CadZone)
                .where(
                    CadZone.workspace_id == project.workspace_id,
                    CadZone.project_id == project.id,
                    CadZone.revision_id == focus_revision_id,
                    CadZone.page_index == focus_page_index,
                )
                .order_by(CadZone.kind, CadZone.apartment_no, CadZone.room_mark, CadZone.id)
            )
        )
        views_on_same_page = {
            f.view
            for f in building.floors
            if f.revision_id == focus_revision_id and f.page_index == focus_page_index
        }
        if len(views_on_same_page) > 1 and zone_rows:
            zone_rows = await _filter_zones_for_multiview_page(
                session,
                zone_rows=zone_rows,
                revision_id=focus_revision_id,
                page_index=focus_page_index,
                target_floor=target_floor,
                frame=placement.frame if placement is not None else None,
            )

        zones: list[CadProjectZoneSummary] = []
        apt_count = 0
        mop_count = 0
        balcony_count = 0
        for row in zone_rows:
            eff_type, _src = cad_zones.effective_room_type(row.kind, row.room_type, row.name)
            if row.kind == "room_apartment":
                apt_count += 1
            elif row.kind == "room_mop":
                mop_count += 1
            if row.kind in cad_zones.ROOM_KINDS and _is_balcony_or_terrace(eff_type, row.name):
                balcony_count += 1
            zones.append(
                CadProjectZoneSummary(
                    id=row.id,
                    kind=row.kind,
                    apartment_no=row.apartment_no,
                    room_mark=row.room_mark,
                    name=row.name,
                    room_type=eff_type,
                    expl_area_m2=row.expl_area_m2,
                    generator_area_m2=row.generator_area_m2,
                    source=row.source,
                    quality_status=row.quality_status,
                )
            )
        focus = CadProjectFocusView(
            view_key=focus_key,
            revision_id=focus_revision_id,
            page_index=focus_page_index,
            view=focus_view,
            placement=placement,
            below_label=below_label,
            below_z_mm=below_z,
            above_label=above_label,
            above_z_mm=above_z,
            zones=zones,
            apartment_zones_count=apt_count,
            mop_zones_count=mop_count,
            balcony_terrace_zones_count=balcony_count,
            coordinate_bridge=_COORDINATE_BRIDGE_NOTE,
        )

    return CadProjectContextRead(
        project_id=project.id,
        project_name=project.name,
        coordination=coordination,
        groups=list(building.groups),
        views=views,
        sections=sections,
        kr_levels=kr_levels,
        project_slab_mm=(
            project_levels_row.slab_thickness_mm if project_levels_row is not None else None
        ),
        project_slab_ref=(
            project_levels_row.slab_source_ref if project_levels_row is not None else None
        ),
        facades=facades,
        building_warnings=list(building.warnings),
        focus_view=focus,
    )
