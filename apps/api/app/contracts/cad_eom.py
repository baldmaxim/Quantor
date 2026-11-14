"""Контракты ЭОМ и СС этажа (`cad_eom_route`): файл генератора и ответы API.

Файл `eom_routes3d.json` (`cad_eom_routes3d.v1`) читается строго по схеме генератора, а наружу
отдаётся в форме трасс механики (`CadMepRoute3dPolyline`): 3D-вид рисует сети ЭОМ и СС тем же
кодом, что ВК и ОВ. Приборы, щиты и коробки - элементы `device` и `box` (короб w×h×d с осью
нормали), гильзы - `sleeve`, как у механики.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_mep import (
    ROUTE3D_MAX_APT,
    ROUTE3D_MAX_SIZE_MM,
    ROUTE3D_MAX_SUBTYPE,
    CadMepRoute3dPolyline,
)
from app.domain import JobStatus
from app.models import Job
from app.services import cad_mep as cad_mep_service

_Size = Annotated[float, Field(ge=0, le=ROUTE3D_MAX_SIZE_MM)]
_Coord = Annotated[float, Field(ge=-1e9, le=1e9)]
_MAX_TEXT = 200


class CadEomFilePolyline(BaseModel):
    """Линия сети в файле генератора: слой, вершины (x, y, z от пола этажа), сечение и изделие."""

    model_config = ConfigDict(extra="ignore")

    layer: Annotated[str, Field(min_length=1, max_length=64)]
    pts: Annotated[list[tuple[_Coord, _Coord, _Coord]], Field(min_length=2)]
    shape: Literal["round", "rect"] | None = None
    dn_mm: _Size | None = None
    w_mm: _Size | None = None
    h_mm: _Size | None = None
    item: Annotated[str, Field(max_length=_MAX_TEXT)] | None = None
    apt: Annotated[str, Field(max_length=ROUTE3D_MAX_APT)] | None = None


class CadEomFileElement(BaseModel):
    """Прибор, щит, коробка или гильза в файле генератора.

    `pos` настенного прибора - точка на лицевой поверхности стены на высоте центра, потолочного -
    точка на потолке; `axis` - нормаль в помещение (у гильзы - её ось), `d_mm` - размер вдоль оси.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["device", "box", "sleeve"]
    subtype: Annotated[str, Field(min_length=1, max_length=ROUTE3D_MAX_SUBTYPE)]
    layer: Annotated[str, Field(min_length=1, max_length=64)]
    pos: tuple[_Coord, _Coord, _Coord]
    axis: tuple[float, float, float]
    w_mm: _Size | None = None
    h_mm: _Size | None = None
    d_mm: _Size | None = None
    outer_d_mm: _Size | None = None
    length_mm: _Size | None = None
    name: Annotated[str, Field(max_length=_MAX_TEXT)] | None = None
    apt: Annotated[str, Field(max_length=ROUTE3D_MAX_APT)] | None = None


class CadEomRoutes3dFile(BaseModel):
    """Файл `eom_routes3d.json`: сети и приборы ЭОМ и СС этажа, Z от отметки этажа."""

    model_config = ConfigDict(extra="ignore")

    schema_id: Literal["cad_eom_routes3d.v1"] = Field(alias="schema")
    frame: Literal["view_dxf_mm"]
    floor_elevation_mm: int | None
    floor_height_mm: int | None
    slab_bottom_mm: int | None = None
    ceiling_mm: int | None = None
    polylines: list[CadEomFilePolyline]
    elements: list[CadEomFileElement] = Field(default_factory=list)


class CadEomElementOut(BaseModel):
    """Элемент для 3D-вида: центр (мм), единичная ось ×1000 (как у механики), габарит."""

    type: Literal["device", "box", "sleeve"]
    subtype: str
    layer: str
    pos: tuple[int, int, int]
    axis: tuple[int, int, int]
    w_mm: int | None = None
    h_mm: int | None = None
    d_mm: int | None = None
    outer_d_mm: int | None = None
    length_mm: int | None = None
    name: str | None = None
    apt: str | None = None


class CadEomPolylineOut(CadMepRoute3dPolyline):
    """Линия ЭОМ и СС для 3D-вида: форма трассы механики плюс изделие («Кабель ... в трубе Ø16»)."""

    item: Annotated[str, Field(max_length=_MAX_TEXT)] | None = None


class CadEomQuantity(BaseModel):
    """Строка ведомости кандидата: количество, длина по трассе, формула и источник."""

    model_config = ConfigDict(extra="ignore")

    system: str
    item: str
    unit: str
    qty: float
    route_m: float | None = None
    formula: str | None = None
    source: str | None = None


class CadEomRoutes3dOut(BaseModel):
    """ЭОМ и СС листа в 3D и ведомость кандидата."""

    job_id: UUID
    generator_version: str | None
    floor_elevation_mm: int | None
    floor_height_mm: int | None
    levels_elevation_mm: int | None
    levels_height_mm: int | None
    heights_match: bool
    polylines: list[CadEomPolylineOut]
    elements: list[CadEomElementOut]
    quantities: list[CadEomQuantity] = Field(default_factory=list)
    apartments: int | None = None
    issues: list[str] = Field(default_factory=list)


class CadEomJobRead(BaseModel):
    """Состояние задания ЭОМ и СС листа."""

    job_id: UUID
    status: JobStatus
    stage: str | None
    progress: float | None
    error_code: str | None
    error_message: str | None
    generator_version: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, job: Job) -> CadEomJobRead:
        version = job.payload.get("generator_version")
        return cls(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            error_code=job.error_code,
            error_message=job.error_message,
            generator_version=version if isinstance(version, str) else None,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )


def _unit(axis: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(v * v for v in axis))
    if n == 0 or not math.isfinite(n):
        return (0.0, 0.0, 1.0)
    return (axis[0] / n, axis[1] / n, axis[2] / n)


def _opt(value: float | None) -> int | None:
    return None if value is None else round(value)


def element_out(element: CadEomFileElement) -> CadEomElementOut:
    """Прибор и коробка - центр короба: точка крепления плюс половина глубины вдоль нормали."""
    ux, uy, uz = _unit(element.axis)
    x, y, z = element.pos
    if element.type != "sleeve" and element.d_mm:
        half = element.d_mm / 2
        x, y, z = x + ux * half, y + uy * half, z + uz * half
    return CadEomElementOut(
        type=element.type,
        subtype=element.subtype,
        layer=element.layer,
        pos=(round(x), round(y), round(z)),
        axis=(round(ux * 1000), round(uy * 1000), round(uz * 1000)),
        w_mm=_opt(element.w_mm),
        h_mm=_opt(element.h_mm),
        d_mm=_opt(element.d_mm),
        outer_d_mm=_opt(element.outer_d_mm),
        length_mm=_opt(element.length_mm),
        name=element.name,
        apt=element.apt,
    )


def polyline_out(line: CadEomFilePolyline) -> CadEomPolylineOut:
    return CadEomPolylineOut(
        layer=line.layer,
        pts=[(round(x), round(y), round(z)) for x, y, z in line.pts],
        shape=line.shape,
        dn_mm=_opt(line.dn_mm),
        w_mm=_opt(line.w_mm),
        h_mm=_opt(line.h_mm),
        item=line.item,
        apt=line.apt,
    )


def _quantities(candidate: dict[str, Any] | None) -> list[CadEomQuantity]:
    rows = candidate.get("quantities") if isinstance(candidate, dict) else None
    out: list[CadEomQuantity] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append(CadEomQuantity.model_validate(row))
        except ValueError:
            continue
    return out


def _issues(candidate: dict[str, Any] | None) -> list[str]:
    rows = candidate.get("issues") if isinstance(candidate, dict) else None
    return [
        str(row.get("message") or row.get("code"))[:_MAX_TEXT]
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
    ]


def routes3d_read(
    job: Job,
    data: CadEomRoutes3dFile,
    candidate: dict[str, Any] | None,
    *,
    levels_elevation_mm: int | None,
    levels_height_mm: int | None,
) -> CadEomRoutes3dOut:
    version = job.payload.get("generator_version")
    apartments = candidate.get("apartments") if isinstance(candidate, dict) else None
    return CadEomRoutes3dOut(
        job_id=job.id,
        generator_version=version if isinstance(version, str) else None,
        floor_elevation_mm=data.floor_elevation_mm,
        floor_height_mm=data.floor_height_mm,
        levels_elevation_mm=levels_elevation_mm,
        levels_height_mm=levels_height_mm,
        heights_match=cad_mep_service.heights_match(
            data.floor_elevation_mm, data.floor_height_mm, levels_elevation_mm, levels_height_mm
        ),
        polylines=[polyline_out(line) for line in data.polylines],
        elements=[element_out(element) for element in data.elements],
        quantities=_quantities(candidate),
        apartments=len(apartments) if isinstance(apartments, list) else None,
        issues=_issues(candidate),
    )
