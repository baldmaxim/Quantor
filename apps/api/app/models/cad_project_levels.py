"""Уровень проекта и решения по отверстиям плиты в 3D-виде этажа (ADR-0039).

`cad_project_levels` — толщина плиты из разрезов, введённая человеком один раз на проект, с листом
разреза; `cad_slab_hole_decisions` — решение человека по отверстию-кандидату плиты листа. Это
данные человека, а не результат скрипта; в итоги обмера, MEP и calc они не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

SLAB_SOURCE_REF_MAX = 200
HOLE_KEY_MAX = 32


class CadProjectLevels(Base):
    """Уровни проекта: толщина плиты из разреза и лист-источник."""

    __tablename__ = "cad_project_levels"

    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    slab_thickness_mm: Mapped[int | None] = mapped_column(Integer)
    # Лист разреза: «АР1.1 л. 45, разрез 4-4».
    slab_source_ref: Mapped[str | None] = mapped_column(String(SLAB_SOURCE_REF_MAX))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "slab_thickness_mm is null or slab_thickness_mm between 100 and 1000",
            name="slab_thickness_range",
        ),
        CheckConstraint(
            "slab_thickness_mm is null or (slab_source_ref is not null and slab_source_ref <> '')",
            name="slab_source_ref_required",
        ),
    )


class CadSlabHoleDecision(Base):
    """Решение человека по отверстию плиты листа: включено (есть отверстие) или выключено."""

    __tablename__ = "cad_slab_hole_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    # Стабильный ключ геометрии отверстия (хеш центроида и площади).
    hole_key: Mapped[str] = mapped_column(String(HOLE_KEY_MAX), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "page_index",
            "view",
            "hole_key",
            name="uq_cad_slab_hole_decisions_sheet_key",
        ),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint(
            f"char_length(hole_key) between 1 and {HOLE_KEY_MAX}", name="hole_key_length"
        ),
    )
