"""Виды фасадов АР: кандидаты задания `cad_facades`, решения человека (ADR-0048).

Кандидата выдаёт генератор `cad_facades` (векторы и текст PDF, без растра и OCR), принимает или
отклоняет человек. Это данные вида фасада, а не измерение: в итоги обмера, таблицы MEP и calc они
не входят, а окна вида в проёмы плана на этом шаге не переносятся. Принять можно только вид с
вертикальной привязкой по отметкам (`fitted` или `weak`). Координаты (`bbox`, оси, отметки,
этажи, окна) - доли отображаемой страницы 0..1 от левого верхнего угла (ADR-0008) и миллиметры
по привязке генератора; JSONB - данные вида, бинарного содержимого в базе нет.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

FACADE_VIEW_STATUSES: tuple[str, ...] = ("candidate", "accepted", "rejected")
FACADE_BODIES: tuple[str, ...] = ("vector", "raster")
FACADE_SCALE_STATUSES: tuple[str, ...] = ("fitted", "weak", "text_only", "none")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in (" + ", ".join(f"'{value}'" for value in values) + ")"


class CadFacadeView(Base):
    __tablename__ = "cad_facade_views"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    # Порядок вида в выходе генератора.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Идентификатор вида из файла генератора («p36v1»).
    view_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    axis_from: Mapped[str | None] = mapped_column(Text)
    axis_to: Mapped[str | None] = mapped_column(Text)
    corps: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(String(8), nullable=False)
    scale_status: Mapped[str] = mapped_column(String(16), nullable=False)
    mm_per_pt: Mapped[float | None] = mapped_column(Float)
    residual_mm: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    axes: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    marks: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    floors: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    windows: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    window_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_cad_facade_views_job_id_seq"),
        Index("ix_cad_facade_views_project_revision", "project_id", "revision_id", "page_index"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("window_count >= 0", name="window_count_non_negative"),
        CheckConstraint(_in("status", FACADE_VIEW_STATUSES), name="status_known"),
        CheckConstraint(_in("body", FACADE_BODIES), name="body_known"),
        CheckConstraint(_in("scale_status", FACADE_SCALE_STATUSES), name="scale_status_known"),
        CheckConstraint(
            "status <> 'accepted' or scale_status in ('fitted', 'weak')",
            name="accepted_needs_scale",
        ),
        CheckConstraint(
            "(status = 'candidate' and decided_by is null and decided_at is null)"
            " or (status <> 'candidate' and decided_by is not null and decided_at is not null)",
            name="decided_matches_status",
        ),
        CheckConstraint("jsonb_typeof(bbox) = 'array'", name="bbox_is_array"),
        CheckConstraint("jsonb_typeof(axes) = 'array'", name="axes_is_array"),
        CheckConstraint("jsonb_typeof(marks) = 'array'", name="marks_is_array"),
        CheckConstraint("jsonb_typeof(floors) = 'array'", name="floors_is_array"),
        CheckConstraint("jsonb_typeof(windows) = 'array'", name="windows_is_array"),
    )
