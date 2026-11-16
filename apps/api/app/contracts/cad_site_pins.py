"""Контракт ручной привязки корпуса к площадке по двум парам точек (ADR-0052).

Точки - в мм кадра вида своего листа (система DXF листа, как контуры этажей в
`/cad/building3d`). Перевод вида источника в вид цели выводит сервер; масштаба и зеркала в нём нет.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.cad_site_pin import MAX_SITE_PIN_TEXT, CadSitePin

# Координаты листа в мм: разумный предел отсекает мусор и бесконечности.
MAX_COORD_MM = 1.0e8


class CadSiteSheetRef(BaseModel):
    """Лист в сборке 3D: ревизия документа, страница, вид (как в `CadBuilding3dFloorRead`)."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    page_index: int = Field(ge=0)
    view: int = Field(ge=0)


class CadSitePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_mm: float = Field(ge=-MAX_COORD_MM, le=MAX_COORD_MM, allow_inf_nan=False)
    y_mm: float = Field(ge=-MAX_COORD_MM, le=MAX_COORD_MM, allow_inf_nan=False)


class CadSitePinCreate(BaseModel):
    """Две точки листа корпуса (`source`) и те же две точки листа площадки (`target`)."""

    model_config = ConfigDict(extra="forbid")

    source: CadSiteSheetRef
    target: CadSiteSheetRef
    source_points: list[CadSitePoint] = Field(min_length=2, max_length=2)
    target_points: list[CadSitePoint] = Field(min_length=2, max_length=2)
    note: str | None = Field(default=None, max_length=MAX_SITE_PIN_TEXT)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CadSitePinRevoke(BaseModel):
    """Отзыв привязки; причина необязательна."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=MAX_SITE_PIN_TEXT)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CadSitePinRead(BaseModel):
    id: UUID
    source: CadSiteSheetRef
    target: CadSiteSheetRef
    source_points: list[CadSitePoint]
    target_points: list[CadSitePoint]
    # Перевод вида источника в вид цели: q = R(rotation_deg) · p + (offset_x_mm, offset_y_mm).
    rotation_deg: float
    offset_x_mm: float
    offset_y_mm: float
    # Расстояние между точками источника и разность длин двух отрезков, мм.
    baseline_mm: float
    residual_mm: float
    note: str | None
    created_by: UUID
    created_by_name: str | None
    created_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


class CadSitePinsRead(BaseModel):
    """Действующие привязки проекта (отозванные в список не входят)."""

    items: list[CadSitePinRead]


def site_pin_read(pin: CadSitePin, author: str | None) -> CadSitePinRead:
    return CadSitePinRead(
        id=pin.id,
        source=CadSiteSheetRef(
            revision_id=pin.source_revision_id,
            page_index=pin.source_page_index,
            view=pin.source_view,
        ),
        target=CadSiteSheetRef(
            revision_id=pin.target_revision_id,
            page_index=pin.target_page_index,
            view=pin.target_view,
        ),
        source_points=[
            CadSitePoint(x_mm=pin.source_x1_mm, y_mm=pin.source_y1_mm),
            CadSitePoint(x_mm=pin.source_x2_mm, y_mm=pin.source_y2_mm),
        ],
        target_points=[
            CadSitePoint(x_mm=pin.target_x1_mm, y_mm=pin.target_y1_mm),
            CadSitePoint(x_mm=pin.target_x2_mm, y_mm=pin.target_y2_mm),
        ],
        rotation_deg=pin.rotation_deg,
        offset_x_mm=pin.offset_x_mm,
        offset_y_mm=pin.offset_y_mm,
        baseline_mm=pin.baseline_mm,
        residual_mm=pin.residual_mm,
        note=pin.note,
        created_by=pin.created_by,
        created_by_name=author,
        created_at=pin.created_at,
        revoked_at=pin.revoked_at,
        revoke_reason=pin.revoke_reason,
    )
