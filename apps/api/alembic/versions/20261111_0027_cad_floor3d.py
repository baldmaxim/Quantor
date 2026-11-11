"""3D-вид этажа: отметка этажа в переопределениях листа, уровень проекта, решения по отверстиям

Revision ID: 0027_cad_floor3d
Revises: 0026_cad_vor
Create Date: 2026-11-11

ADR-0039: `cad_sheet_levels.floor_elevation_mm` - отметка этажа (верх плиты); `cad_project_levels` -
толщина плиты из разрезов, один раз на проект, с листом разреза; `cad_slab_hole_decisions` - решения
человека по отверстиям-кандидатам плиты листа.

Откат удаляет обе новые таблицы и колонку вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_cad_floor3d"
down_revision: str | None = "0026_cad_vor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cad_sheet_levels", sa.Column("floor_elevation_mm", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_cad_sheet_levels_floor_elevation_range"),
        "cad_sheet_levels",
        "floor_elevation_mm is null or floor_elevation_mm between -100000 and 500000",
    )

    op.create_table(
        "cad_project_levels",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("slab_thickness_mm", sa.Integer(), nullable=True),
        sa.Column("slab_source_ref", sa.String(length=200), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slab_thickness_mm is null or slab_thickness_mm between 100 and 1000",
            name=op.f("ck_cad_project_levels_slab_thickness_range"),
        ),
        sa.CheckConstraint(
            "slab_thickness_mm is null or (slab_source_ref is not null and slab_source_ref <> '')",
            name=op.f("ck_cad_project_levels_slab_source_ref_required"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_project_levels_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_project_levels_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_cad_project_levels")),
    )

    op.create_table(
        "cad_slab_hole_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("hole_key", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_cad_slab_hole_decisions_page_index_non_negative")
        ),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_slab_hole_decisions_view_non_negative")),
        sa.CheckConstraint(
            "char_length(hole_key) between 1 and 32",
            name=op.f("ck_cad_slab_hole_decisions_hole_key_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_slab_hole_decisions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_slab_hole_decisions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_slab_hole_decisions_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_slab_hole_decisions")),
        sa.UniqueConstraint(
            "revision_id",
            "page_index",
            "view",
            "hole_key",
            name="uq_cad_slab_hole_decisions_sheet_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("cad_slab_hole_decisions")
    op.drop_table("cad_project_levels")
    op.drop_constraint(
        op.f("ck_cad_sheet_levels_floor_elevation_range"), "cad_sheet_levels", type_="check"
    )
    op.drop_column("cad_sheet_levels", "floor_elevation_mm")
