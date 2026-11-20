"""«Здание» по утверждённой модели здания: сетка осей ставит корпуса, этажи модели дают отметки.

У проекта с утверждённой версией модели (IFC → пакет QMP, ADR-0053) есть сетка осей всех корпусов
в одной системе (`grids.json`) и этажи каждого здания с отметками. Сборка «Здания» берёт из неё:

- отметки этажей корпуса, когда их нет ни в заголовке плана, ни в схемах КР (типовой лист
  «5–12 эт.» без отметок): `model_levels` - (корпус, этаж) → отметка этажа модели; КР - первыми;
- постановку на объект зданий, которые не встали ни по осям, ни по ядрам, ни по ручной привязке
  (листы башен повёрнуты к стилобату, общих осей с поставленными зданиями нет). Каждый этаж
  подгоняется по подписям осей к сетке модели той же подгонкой, что «чертёж наложением»
  (`model_sheets.fit_sheet`). Переход «модель → объект» берётся по уже поставленным этажам и
  проверяется на согласие; здание встаёт, только если согласны его собственные этажи.

Без утверждённой модели ничего не меняется (объекты без IFC собираются как прежде).
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_building3d import CadBuilding3dFloorRead
from app.core.logging import get_logger
from app.domain import ModelVersionStatus
from app.models import BuildingModelVersion
from app.services import building_models, cad_project_levels, model_sheets
from app.services import cad_building3d as b3d
from app.storage.base import ObjectStorage

log = get_logger(__name__)

Point = tuple[float, float]

# Переход «модель → объект» по поставленным этажам: столько этажей с подгонкой нужно, и в таких
# пределах они должны совпасть (поворот, положение центра площадки модели).
GRID_MIN_FLOORS: Final = 2
GRID_AGREE_DEG: Final = 0.5
GRID_AGREE_MM: Final = 150.0
# Этажи одного здания по сетке: в таких пределах они дают одно место (центр здания).
GROUP_AGREE_DEG: Final = 0.5
GROUP_AGREE_MM: Final = 300.0
# Масштаб вида листа (мм DXF) против мм модели: подгонка с иным масштабом - не этот лист.
SCALE_FRAME: Final = 1.0


@dataclass(frozen=True, slots=True)
class GridFit:
    """Вид листа (мм DXF) → модель (мм): `p_модели = scale · R(rotation_deg) · p_вида + offset`."""

    rotation_deg: float
    scale: float
    offset: Point
    rms_mm: float
    used: tuple[str, ...]

    def apply(self, x: float, y: float) -> Point:
        c, s = _cos_sin(self.rotation_deg)
        k = self.scale
        return (k * (c * x - s * y) + self.offset[0], k * (s * x + c * y) + self.offset[1])


@dataclass(frozen=True, slots=True)
class ModelReference:
    """Утверждённая версия модели проекта: номер, сетка осей, отметки этажей корпусов."""

    version_id: uuid.UUID
    number: int
    axes: tuple[model_sheets.ModelAxis, ...]
    levels: Mapping[tuple[str, int], cad_project_levels.ProjectLevel]


def _cos_sin(degrees: float) -> tuple[float, float]:
    turns = degrees / 90.0
    if turns == round(turns):
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[round(turns) % 4]
    rad = math.radians(degrees)
    return math.cos(rad), math.sin(rad)


def _rotate(point: Point, degrees: float) -> Point:
    c, s = _cos_sin(degrees)
    return (c * point[0] - s * point[1], s * point[0] + c * point[1])


def _turn_gap(a: float, b: float) -> float:
    gap = abs(a - b) % 360.0
    return min(gap, 360.0 - gap)


def _mean_angle(values: Sequence[float]) -> float:
    x = sum(math.cos(math.radians(v)) for v in values)
    y = sum(math.sin(math.radians(v)) for v in values)
    return math.degrees(math.atan2(y, x))


# --------------------------------------------------------------------------- загрузка


def model_levels(
    storeys: Sequence[object], number: int
) -> dict[tuple[str, int], cad_project_levels.ProjectLevel]:
    """(корпус, этаж) → отметка этажа модели; этажи без номера и здания без номера - мимо."""
    out: dict[tuple[str, int], cad_project_levels.ProjectLevel] = {}
    for storey in storeys:
        building = getattr(storey, "building_name", None)
        name = getattr(storey, "name", "") or ""
        elevation = getattr(storey, "elevation_mm", None)
        corps = cad_project_levels.corps_key(model_sheets.building_number(building))
        floor = model_sheets.storey_floor(name)
        if corps is None or floor is None or floor == 0 or elevation is None:
            continue
        if not math.isfinite(float(elevation)):
            continue
        out.setdefault(
            (corps, floor),
            cad_project_levels.ProjectLevel(
                round(float(elevation)),
                f"модель здания, версия {number}: {building}, {name}",
                source="модели здания",
            ),
        )
    return out


def merged_levels(
    project: Mapping[tuple[str, int], cad_project_levels.ProjectLevel],
    reference: ModelReference | None,
) -> Mapping[tuple[str, int], cad_project_levels.ProjectLevel]:
    """Отметки КР, недостающие - из модели здания."""
    if reference is None or not reference.levels:
        return project
    return {**reference.levels, **project}


async def load_model_reference(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ModelReference | None:
    """Утверждённая версия модели проекта; нет её - `None`."""
    version = await session.scalar(
        select(BuildingModelVersion)
        .where(
            BuildingModelVersion.project_id == project_id,
            BuildingModelVersion.workspace_id == workspace_id,
            BuildingModelVersion.status == ModelVersionStatus.APPROVED,
        )
        .order_by(BuildingModelVersion.number.desc())
        .limit(1)
    )
    if version is None:
        return None
    try:
        axes = await model_sheets.load_model_axes(storage, version) or []
    except (ValueError, OSError) as error:
        log.warning(
            "cad_building3d_grid.grids_unreadable", version_id=str(version.id), error=str(error)
        )
        axes = []
    storeys = await building_models.storeys_of(session, version.id)
    return ModelReference(
        version.id, version.number, tuple(axes), model_levels(storeys, version.number)
    )


# --------------------------------------------------------------------------- подгонка этажа


def floor_fit(axes: b3d.FloorAxes, model: Sequence[model_sheets.ModelAxis]) -> GridFit | None:
    """Вид этажа (оси в мм DXF) → сетка модели по подписям осей; не сходится - `None`.

    Оси вида подаются в `fit_sheet` как «лист» с осью Y вниз (горизонтальные - с минусом) и
    масштабом 1: подобие лист → модель тогда - поворот и сдвиг вида без отражения.
    """
    if not model or not (axes.usable or axes.oblique):
        return None
    sheet = [
        model_sheets.SheetAxis(label, "vertical", float(x)) for label, x in axes.vertical.items()
    ] + [
        model_sheets.SheetAxis(label, "horizontal", -float(y))
        for label, y in axes.horizontal.items()
    ]
    for oblique in axes.oblique:
        # ось под углом (корпус повёрнут на плане): точка и направление в мм DXF (Y вверх)
        # переводятся в «лист» с осью Y вниз
        dx, dy = oblique.direction
        angle = math.degrees(math.atan2(-dy, dx)) % 180.0
        point = (float(oblique.point_mm[0]), -float(oblique.point_mm[1]))
        sheet.append(model_sheets.SheetAxis(oblique.label, "oblique", 0.0, angle, point))
    fit, _reason = model_sheets.fit_sheet(sheet, model, frame_scale=SCALE_FRAME)
    if fit is None:
        return None
    return GridFit(fit.rotation_deg, fit.scale, fit.offset, fit.rms_mm, fit.used)


# --------------------------------------------------------------------------- постановка


@dataclass(frozen=True, slots=True)
class _Transform:
    """`p_цели = R(rotation_deg) · p + offset`."""

    rotation_deg: float
    offset: Point

    def apply(self, point: Point) -> Point:
        rx, ry = _rotate(point, self.rotation_deg)
        return (rx + self.offset[0], ry + self.offset[1])


def _view_to_site(floor: CadBuilding3dFloorRead, placement: b3d.GroupPlacement) -> _Transform:
    """Вид этажа → объект: совмещение в группе (`floor`), затем постановка группы."""
    rotation = floor.rotation_deg + placement.rotation_deg
    ox, oy = _rotate(floor.offset_mm, placement.rotation_deg)
    return _Transform(rotation, (ox + placement.offset_mm[0], oy + placement.offset_mm[1]))


def _model_to_site(fit: GridFit, site: _Transform) -> _Transform:
    """Переход модель → объект по одному этажу: `site ∘ fit⁻¹` (масштаб подгонки ≈ 1)."""
    rotation = site.rotation_deg - fit.rotation_deg
    model_origin = fit.apply(0.0, 0.0)
    site_origin = site.apply((0.0, 0.0))
    rx, ry = _rotate(model_origin, rotation)
    return _Transform(rotation, (site_origin[0] - rx, site_origin[1] - ry))


def _consensus(
    items: Sequence[_Transform], probe: Point, agree_deg: float, agree_mm: float
) -> tuple[_Transform, int] | None:
    """Общий переход: медиана по точке `probe`, согласные с ней - в пределах; иначе `None`."""
    if not items:
        return None
    rotation = _mean_angle([t.rotation_deg for t in items])
    xs = [t.apply(probe)[0] for t in items]
    ys = [t.apply(probe)[1] for t in items]
    centre = (statistics.median(xs), statistics.median(ys))
    kept = [
        t
        for t, x, y in zip(items, xs, ys, strict=True)
        if _turn_gap(t.rotation_deg, rotation) <= agree_deg
        and math.hypot(x - centre[0], y - centre[1]) <= agree_mm
    ]
    if not kept:
        return None
    rotation = _mean_angle([t.rotation_deg for t in kept])
    cx = statistics.median(t.apply(probe)[0] for t in kept)
    cy = statistics.median(t.apply(probe)[1] for t in kept)
    rx, ry = _rotate(probe, rotation)
    return _Transform(rotation, (cx - rx, cy - ry)), len(kept)


def place_by_grid(
    items: Sequence[b3d.BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    placements: dict[str, b3d.GroupPlacement],
    version_number: int,
) -> dict[str, b3d.GroupPlacement]:
    """Здания, не вставшие на объект, - по сетке осей модели; остальные постановки не трогаются."""
    return place_and_align_by_grid(items, aligned, placements, version_number)[0]


def place_and_align_by_grid(
    items: Sequence[b3d.BuiltFloor],
    aligned: Sequence[CadBuilding3dFloorRead],
    placements: dict[str, b3d.GroupPlacement],
    version_number: int,
) -> tuple[dict[str, b3d.GroupPlacement], list[CadBuilding3dFloorRead]]:
    """Постановка по сетке (`place_by_grid`) и этажи, не совмещённые в своей группе.

    Этаж поставленной группы, не совмещённый с эталоном группы по осям (`alignment = none`: общих
    осей нет, оси одного направления, корпус повёрнут на листе), но подогнанный к сетке модели,
    ставится по сетке: его положение в системе группы = постановка группы⁻¹ ∘ модель→объект ∘
    подгонка этажа.
    Этаж стилобата («Корпус не указан») без совмещения и без подгонки не остаётся в центре основы
    площадки, а выносится своей группой без постановки - место его неизвестно.
    """
    floors = list(aligned)
    fits = [item.grid for item in items]
    if not any(fit is not None for fit in fits):
        return placements, floors
    samples: list[_Transform] = []
    probes: list[Point] = []
    for fit, floor in zip(fits, aligned, strict=True):
        placement = placements.get(floor.group_key)
        if fit is None or placement is None or placement.placement == "none":
            continue
        samples.append(_model_to_site(fit, _view_to_site(floor, placement)))
        probes.append(fit.apply(0.0, 0.0))
    if len(samples) < GRID_MIN_FLOORS:
        return placements, floors
    probe = (statistics.median(p[0] for p in probes), statistics.median(p[1] for p in probes))
    agreed = _consensus(samples, probe, GRID_AGREE_DEG, GRID_AGREE_MM)
    if agreed is None or agreed[1] < max(GRID_MIN_FLOORS, (len(samples) + 1) // 2):
        log.info("cad_building3d_grid.no_consensus", floors=len(samples))
        return placements, floors
    model_to_site = agreed[0]
    floors = _align_unaligned(items, floors, placements, model_to_site, version_number)
    by_group: dict[str, list[tuple[GridFit, CadBuilding3dFloorRead]]] = {}
    for fit, floor in zip(fits, aligned, strict=True):
        current = placements.get(floor.group_key)
        if fit is None or (current is not None and current.placement != "none"):
            continue
        by_group.setdefault(floor.group_key, []).append((fit, floor))
    result = dict(placements)
    for key, rows in sorted(by_group.items()):
        options: list[_Transform] = []
        for fit, floor in rows:
            # группа → вид: обратное совмещению этажа в группе; вид → модель → объект
            rotation = model_to_site.rotation_deg + fit.rotation_deg - floor.rotation_deg
            site_origin = model_to_site.apply(fit.apply(0.0, 0.0))
            rx, ry = _rotate(floor.offset_mm, rotation)
            options.append(_Transform(rotation, (site_origin[0] - rx, site_origin[1] - ry)))
        box = rows[0][1].bbox
        centre = (0.0, 0.0) if box is None else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        chosen = _consensus(options, centre, GROUP_AGREE_DEG, GROUP_AGREE_MM)
        if chosen is None or chosen[1] < (len(options) + 1) // 2:
            log.info("cad_building3d_grid.group_disagrees", group=key, floors=len(options))
            continue
        transform, count = chosen
        used = sorted({label for fit, _floor in rows for label in fit.used})
        worst = max(fit.rms_mm for fit, _floor in rows)
        result[key] = b3d.GroupPlacement(
            "axes",
            (round(transform.offset[0], 3), round(transform.offset[1], 3)),
            tuple(used),
            None,
            f"по сетке осей модели здания (версия {version_number}): этажей {count} из "
            f"{len(options)}, СКО до {worst:.0f} мм",
            None,
            round(transform.rotation_deg % 360.0, 6),
        )
    return result, floors


def _align_unaligned(
    items: Sequence[b3d.BuiltFloor],
    floors: list[CadBuilding3dFloorRead],
    placements: dict[str, b3d.GroupPlacement],
    model_to_site: _Transform,
    version_number: int,
) -> list[CadBuilding3dFloorRead]:
    out = list(floors)
    for i, (item, floor) in enumerate(zip(items, floors, strict=True)):
        if floor.alignment != "none":
            continue
        placement = placements.get(floor.group_key)
        if placement is None or placement.placement == "none":
            continue
        fit = item.grid
        if fit is None:
            if floor.group_key == "none" and placement.placement == "reference":
                out[i] = floor.model_copy(
                    update={
                        "group_key": f"none-free-{floor.page_index}-{floor.view}",
                        "group_label": f"Корпус не указан · {floor.label}",
                        "alignment_message": (floor.alignment_message or "")
                        + "; по сетке осей модели не подогнан - место на объекте неизвестно",
                    }
                )
            continue
        # вид -> объект по сетке; вид -> группа = постановка⁻¹ ∘ (вид -> объект)
        site_rotation = model_to_site.rotation_deg + fit.rotation_deg
        site_origin = model_to_site.apply(fit.apply(0.0, 0.0))
        p_rot = placement.rotation_deg
        local = _rotate(
            (site_origin[0] - placement.offset_mm[0], site_origin[1] - placement.offset_mm[1]),
            -p_rot,
        )
        target_rotation = site_rotation - p_rot
        delta = target_rotation - floor.rotation_deg
        rx, ry = _rotate(floor.offset_mm, delta)
        moved = b3d._rotated(floor, delta, local[0] - rx, local[1] - ry)
        out[i] = moved.model_copy(
            update={
                "alignment": "axes",
                "alignment_axes": sorted(fit.used),
                "alignment_message": f"по сетке осей модели здания (версия {version_number}), "
                f"СКО {fit.rms_mm:.0f} мм",
            }
        )
    return out
