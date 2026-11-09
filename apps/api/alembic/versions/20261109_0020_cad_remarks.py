"""Замечания проверяющего к видам результата CAD

Revision ID: 0020_cad_remarks
Revises: 0019_tender_versions
Create Date: 2026-11-09

QA-контур PDF -> CAD: замечания к виду хранятся на сервере, а не в браузере. Одна таблица
`cad_remarks`: привязка к заданию, попытке, странице и виду, клиентский идентификатор замечания
(`remark_key`), тип, комментарий, статус и прямоугольник в pt PDF. Замечание — след человека, а не
измерение и не приёмка.

Откат удаляет таблицу вместе с замечаниями: до этой ревизии они жили только в браузерах и
переносились файлом `quantor.cad-remarks.v1`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_cad_remarks"
down_revision: str | None = "0019_tender_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Те же значения, что `REMARK_TYPE_VALUES` в `app/models/cad_remark.py`.
REMARK_TYPES = (
    "missing_wall",
    "false_wall",
    "missing_door",
    "door_geometry",
    "missing_gate",
    "missing_glazing",
    "monolith",
    "room_boundary",
    "wrong_class",
    "other",
)


def upgrade() -> None:
    types = ", ".join(f"'{value}'" for value in REMARK_TYPES)
    op.create_table(
        "cad_remarks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("dxf_sha256", sa.Text(), nullable=True),
        sa.Column("remark_key", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("bbox_x0", sa.Float(), nullable=False),
        sa.Column("bbox_y0", sa.Float(), nullable=False),
        sa.Column("bbox_x1", sa.Float(), nullable=False),
        sa.Column("bbox_y1", sa.Float(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_cad_remarks_attempt_positive")),
        sa.CheckConstraint("page_index >= 0", name=op.f("ck_cad_remarks_page_index_non_negative")),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_remarks_view_non_negative")),
        sa.CheckConstraint(
            "dxf_sha256 is null or dxf_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cad_remarks_dxf_sha256_hex"),
        ),
        sa.CheckConstraint(
            "char_length(remark_key) between 1 and 64",
            name=op.f("ck_cad_remarks_remark_key_length"),
        ),
        sa.CheckConstraint(f"type in ({types})", name=op.f("ck_cad_remarks_type_known")),
        sa.CheckConstraint(
            "char_length(comment) <= 4000", name=op.f("ck_cad_remarks_comment_length")
        ),
        sa.CheckConstraint(
            "reviewer is null or char_length(reviewer) <= 200",
            name=op.f("ck_cad_remarks_reviewer_length"),
        ),
        sa.CheckConstraint(
            "status in ('open', 'resolved')", name=op.f("ck_cad_remarks_status_known")
        ),
        sa.CheckConstraint(
            "bbox_x0 >= 0 and bbox_y0 >= 0 and bbox_x1 > bbox_x0 and bbox_y1 > bbox_y0",
            name=op.f("ck_cad_remarks_bbox_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_remarks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_remarks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_remarks_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_cad_remarks_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_remarks")),
        sa.UniqueConstraint(
            "job_id",
            "attempt",
            "page_index",
            "view",
            "remark_key",
            name="uq_cad_remarks_job_attempt_page_view_key",
        ),
    )
    op.create_index(op.f("ix_cad_remarks_created_at"), "cad_remarks", ["created_at"])
    op.create_index(
        "ix_cad_remarks_job_attempt_page_view",
        "cad_remarks",
        ["job_id", "attempt", "page_index", "view"],
    )


def downgrade() -> None:
    op.drop_table("cad_remarks")
