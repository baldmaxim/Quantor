"""Ведомость листов документа (ADR-0043, С2, подэтап «ведомость ↔ листы»).

Одна строка - ведомость, найденная на странице ревизии PDF, вместе со страницами-продолжениями.
Строки ведомости (номер листа, наименование, исходная строка, страница) - в JSONB `entries`: их
разбирает исполнитель заданий по тексту страниц, а человек подтверждает или отклоняет ведомость
целиком. В проверки идёт только подтверждённая. Данные контура согласованности: в итоги обмера,
таблицы MEP и calc не входят.
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


class SheetRegister(Base):
    __tablename__ = "sheet_registers"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Страница с заголовком ведомости; `pages` - она и страницы-продолжения.
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    pages: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    entries: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False)
    duplicates: Mapped[list[Any]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
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
        CheckConstraint("entry_count >= 0", name="entry_count_non_negative"),
        CheckConstraint("status in ('candidate', 'confirmed', 'rejected')", name="status_known"),
        CheckConstraint("jsonb_typeof(pages) = 'array'", name="pages_is_array"),
        CheckConstraint("jsonb_typeof(entries) = 'array'", name="entries_is_array"),
        CheckConstraint("jsonb_typeof(duplicates) = 'array'", name="duplicates_is_array"),
        CheckConstraint("jsonb_typeof(versions) = 'object'", name="versions_is_object"),
        Index("uq_sheet_registers_page", "revision_id", "page_index", unique=True),
        Index("ix_sheet_registers_project", "project_id"),
    )
