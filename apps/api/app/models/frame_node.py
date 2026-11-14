"""Каркас здания (ADR-0043, этап С2): корпус → секция → уровень на проект.

Одна таблица узлов с видом и родителем. Кандидатов собирает сервис из подтверждённых паспортов
листов, подтверждает или отклоняет человек; человек может добавить узел сам (`origin = manual`).
Корпус или секция `NULL` - «не указаны» на листах. Данные контура согласованности: в итоги
обмера, таблицы MEP и calc не входят.
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


class FrameNode(Base):
    __tablename__ = "frame_nodes"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("frame_nodes.id", ondelete="CASCADE")
    )
    # Ключ узла как на листах: корпус и секция (NULL - не указаны), код уровня («3 этаж»).
    building: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    # Только у уровня; не определённое - NULL, а не 0.
    ordinal: Mapped[int | None] = mapped_column(Integer)
    elevation_m: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    # Высота «пол - пол», введённая человеком; выведенная из отметок не хранится.
    height_m: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    # Паспорта-источники, источники отметки и поля, правленные человеком (`manual`).
    evidence: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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
        CheckConstraint("kind in ('building', 'section', 'level')", name="kind_known"),
        CheckConstraint("status in ('candidate', 'confirmed', 'rejected')", name="status_known"),
        CheckConstraint("origin in ('passports', 'manual')", name="origin_known"),
        CheckConstraint("(kind = 'building') = (parent_id is null)", name="parent_matches_kind"),
        CheckConstraint("(kind = 'level') = (code is not null)", name="code_only_level"),
        CheckConstraint(
            "kind = 'level' or (ordinal is null and elevation_m is null and height_m is null)",
            name="level_fields_only_level",
        ),
        CheckConstraint("kind <> 'building' or section is null", name="building_has_no_section"),
        CheckConstraint("height_m is null or height_m > 0", name="height_positive"),
        CheckConstraint("jsonb_typeof(evidence) = 'object'", name="evidence_is_object"),
        CheckConstraint("jsonb_typeof(versions) = 'object'", name="versions_is_object"),
        # Один узел на ключ: NULL корпуса или секции - тоже значение («не указан»).
        Index(
            "uq_frame_nodes_key",
            "project_id",
            "kind",
            text("coalesce(building, '')"),
            text("coalesce(section, '')"),
            text("coalesce(code, '')"),
            unique=True,
        ),
        Index("ix_frame_nodes_parent", "parent_id"),
    )
