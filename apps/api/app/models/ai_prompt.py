"""Версии промтов ИИ-проверки вида CAD: правка в админке, ссылка на версию у каждого прогона.

Версия неизменяема по смыслу (текст не правится, правка - новая версия), менять можно только статус.
На роль - ровно одна активная версия (частичный уникальный индекс).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, uuid_pk

AI_PROMPT_ROLES: tuple[str, ...] = ("corrector", "verifier")
AI_PROMPT_STATUSES: tuple[str, ...] = ("draft", "active", "archived")
# Предел текста промта в байтах UTF-8.
AI_PROMPT_MAX_BYTES = 64 * 1024
AI_PROMPT_MAX_NOTE = 500


class AiPromptVersion(CreatedAtMixin, Base):
    __tablename__ = "ai_prompt_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    # NULL - системная версия (из миграции).
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("role", "version", name="uq_ai_prompt_versions_role_version"),
        Index(
            "uq_ai_prompt_versions_active",
            "role",
            unique=True,
            postgresql_where=sql_text("status = 'active'"),
        ),
        CheckConstraint("role in ('corrector', 'verifier')", name="role_valid"),
        CheckConstraint("status in ('draft', 'active', 'archived')", name="status_valid"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            f"octet_length(text) between 1 and {AI_PROMPT_MAX_BYTES}", name="text_size"
        ),
        CheckConstraint(f"char_length(note) <= {AI_PROMPT_MAX_NOTE}", name="note_length"),
    )
