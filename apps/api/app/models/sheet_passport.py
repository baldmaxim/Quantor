"""Паспорт листа: раздел, тип, корпус, секция и уровни по текстовому слою PDF (ADR-0043, С1).

Кандидата собирает задание `sheet_passport_extract`, подтверждает человек. Привязка - к странице
ревизии: одна запись на лист. Данные контура согласованности, в итоги обмера, таблицы MEP и calc
не входят.
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
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk


class SheetPassport(Base):
    __tablename__ = "sheet_passports"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)

    # Поля паспорта; не определённое - NULL, а не 0 и не догадка.
    section_mark: Mapped[str | None] = mapped_column(Text)
    sheet_kind: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(Text)
    building: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    level_from: Mapped[str | None] = mapped_column(Text)
    level_to: Mapped[str | None] = mapped_column(Text)
    level_from_ordinal: Mapped[int | None] = mapped_column(Integer)
    level_to_ordinal: Mapped[int | None] = mapped_column(Integer)
    elevation_m: Mapped[float | None] = mapped_column(pg.DOUBLE_PRECISION)
    code: Mapped[str | None] = mapped_column(Text)
    sheet_number: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    # {поле: {source, snippet}}; source = manual - поле правил человек, разбор его не трогает.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Версии разборщика и словарей, по которым собран кандидат.
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
        UniqueConstraint("revision_id", "page_index", name="uq_sheet_passports_revision_id_page"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("status in ('candidate', 'confirmed', 'rejected')", name="status_known"),
        CheckConstraint("jsonb_typeof(evidence) = 'object'", name="evidence_is_object"),
        CheckConstraint("jsonb_typeof(versions) = 'object'", name="versions_is_object"),
        Index(
            "ix_sheet_passports_project_revision_page", "project_id", "revision_id", "page_index"
        ),
    )
