"""Локальный вход: допуск личности и пароли

Revision ID: 0018_local_auth
Revises: 0017_calc_vk_passports
Create Date: 2026-09-29

Локальная аутентификация с одобрением администратора (ADR-0031):

- `user_identities.approval_status` — допуск к порталу: `pending` / `approved` / `rejected`.
  Существующие личности получают `approved` умолчанием колонки: их допускал провайдер;
- `local_credentials` — хеш пароля argon2id, требование смены пароля, счётчик неудач и срок
  блокировки. Одна строка на личность, удаляется вместе с ней.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_local_auth"
down_revision: str | None = "0017_calc_vk_passports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL_STATUSES = ("pending", "approved", "rejected")


def upgrade() -> None:
    op.add_column(
        "user_identities",
        sa.Column(
            "approval_status",
            sa.Enum(*APPROVAL_STATUSES, name="approval_status", native_enum=False, length=32),
            server_default="approved",
            nullable=False,
        ),
    )
    op.create_table(
        "local_credentials",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_local_credentials_failed_attempts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_identities.id"],
            name=op.f("fk_local_credentials_user_id_user_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_local_credentials")),
    )
    op.create_index(
        op.f("ix_local_credentials_created_at"), "local_credentials", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_local_credentials_created_at"), table_name="local_credentials")
    op.drop_table("local_credentials")
    op.drop_column("user_identities", "approval_status")
