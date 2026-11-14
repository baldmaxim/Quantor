"""Ведомости листов документов

Revision ID: 0037_sheet_registers
Revises: 0036_frame_nodes
Create Date: 2026-11-14

Подэтап С2 «ведомость ↔ листы» (ADR-0043): `sheet_registers` - ведомость листов, найденная заданием
`sheet_register_extract` на странице ревизии PDF (страницы, строки «номер - наименование» в JSONB,
повторы номеров, статус candidate / confirmed / rejected). Одна ведомость на страницу ревизии.
Значение `sheet_register_extract` типа задания (`jobs.job_type`) миграции не требует: перечисление
хранится как VARCHAR без CHECK.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0037_sheet_registers"
down_revision: str | None = "0036_frame_nodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sheet_registers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("pages", pg.JSONB(), nullable=False),
        sa.Column("entries", pg.JSONB(), nullable=False),
        sa.Column("duplicates", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("versions", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "page_index >= 0", name=op.f("ck_sheet_registers_page_index_non_negative")
        ),
        sa.CheckConstraint(
            "entry_count >= 0", name=op.f("ck_sheet_registers_entry_count_non_negative")
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'confirmed', 'rejected')",
            name=op.f("ck_sheet_registers_status_known"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(pages) = 'array'", name=op.f("ck_sheet_registers_pages_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(entries) = 'array'", name=op.f("ck_sheet_registers_entries_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(duplicates) = 'array'",
            name=op.f("ck_sheet_registers_duplicates_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(versions) = 'object'", name=op.f("ck_sheet_registers_versions_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_sheet_registers_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_sheet_registers_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sheet_registers")),
    )
    op.create_index(
        "uq_sheet_registers_page", "sheet_registers", ["revision_id", "page_index"], unique=True
    )
    op.create_index("ix_sheet_registers_project", "sheet_registers", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sheet_registers_project", table_name="sheet_registers")
    op.drop_index("uq_sheet_registers_page", table_name="sheet_registers")
    op.drop_table("sheet_registers")
