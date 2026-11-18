"""Персональные API-токены `qtk_…` (ADR-0051).

Токен выпускает пользователь у себя в профиле: он привязан к пространству, ограничен областью
(`scopes`, в версии 1 — `["tender"]`) и не даёт ничего сверх прав роли владельца. Сам токен виден
один раз при создании; в базе — только sha256 и первые 12 знаков для показа в списке.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

API_TOKEN_NAME_MAX = 100
API_TOKEN_PREFIX_LENGTH = 12


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(API_TOKEN_NAME_MAX), nullable=False)
    # Первые 12 знаков токена: по ним человек узнаёт свой токен в списке.
    prefix: Mapped[str] = mapped_column(String(API_TOKEN_PREFIX_LENGTH), nullable=False)
    # sha256 токена, hex. Сам токен не хранится.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(pg.JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Пусто — бессрочный.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Разрешение ИИ-чату по OAuth (ADR-0054): значения `qtk_` у такой строки нет, чат ходит
    # своими `qoa_` из `oauth_tokens`; отзыв строки гасит их все.
    oauth_client_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("oauth_clients.id", ondelete="CASCADE")
    )

    __table_args__ = (
        Index("ix_api_tokens_user_id_workspace_id", "user_id", "workspace_id"),
        CheckConstraint("jsonb_typeof(scopes) = 'array'", name="scopes_is_array"),
        CheckConstraint("char_length(token_hash) = 64", name="token_hash_length"),
    )
