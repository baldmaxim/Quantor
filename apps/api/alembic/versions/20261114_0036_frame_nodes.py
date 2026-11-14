"""Каркас здания: узлы корпус / секция / уровень

Revision ID: 0036_frame_nodes
Revises: 0035_doc_questions
Create Date: 2026-11-14

Этап С2 плана согласованности комплекта (ADR-0043): `frame_nodes` - узлы каркаса здания проекта
(вид, родитель, корпус, секция, код уровня, номер, отметка, высота, статус candidate / confirmed /
rejected, происхождение passports / manual, доказательства). Уникальный индекс по выражению даёт
один узел на ключ; NULL корпуса или секции - «не указан» и тоже значение ключа.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0036_frame_nodes"
down_revision: str | None = "0035_doc_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "frame_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("building", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=True),
        sa.Column("elevation_m", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("height_m", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("evidence", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
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
            "kind in ('building', 'section', 'level')", name=op.f("ck_frame_nodes_kind_known")
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'confirmed', 'rejected')",
            name=op.f("ck_frame_nodes_status_known"),
        ),
        sa.CheckConstraint(
            "origin in ('passports', 'manual')", name=op.f("ck_frame_nodes_origin_known")
        ),
        sa.CheckConstraint(
            "(kind = 'building') = (parent_id is null)",
            name=op.f("ck_frame_nodes_parent_matches_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'level') = (code is not null)", name=op.f("ck_frame_nodes_code_only_level")
        ),
        sa.CheckConstraint(
            "kind = 'level' or (ordinal is null and elevation_m is null and height_m is null)",
            name=op.f("ck_frame_nodes_level_fields_only_level"),
        ),
        sa.CheckConstraint(
            "kind <> 'building' or section is null",
            name=op.f("ck_frame_nodes_building_has_no_section"),
        ),
        sa.CheckConstraint(
            "height_m is null or height_m > 0", name=op.f("ck_frame_nodes_height_positive")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object'", name=op.f("ck_frame_nodes_evidence_is_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(versions) = 'object'", name=op.f("ck_frame_nodes_versions_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_frame_nodes_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["frame_nodes.id"],
            name=op.f("fk_frame_nodes_parent_id_frame_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_frame_nodes")),
    )
    op.create_index(
        "uq_frame_nodes_key",
        "frame_nodes",
        [
            "project_id",
            "kind",
            sa.text("coalesce(building, '')"),
            sa.text("coalesce(section, '')"),
            sa.text("coalesce(code, '')"),
        ],
        unique=True,
    )
    op.create_index("ix_frame_nodes_parent", "frame_nodes", ["parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_frame_nodes_parent", table_name="frame_nodes")
    op.drop_index("uq_frame_nodes_key", table_name="frame_nodes")
    op.drop_table("frame_nodes")
