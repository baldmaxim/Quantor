"""Текст страниц PDF ревизии (В1): указатель на объект хранилища со сжатым текстом.

Сам текст - в хранилище (ADR-0002), здесь ключ, формат, версия разборщика, счётчики и
SHA-256 сжатого файла. Строка есть - ревизия доразобрана: по ней же решает повторный запуск
разбора паспортов листов. Данные контура согласованности, в итоги обмера и calc не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RevisionPageText(Base):
    __tablename__ = "revision_page_texts"
    __table_args__ = (
        CheckConstraint(
            "pages >= 0 and empty_pages >= 0 and empty_pages <= pages",
            name="page_counts_valid",
        ),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False)
    # Страницы без текстового слоя (сканы и пустые листы).
    empty_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
