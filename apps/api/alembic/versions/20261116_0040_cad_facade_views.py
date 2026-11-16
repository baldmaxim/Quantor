"""Виды фасадов АР: кандидаты задания `cad_facades` и решения человека

Revision ID: 0040_cad_facade_views
Revises: 0039_section_levels_auto_accept
Create Date: 2026-11-16

ADR-0048: `cad_facade_views` - строки видов из выхода задания `cad_facades` (генератор фасадов
движка): заголовок, оси, корпус и секция, тело вида (`vector | raster`), статус привязки по
отметкам, оси, отметки, этажи и окна вида (JSONB, доли страницы и мм) и решение человека
(`candidate | accepted | rejected`) с автором и временем. Принять можно только вид с привязкой
`fitted` или `weak`. Значение `cad_facades` типа задания (`jobs.job_type`) миграции не требует:
перечисление хранится как VARCHAR без CHECK.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0040_cad_facade_views"
down_revision: str | None = "0039_section_levels_auto_accept"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "cad_facade_views"


def upgrade() -> None:
    op.create_table(
        _T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("axis_from", sa.Text(), nullable=True),
        sa.Column("axis_to", sa.Text(), nullable=True),
        sa.Column("corps", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("body", sa.String(length=8), nullable=False),
        sa.Column("scale_status", sa.String(length=16), nullable=False),
        sa.Column("mm_per_pt", sa.Float(), nullable=True),
        sa.Column("residual_mm", sa.Float(), nullable=True),
        sa.Column("bbox", pg.JSONB(), nullable=False),
        sa.Column("axes", pg.JSONB(), nullable=False),
        sa.Column("marks", pg.JSONB(), nullable=False),
        sa.Column("floors", pg.JSONB(), nullable=False),
        sa.Column("windows", pg.JSONB(), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_cad_facade_views_seq_non_negative")),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_cad_facade_views_page_index_non_negative")
        ),
        sa.CheckConstraint(
            "window_count >= 0", name=op.f("ck_cad_facade_views_window_count_non_negative")
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'accepted', 'rejected')",
            name=op.f("ck_cad_facade_views_status_known"),
        ),
        sa.CheckConstraint(
            "body in ('vector', 'raster')", name=op.f("ck_cad_facade_views_body_known")
        ),
        sa.CheckConstraint(
            "scale_status in ('fitted', 'weak', 'text_only', 'none')",
            name=op.f("ck_cad_facade_views_scale_status_known"),
        ),
        sa.CheckConstraint(
            "status <> 'accepted' or scale_status in ('fitted', 'weak')",
            name=op.f("ck_cad_facade_views_accepted_needs_scale"),
        ),
        sa.CheckConstraint(
            "(status = 'candidate' and decided_by is null and decided_at is null)"
            " or (status <> 'candidate' and decided_by is not null and decided_at is not null)",
            name=op.f("ck_cad_facade_views_decided_matches_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(bbox) = 'array'", name=op.f("ck_cad_facade_views_bbox_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(axes) = 'array'", name=op.f("ck_cad_facade_views_axes_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(marks) = 'array'", name=op.f("ck_cad_facade_views_marks_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(floors) = 'array'", name=op.f("ck_cad_facade_views_floors_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(windows) = 'array'", name=op.f("ck_cad_facade_views_windows_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_facade_views_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_facade_views_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_cad_facade_views_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_facade_views")),
        sa.UniqueConstraint("job_id", "seq", name=op.f("uq_cad_facade_views_job_id_seq")),
    )
    op.create_index(
        "ix_cad_facade_views_project_revision", _T, ["project_id", "revision_id", "page_index"]
    )


def downgrade() -> None:
    op.drop_index("ix_cad_facade_views_project_revision", table_name=_T)
    op.drop_table(_T)
