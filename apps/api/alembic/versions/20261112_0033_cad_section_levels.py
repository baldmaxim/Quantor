"""Уровни по разрезам АР: кандидаты высоты «чистый пол - низ плиты» и решения человека

Revision ID: 0033_cad_section_levels
Revises: 0032_sheet_passports
Create Date: 2026-11-12

`cad_section_levels` - строки уровней из выхода задания `cad_sections` (генератор разрезов движка):
отметки, высота в свету, толщина перекрытия, доказательство, разметка на странице и статус
(`candidate | accepted | rejected`) с автором и временем решения. Значение `cad_sections` типа
задания (`jobs.job_type`) миграции не требует: перечисление хранится как VARCHAR без CHECK.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0033_cad_section_levels"
down_revision: str | None = "0032_sheet_passports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cad_section_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("cut", sa.Text(), nullable=True),
        sa.Column("corps", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("elevation_mm", sa.Integer(), nullable=False),
        sa.Column("upper_elevation_mm", sa.Integer(), nullable=False),
        sa.Column("clear_height_mm", sa.Integer(), nullable=True),
        sa.Column("structure_mm", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("markup", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_cad_section_levels_seq_non_negative")),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_cad_section_levels_page_index_non_negative")
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'accepted', 'rejected')",
            name=op.f("ck_cad_section_levels_status_known"),
        ),
        sa.CheckConstraint(
            "status <> 'accepted' or clear_height_mm is not null",
            name=op.f("ck_cad_section_levels_accepted_needs_clear_height"),
        ),
        sa.CheckConstraint(
            "(status = 'candidate' and decided_by is null and decided_at is null)"
            " or (status <> 'candidate' and decided_by is not null and decided_at is not null)",
            name=op.f("ck_cad_section_levels_decided_matches_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(markup) = 'object'",
            name=op.f("ck_cad_section_levels_markup_is_object"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_section_levels_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_section_levels_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_cad_section_levels_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_section_levels")),
        sa.UniqueConstraint("job_id", "seq", name=op.f("uq_cad_section_levels_job_id_seq")),
    )
    op.create_index(
        "ix_cad_section_levels_project_elevation_status",
        "cad_section_levels",
        ["project_id", "elevation_mm", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_cad_section_levels_project_elevation_status", table_name="cad_section_levels")
    op.drop_table("cad_section_levels")
