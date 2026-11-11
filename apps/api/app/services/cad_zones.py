"""Зоны листа во вкладке CAD: хранение и расчёт площади, периметра, ширины двери.

Зона - разметка человека (эталон для движка и вход будущего расчёта отделки), не измерение.
Величины считает не этот модуль: он собирает вход (геометрия страницы, действующая калибровка
листа) и отдаёт его `quantity.compute` - тому же правилу, что считает `area.v1` и `length.v1`.
Модель нигде не участвует; проёмы из площади не вычитаются.

Доступ к проекту и ревизии проверяет вызывающий; зона чужого пространства не находится.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_zones import (
    CadParkingType,
    CadZoneCreate,
    CadZoneKind,
    CadZoneRead,
    CadZoneUpdate,
)
from app.domain import GeometryType, QuantityState
from app.errors import DomainError, ErrorCode
from app.models import CadZone, Measurement, PageGeometry, ScaleCalibration, Sheet
from app.models.cad_zone import DOOR_HEIGHT_MAX_MM, DOOR_HEIGHT_MIN_MM
from app.services import quantity
from app.services.takeoff import validate_geometry, validate_points

# Дверь - отрезок, а не точка: две совпавшие вершины ширины не дают.
_MIN_DOOR_SEGMENT: Final = 1e-6


@dataclass(frozen=True, slots=True)
class PageScale:
    geometry: PageGeometry | None
    calibration: ScaleCalibration | None


@dataclass(frozen=True, slots=True)
class ZoneFields:
    """Итоговое состояние зоны: вход проверки и при создании, и при правке."""

    kind: str
    apartment_no: str | None
    room_mark: str | None
    name: str | None
    points: list[list[float]]
    door_height_mm: int | None
    parking_type: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _invalid(detail: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_FAILED, detail)


def validate_fields(fields: ZoneFields) -> ZoneFields:
    """Вид-зависимые поля и геометрия; возвращает нормализованное состояние."""
    apartment_no = _clean(fields.apartment_no)
    points: list[list[float]]
    if fields.kind == "door":
        points = validate_points(GeometryType.LINE, fields.points)
        (x0, y0), (x1, y1) = points
        if abs(x1 - x0) < _MIN_DOOR_SEGMENT and abs(y1 - y0) < _MIN_DOOR_SEGMENT:
            raise _invalid("Дверь: точки линии совпадают")
        height = fields.door_height_mm
        if height is None or not DOOR_HEIGHT_MIN_MM <= height <= DOOR_HEIGHT_MAX_MM:
            raise _invalid(
                f"Дверь: высота проёма {DOOR_HEIGHT_MIN_MM}..{DOOR_HEIGHT_MAX_MM} мм обязательна"
            )
        if apartment_no is not None:
            raise _invalid("Дверь: № квартиры не задаётся")
    else:
        # Тот же контроль, что у многоугольника обмера (ADR-0026): самопересечения, вырождение.
        points, _ = validate_geometry(GeometryType.POLYGON, fields.points)
        if fields.door_height_mm is not None:
            raise _invalid("Высота проёма задаётся только двери")
        if fields.kind == "room_apartment" and apartment_no is None:
            raise _invalid("Помещение квартиры: № квартиры обязателен")
        if fields.kind == "room_mop" and apartment_no is not None:
            raise _invalid("Помещение МОП: № квартиры не задаётся")
        if fields.kind == "parking_space" and apartment_no is not None:
            raise _invalid("Машино-место: № квартиры не задаётся")
    if fields.kind == "parking_space":
        if fields.parking_type is None:
            raise _invalid("Машино-место: тип обязателен")
    elif fields.parking_type is not None:
        raise _invalid("Тип задаётся только машино-месту")
    return ZoneFields(
        kind=fields.kind,
        apartment_no=apartment_no,
        room_mark=_clean(fields.room_mark),
        name=_clean(fields.name),
        points=points,
        door_height_mm=fields.door_height_mm if fields.kind == "door" else None,
        parking_type=fields.parking_type,
    )


def _fields_of(zone: CadZone) -> ZoneFields:
    return ZoneFields(
        kind=zone.kind,
        apartment_no=zone.apartment_no,
        room_mark=zone.room_mark,
        name=zone.name,
        points=[[float(x), float(y)] for x, y in zone.points],
        door_height_mm=zone.door_height_mm,
        parking_type=zone.parking_type,
    )


def _apply(zone: CadZone, fields: ZoneFields) -> None:
    zone.kind = fields.kind
    zone.apartment_no = fields.apartment_no
    zone.room_mark = fields.room_mark
    zone.name = fields.name
    zone.points = fields.points
    zone.door_height_mm = fields.door_height_mm
    zone.parking_type = fields.parking_type


async def list_zones(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int | None
) -> list[CadZone]:
    query = select(CadZone).where(CadZone.revision_id == revision_id)
    if page_index is not None:
        query = query.where(CadZone.page_index == page_index)
    rows = await session.scalars(query.order_by(CadZone.page_index, CadZone.created_at, CadZone.id))
    return list(rows)


async def get_zone(
    session: AsyncSession, *, workspace_id: uuid.UUID, zone_id: uuid.UUID
) -> CadZone | None:
    """Зона внутри своего пространства; чужая не находится."""
    zone = await session.get(CadZone, zone_id)
    if zone is None or zone.workspace_id != workspace_id:
        return None
    return zone


async def create_zone(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    body: CadZoneCreate,
    user_id: uuid.UUID | None,
) -> CadZone:
    fields = validate_fields(
        ZoneFields(
            kind=body.kind,
            apartment_no=body.apartment_no,
            room_mark=body.room_mark,
            name=body.name,
            points=[[x, y] for x, y in body.points],
            door_height_mm=body.door_height_mm,
            parking_type=body.parking_type,
        )
    )
    zone = CadZone(
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=body.revision_id,
        page_index=body.page_index,
        created_by=user_id,
        **_fields_dict(fields),
    )
    session.add(zone)
    await session.flush()
    await session.refresh(zone)
    return zone


def _fields_dict(fields: ZoneFields) -> dict[str, object]:
    return {
        "kind": fields.kind,
        "apartment_no": fields.apartment_no,
        "room_mark": fields.room_mark,
        "name": fields.name,
        "points": fields.points,
        "door_height_mm": fields.door_height_mm,
        "parking_type": fields.parking_type,
    }


async def update_zone(session: AsyncSession, *, zone: CadZone, body: CadZoneUpdate) -> CadZone:
    """Переданные поля заменяют хранимые; итог проверяется как новая зона.

    Смена вида сбрасывает вид-зависимые поля (№ квартиры, высоту), если их не передали: прежние
    значения не принадлежат новому виду.
    """
    sent = body.model_fields_set
    current = _fields_of(zone)
    kind = body.kind if body.kind is not None else current.kind
    changed = kind != current.kind
    merged = ZoneFields(
        kind=kind,
        apartment_no=(
            body.apartment_no
            if "apartment_no" in sent
            else (None if changed else current.apartment_no)
        ),
        room_mark=body.room_mark if "room_mark" in sent else current.room_mark,
        name=body.name if "name" in sent else current.name,
        points=([[x, y] for x, y in body.points] if body.points is not None else current.points),
        door_height_mm=(
            body.door_height_mm
            if "door_height_mm" in sent
            else (None if changed else current.door_height_mm)
        ),
        parking_type=(
            body.parking_type
            if "parking_type" in sent
            else (None if changed else current.parking_type)
        ),
    )
    _apply(zone, validate_fields(merged))
    await session.flush()
    await session.refresh(zone)
    return zone


async def delete_zone(session: AsyncSession, *, zone: CadZone) -> None:
    await session.execute(delete(CadZone).where(CadZone.id == zone.id))


# --------------------------------------------------------------------------- величины


async def page_scales(
    session: AsyncSession, *, revision_id: uuid.UUID, page_indexes: set[int]
) -> dict[int, PageScale]:
    """Геометрия страницы и действующая калибровка листа для каждой страницы ревизии."""
    result: dict[int, PageScale] = {index: PageScale(None, None) for index in page_indexes}
    if not page_indexes:
        return result
    sheets = await session.execute(
        select(Sheet.id, Sheet.page_index).where(
            Sheet.revision_id == revision_id, Sheet.page_index.in_(page_indexes)
        )
    )
    by_sheet = dict(sheets.tuples().all())
    if not by_sheet:
        return result
    geometries = {
        geometry.sheet_id: geometry
        for geometry in await session.scalars(
            select(PageGeometry).where(PageGeometry.sheet_id.in_(by_sheet))
        )
    }
    calibrations = {
        calibration.sheet_id: calibration
        for calibration in await session.scalars(
            select(ScaleCalibration).where(
                ScaleCalibration.sheet_id.in_(by_sheet), ScaleCalibration.is_default.is_(True)
            )
        )
    }
    for sheet_id, index in by_sheet.items():
        result[index] = PageScale(geometries.get(sheet_id), calibrations.get(sheet_id))
    return result


def _compute(
    geometry_type: GeometryType, points: list[list[float]], scale: PageScale
) -> quantity.QuantityResult:
    measurement = Measurement(geometry_type=geometry_type, points=points, holes=[])
    return quantity.compute(measurement, geometry=scale.geometry, calibration=scale.calibration)


def zone_read(zone: CadZone, scale: PageScale) -> CadZoneRead:
    """Зона с величинами; не определено - `None`, а не 0."""
    points = [[float(x), float(y)] for x, y in zone.points]
    area: float | None = None
    perimeter: float | None = None
    width: float | None = None
    missing = False
    issue: str | None = None

    if zone.kind == "door":
        line = _compute(GeometryType.LINE, points, scale)
        if line.state is QuantityState.READY and line.value is not None:
            width = float(line.value)
        missing = line.state in (
            QuantityState.UNAVAILABLE_NO_SCALE,
            QuantityState.UNAVAILABLE_NO_GEOMETRY,
        )
    else:
        polygon = _compute(GeometryType.POLYGON, points, scale)
        if polygon.state is QuantityState.READY and polygon.value is not None:
            area = float(polygon.value)
            ring = _compute(GeometryType.POLYLINE, [*points, points[0]], scale)
            if ring.value is not None:
                perimeter = float(ring.value)
        missing = polygon.state in (
            QuantityState.UNAVAILABLE_NO_SCALE,
            QuantityState.UNAVAILABLE_NO_GEOMETRY,
        )
        if polygon.geometry_issue is not None:
            issue = polygon.geometry_issue.value

    return CadZoneRead(
        id=zone.id,
        revision_id=zone.revision_id,
        page_index=zone.page_index,
        kind=_kind(zone.kind),
        apartment_no=zone.apartment_no,
        room_mark=zone.room_mark,
        name=zone.name,
        points=[(x, y) for x, y in points],
        door_height_mm=zone.door_height_mm,
        parking_type=_parking_type(zone.parking_type),
        area_m2=area,
        perimeter_m=perimeter,
        width_m=width,
        calibration_missing=missing,
        geometry_issue=issue,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


def _kind(value: str) -> CadZoneKind:
    match value:
        case "room_apartment":
            return "room_apartment"
        case "room_mop":
            return "room_mop"
        case "door":
            return "door"
        case "parking_space":
            return "parking_space"
    raise DomainError(ErrorCode.VALIDATION_FAILED, f"Неизвестный вид зоны: {value}")


def _parking_type(value: str | None) -> CadParkingType | None:
    match value:
        case None:
            return None
        case (
            "permanent"
            | "temporary"
            | "guest"
            | "medium"
            | "medium_guest"
            | "large"
            | "large_guest"
            | "mgn_m1_3"
            | "mgn_m4"
            | "unknown"
        ):
            return value
    raise DomainError(ErrorCode.VALIDATION_FAILED, f"Неизвестный тип машино-места: {value}")


async def zones_read(session: AsyncSession, zones: list[CadZone]) -> list[CadZoneRead]:
    """Список зон с величинами; калибровка читается один раз на страницу."""
    scales: dict[int, PageScale] = {}
    by_revision: dict[uuid.UUID, set[int]] = {}
    for zone in zones:
        by_revision.setdefault(zone.revision_id, set()).add(zone.page_index)
    keyed: dict[tuple[uuid.UUID, int], PageScale] = {}
    for revision_id, indexes in by_revision.items():
        scales = await page_scales(session, revision_id=revision_id, page_indexes=indexes)
        for index, scale in scales.items():
            keyed[(revision_id, index)] = scale
    return [zone_read(zone, keyed[(zone.revision_id, zone.page_index)]) for zone in zones]
