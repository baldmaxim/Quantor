"""Параметры конструкций и уровни листа в контуре «Конструкции CAD»

Revision ID: 0025_cad_constructions
Revises: 0024_pdf_status_attached
Create Date: 2026-11-11

ADR-0038 п. 4: `cad_construction_props` хранит параметры конструкции (материал, блок, шов,
назначение и т. п.) по ключу листа и id конструкции из walls.json; `cad_sheet_levels` — высоты
листа, переопределённые человеком. Привязка к листу (ревизия, страница, вид), а не к заданию:
id конструкции стабилен, и параметры переходят на новое задание того же листа.

Значение `cad_walls` типа задания (`jobs.job_type`) миграции не требует: перечисление хранится
как VARCHAR без CHECK.

Откат удаляет обе таблицы вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_cad_constructions"
down_revision: str | None = "0024_pdf_status_attached"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cad_construction_props",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("construction_key", sa.String(length=32), nullable=False),
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("accepted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "page_index >= 0", name=op.f("ck_cad_construction_props_page_index_non_negative")
        ),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_construction_props_view_non_negative")),
        sa.CheckConstraint(
            "char_length(construction_key) between 1 and 32",
            name=op.f("ck_cad_construction_props_construction_key_length"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(props) = 'object'", name=op.f("ck_cad_construction_props_props_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_construction_props_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_construction_props_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_construction_props")),
        sa.UniqueConstraint(
            "revision_id",
            "page_index",
            "view",
            "construction_key",
            name="uq_cad_construction_props_sheet_key",
        ),
    )
    op.create_index(
        op.f("ix_cad_construction_props_created_at"), "cad_construction_props", ["created_at"]
    )

    op.create_table(
        "cad_sheet_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("floor_height_mm", sa.Integer(), nullable=True),
        sa.Column("slab_thickness_mm", sa.Integer(), nullable=True),
        sa.Column("door_height_mm", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_cad_sheet_levels_page_index_non_negative")
        ),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_sheet_levels_view_non_negative")),
        sa.CheckConstraint(
            "floor_height_mm is null or floor_height_mm between 2000 and 6000",
            name=op.f("ck_cad_sheet_levels_floor_height_range"),
        ),
        sa.CheckConstraint(
            "slab_thickness_mm is null or slab_thickness_mm between 100 and 1000",
            name=op.f("ck_cad_sheet_levels_slab_thickness_range"),
        ),
        sa.CheckConstraint(
            "door_height_mm is null or door_height_mm between 1500 and 3500",
            name=op.f("ck_cad_sheet_levels_door_height_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_sheet_levels_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_sheet_levels_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_sheet_levels")),
        sa.UniqueConstraint("revision_id", "page_index", "view", name="uq_cad_sheet_levels_sheet"),
    )


def downgrade() -> None:
    op.drop_table("cad_sheet_levels")
    op.drop_index(op.f("ix_cad_construction_props_created_at"), table_name="cad_construction_props")
    op.drop_table("cad_construction_props")
