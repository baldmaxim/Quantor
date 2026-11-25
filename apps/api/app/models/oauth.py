"""Вход ИИ-чатов по OAuth 2.1 (ADR-0054): клиенты и выданные значения.

Чат (Claude, ChatGPT) регистрируется сам (`oauth_clients`, RFC 7591), человек разрешает ему доступ
на странице портала, и разрешение становится строкой `api_tokens` с `oauth_client_id`: тот же
список «Доступ», тот же отзыв, те же области и пространство. `oauth_tokens` - выданные чату
значения: код (минуты), доступ (час) и обновление (недели), в базе только sha256.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

OAUTH_CLIENT_NAME_MAX = 200
OAUTH_TOKEN_KINDS = ("code", "access", "refresh")
OAUTH_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Выдаётся порталом при регистрации: `qoc_` и случайная часть.
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_name: Mapped[str] = mapped_column(String(OAUTH_CLIENT_NAME_MAX), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(pg.JSONB, nullable=False)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # Только у клиента с секретом; sha256, сам секрет показан один раз в ответе регистрации.
    client_secret_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("jsonb_typeof(redirect_uris) = 'array'", name="redirect_uris_is_array"),
        CheckConstraint(
            "token_endpoint_auth_method in ('none', 'client_secret_post', 'client_secret_basic')",
            name="auth_method_known",
        ),
        CheckConstraint(
            "(token_endpoint_auth_method = 'none') = (client_secret_hash is null)",
            name="secret_matches_auth_method",
        ),
    )


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Разрешение человека: строка `api_tokens`; её отзыв гасит все значения сразу.
    grant_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("api_tokens.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Код и обновление одноразовые: время обмена. Повтор после этого - признак кражи.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Только у кода: PKCE (S256) и адрес возврата, с которым его просили.
    code_challenge: Mapped[str | None] = mapped_column(String(128))
    redirect_uri: Mapped[str | None] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_oauth_tokens_grant_id", "grant_id"),
        Index("ix_oauth_tokens_client_id", "client_id"),
        CheckConstraint("kind in ('code', 'access', 'refresh')", name="kind_known"),
        CheckConstraint("char_length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint(
            "(kind = 'code') = (code_challenge is not null and redirect_uri is not null)",
            name="code_has_pkce",
        ),
    )
