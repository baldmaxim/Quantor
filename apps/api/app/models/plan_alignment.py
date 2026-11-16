"""Совмещение плана с уровнем (ADR-0043 п. 5, этап С3).

Одна строка - вид CAD подтверждённого паспорта плана этажа (лист без CAD - строка с `view = 0` и
итогом `not_run`). Преобразование `точка уровня = R(rotation_deg) · точка листа + (dx_mm, dy_mm)`
переводит мм DXF вида в систему координат уровня - эталонного плана АР секции. Кадр вида
(`origin_pt`, `mm_per_pdf_point`) сохранён, чтобы переводить и точки PDF:
`мм = ((x - origin_x) · k, (origin_y - y) · k)`. Итог считает задание `plan_align`, человек
подтверждает или отклоняет; в проверки идёт подтверждённое. Данные контура согласованности: в
итоги обмера, таблицы MEP, CAD и calc не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk


class PlanAlignment(Base):
    __tablename__ = "plan_alignments"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    passport_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("sheet_passports.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    section_mark: Mapped[str | None] = mapped_column(Text)
    building: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    level_from: Mapped[str | None] = mapped_column(Text)
    level_to: Mapped[str | None] = mapped_column(Text)
    # Задание `cad_pdf_convert`, из итога которого взяты вид и оси; без CAD - пусто.
    cad_job_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    # Эталон секции; у самого эталона - ссылка на себя.
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("plan_alignments.id", ondelete="SET NULL")
    )
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    rotation_deg: Mapped[int | None] = mapped_column(Integer)
    dx_mm: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    dy_mm: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    axes: Mapped[list[Any]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    common_axes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    agreed_axes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    residual_rms_mm: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    residual_max_mm: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    scale_source: Mapped[str | None] = mapped_column(String(24))
    mm_per_pdf_point: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    origin_pt: Mapped[list[Any] | None] = mapped_column(pg.JSONB)
    reasons: Mapped[list[Any]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    versions: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint(
            "result in ('reference', 'aligned', 'check', 'failed', 'not_run')", name="result_known"
        ),
        CheckConstraint(
            "rotation_deg is null or rotation_deg in (0, 90, 180, 270)", name="rotation_known"
        ),
        CheckConstraint(
            "scale_source is null or scale_source in ('calibration', 'dimension_chains')",
            name="scale_source_known",
        ),
        CheckConstraint("status in ('candidate', 'confirmed', 'rejected')", name="status_known"),
        CheckConstraint("jsonb_typeof(axes) = 'array'", name="axes_is_array"),
        CheckConstraint("jsonb_typeof(reasons) = 'array'", name="reasons_is_array"),
        CheckConstraint("jsonb_typeof(versions) = 'object'", name="versions_is_object"),
        Index("uq_plan_alignments_view", "passport_id", "view", unique=True),
        Index("ix_plan_alignments_project", "project_id"),
    )
