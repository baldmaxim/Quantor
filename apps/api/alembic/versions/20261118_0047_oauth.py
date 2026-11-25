"""Вход ИИ-чатов по OAuth: клиенты, выданные значения, разрешение как строка api_tokens

Revision ID: 0047_oauth
Revises: 0046_building_models
Create Date: 2026-11-18

ADR-0054. `oauth_clients` - чаты, зарегистрированные сами (RFC 7591); `oauth_tokens` - код, доступ
и обновление (в базе только sha256); `api_tokens.oauth_client_id` - разрешение человека чату.

Откат удаляет обе таблицы, колонку и строки разрешений чатам: подключённые чаты придётся
подключить заново, личные токены `qtk_` не затрагиваются.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0047_oauth"
down_revision: str | None = "0046_building_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uris", pg.JSONB(), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=32), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(redirect_uris) = 'array'",
            name=op.f("ck_oauth_clients_redirect_uris_is_array"),
        ),
        sa.CheckConstraint(
            "token_endpoint_auth_method in ('none', 'client_secret_post', 'client_secret_basic')",
            name=op.f("ck_oauth_clients_auth_method_known"),
        ),
        sa.CheckConstraint(
            "(token_endpoint_auth_method = 'none') = (client_secret_hash is null)",
            name=op.f("ck_oauth_clients_secret_matches_auth_method"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
        sa.UniqueConstraint("client_id", name=op.f("uq_oauth_clients_client_id")),
    )

    op.add_column("api_tokens", sa.Column("oauth_client_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_api_tokens_oauth_client_id_oauth_clients"),
        "api_tokens",
        "oauth_clients",
        ["oauth_client_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_challenge", sa.String(length=128), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint(
            "kind in ('code', 'access', 'refresh')", name=op.f("ck_oauth_tokens_kind_known")
        ),
        sa.CheckConstraint(
            "char_length(token_hash) = 64", name=op.f("ck_oauth_tokens_token_hash_length")
        ),
        sa.CheckConstraint(
            "(kind = 'code') = (code_challenge is not null and redirect_uri is not null)",
            name=op.f("ck_oauth_tokens_code_has_pkce"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["api_tokens.id"],
            name=op.f("fk_oauth_tokens_grant_id_api_tokens"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_tokens_token_hash")),
    )
    op.create_index("ix_oauth_tokens_grant_id", "oauth_tokens", ["grant_id"])
    op.create_index("ix_oauth_tokens_client_id", "oauth_tokens", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_client_id", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_grant_id", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.execute("DELETE FROM api_tokens WHERE oauth_client_id IS NOT NULL")
    op.drop_constraint(
        op.f("fk_api_tokens_oauth_client_id_oauth_clients"), "api_tokens", type_="foreignkey"
    )
    op.drop_column("api_tokens", "oauth_client_id")
    op.drop_table("oauth_clients")
