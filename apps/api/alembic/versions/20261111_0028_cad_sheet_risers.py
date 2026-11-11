"""Реестр стояков листа CAD по проекту ИОС: вход задания трасс cad_mep.v6

Revision ID: 0028_cad_sheet_risers
Revises: 0027_cad_floor3d
Create Date: 2026-11-11

ADR-0041: `cad_sheet_risers` - реестр стояков листа (ревизия, страница, вид), который вводит или
подтверждает человек по проекту ИОС; список записей контракта `cad_risers.v1` лежит в JSONB.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0028_cad_sheet_risers"
down_revision: str | None = "0027_cad_floor3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cad_sheet_risers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("risers", pg.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
            "page_index >= 0", name=op.f("ck_cad_sheet_risers_page_index_non_negative")
        ),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_sheet_risers_view_non_negative")),
        sa.CheckConstraint(
            "jsonb_typeof(risers) = 'array'", name=op.f("ck_cad_sheet_risers_risers_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_sheet_risers_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_sheet_risers")),
        sa.UniqueConstraint("revision_id", "page_index", "view", name="uq_cad_sheet_risers_sheet"),
    )


def downgrade() -> None:
    op.drop_table("cad_sheet_risers")
