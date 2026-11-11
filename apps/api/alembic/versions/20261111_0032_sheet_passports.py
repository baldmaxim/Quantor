"""Паспорт листа: раздел, тип, корпус, секция и уровни по текстовому слою PDF

Revision ID: 0032_sheet_passports
Revises: 0031_cad_finish_reveals
Create Date: 2026-11-11

ADR-0043, этап С1: `sheet_passports` - кандидат паспорта на страницу ревизии с доказательствами
по полям (`evidence`), версиями разборщика и словарей (`versions`) и статусом подтверждения.
Значение `sheet_passport_extract` типа задания (`jobs.job_type`) миграции не требует:
перечисление хранится как VARCHAR без CHECK.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0032_sheet_passports"
down_revision: str | None = "0031_cad_finish_reveals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sheet_passports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("section_mark", sa.Text(), nullable=True),
        sa.Column("sheet_kind", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("building", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("level_from", sa.Text(), nullable=True),
        sa.Column("level_to", sa.Text(), nullable=True),
        sa.Column("level_from_ordinal", sa.Integer(), nullable=True),
        sa.Column("level_to_ordinal", sa.Integer(), nullable=True),
        sa.Column("elevation_m", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("sheet_number", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column(
            "evidence", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "versions", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
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
        sa.CheckConstraint("page_index >= 0", name=op.f("ck_sheet_passports_page_index_non_negative")),
        sa.CheckConstraint(
            "status in ('candidate', 'confirmed', 'rejected')",
            name=op.f("ck_sheet_passports_status_known"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object'",
            name=op.f("ck_sheet_passports_evidence_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(versions) = 'object'",
            name=op.f("ck_sheet_passports_versions_is_object"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_sheet_passports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_sheet_passports_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sheet_passports")),
        sa.UniqueConstraint("revision_id", "page_index", name="uq_sheet_passports_revision_id_page"),
    )
    op.create_index(
        "ix_sheet_passports_project_revision_page",
        "sheet_passports",
        ["project_id", "revision_id", "page_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_sheet_passports_project_revision_page", table_name="sheet_passports")
    op.drop_table("sheet_passports")
