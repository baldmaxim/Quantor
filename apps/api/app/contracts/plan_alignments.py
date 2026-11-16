"""Контракты совмещения планов с уровнем (ADR-0043, С3)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.consistency.plan_alignment import AlignResult, AlignScaleSource

BULK_MAX: Final = 2000


class AlignmentStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PlanAlignmentOut(BaseModel):
    """Совмещение вида плана с уровнем: `точка уровня = R(rotation_deg) · точка листа + (dx, dy)`.

    Точка листа - мм DXF вида CAD; из точки PDF (pt от левого верхнего угла страницы) она
    получается по кадру вида: `((x - origin_x) · k, (origin_y - y) · k)`, `k = mm_per_pdf_point`.
    """

    id: UUID
    passport_id: UUID
    revision_id: UUID
    file_name: str
    page_index: int
    view: int
    section_mark: str | None
    building: str | None
    section: str | None
    level_from: str | None
    level_to: str | None
    cad_job_id: UUID | None
    reference_id: UUID | None
    result: AlignResult
    rotation_deg: int | None
    dx_mm: float | None
    dy_mm: float | None
    axes: list[str]
    common_axes: int
    agreed_axes: int
    residual_rms_mm: float | None
    residual_max_mm: float | None
    scale_source: AlignScaleSource | None
    mm_per_pdf_point: float | None
    origin_pt: list[float] | None
    reasons: list[str]
    status: AlignmentStatus
    confirmed_at: datetime | None


class AlignRunSummary(BaseModel):
    """Итог последнего задания совмещения; чисел, которых нет в итоге, - null."""

    job_id: UUID
    status: str
    progress: float | None
    stage: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    plans: int | None
    views: int | None
    without_cad: int | None
    aligned: int | None
    check: int | None
    failed: int | None
    not_run: int | None
    versions: dict[str, str]


class AlignParamsOut(BaseModel):
    """Параметры правила совмещения действующей версии."""

    axis_agree_mm: float
    residual_check_mm: float


class PlanAlignmentsOut(BaseModel):
    alignments: list[PlanAlignmentOut]
    last_run: AlignRunSummary | None
    params: AlignParamsOut
    versions: dict[str, str]


class PlanAlignmentBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=BULK_MAX)
    status: AlignmentStatus


class PlanAlignmentBulkOut(BaseModel):
    updated: int
