"""Уровни по разрезам АР: кандидаты высоты «чистый пол - низ плиты», решения человека.

Кандидата выдаёт задание `cad_sections` (генератор распознаёт разрезы по тексту PDF), принимает или
отклоняет человек. Это данные уровней проекта, а не измерение: в итоги обмера, таблицы MEP и calc
они не входят. Принятая высота уходит в запуск трасс механики (`cad_mep`) ключом
`--clear-height-mm`. Разметка (`markup`) - нормализованные координаты 0..1 от левого верхнего
угла отображаемой страницы (ADR-0008); замечания генератора в базе не хранятся - они в артефакте.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

SECTION_LEVEL_STATUSES: tuple[str, ...] = ("candidate", "accepted", "rejected")

_STATUS_CHECK = "status in (" + ", ".join(f"'{value}'" for value in SECTION_LEVEL_STATUSES) + ")"


class CadSectionLevel(Base):
    __tablename__ = "cad_section_levels"

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
    # Порядок уровня в выходе генератора.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cut: Mapped[str | None] = mapped_column(Text)
    corps: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    floor: Mapped[int | None] = mapped_column(Integer)
    # Отметка чистого пола и верхняя отметка (низ плиты перекрытия выше), мм.
    elevation_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    upper_elevation_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    clear_height_mm: Mapped[int | None] = mapped_column(Integer)
    structure_mm: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    markup: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_cad_section_levels_job_id_seq"),
        Index(
            "ix_cad_section_levels_project_elevation_status", "project_id", "elevation_mm", "status"
        ),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint(_STATUS_CHECK, name="status_known"),
        CheckConstraint(
            "status <> 'accepted' or clear_height_mm is not null",
            name="accepted_needs_clear_height",
        ),
        CheckConstraint(
            "(status = 'candidate' and decided_by is null and decided_at is null)"
            " or (status <> 'candidate' and decided_by is not null and decided_at is not null)",
            name="decided_matches_status",
        ),
        CheckConstraint("jsonb_typeof(markup) = 'object'", name="markup_is_object"),
    )
