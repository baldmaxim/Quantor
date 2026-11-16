"""Модель здания из пакета QMP: версии, принятые части, этажи

Revision ID: 0046_building_models
Revises: 0045_cad_site_pins
Create Date: 2026-11-16

ADR-0053. `building_model_versions` - неизменяемые выгрузки модели проекта (загрузка → кандидат →
утверждена → заменена; не больше одной утверждённой на проект); `model_parts` - принятые части
пакета с хешем и ключом в хранилище; `model_storeys` - этажи версии. Элементы и геометрия лежат в
объектном хранилище.

Откат удаляет все три таблицы вместе с данными; файлы в хранилище остаются.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0046_building_models"
down_revision: str | None = "0045_cad_site_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "building_model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tender_version_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "uploading",
                "candidate",
                "approved",
                "superseded",
                name="model_version_status",
                native_enum=False,
                length=32,
            ),
            server_default="uploading",
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("generator", sa.String(length=120), nullable=True),
        sa.Column("storage_prefix", sa.String(length=200), nullable=False),
        sa.Column("counts", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("warnings", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_building_model_versions_number_positive")),
        sa.CheckConstraint(
            "length(manifest_sha256) = 64",
            name=op.f("ck_building_model_versions_manifest_sha256_length"),
        ),
        sa.CheckConstraint(
            "status <> 'approved' or approved_at is not null",
            name=op.f("ck_building_model_versions_approved_has_time"),
        ),
        sa.CheckConstraint(
            "status = 'uploading' or committed_at is not null",
            name=op.f("ck_building_model_versions_committed_has_time"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name=op.f("fk_building_model_versions_project_id_workspace_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_building_model_versions_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tender_version_id"],
            ["tender_versions.id"],
            name=op.f("fk_building_model_versions_tender_version_id_tender_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building_model_versions")),
        sa.UniqueConstraint(
            "project_id", "number", name="uq_building_model_versions_project_number"
        ),
        sa.UniqueConstraint(
            "project_id", "manifest_sha256", name="uq_building_model_versions_project_manifest"
        ),
    )
    op.create_index(
        op.f("ix_building_model_versions_created_at"), "building_model_versions", ["created_at"]
    )
    op.create_index(
        "uq_building_model_versions_approved",
        "building_model_versions",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )

    op.create_table(
        "model_parts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("storey_key", sa.String(length=64), nullable=True),
        sa.Column("discipline", sa.String(length=16), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(sha256) = 64", name=op.f("ck_model_parts_sha256_length")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_model_parts_size_non_negative")),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["building_model_versions.id"],
            name=op.f("fk_model_parts_version_id_building_model_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_parts")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_model_parts_storage_key")),
        sa.UniqueConstraint("version_id", "path", name="uq_model_parts_version_path"),
    )
    op.create_index(op.f("ix_model_parts_created_at"), "model_parts", ["created_at"])

    op.create_table(
        "model_storeys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("storey_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("elevation_mm", sa.Float(), nullable=False),
        sa.Column("height_mm", sa.Float(), nullable=True),
        sa.Column("bbox_mm", pg.JSONB(), nullable=True),
        sa.Column("element_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "element_count >= 0", name=op.f("ck_model_storeys_element_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["building_model_versions.id"],
            name=op.f("fk_model_storeys_version_id_building_model_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_storeys")),
        sa.UniqueConstraint("version_id", "storey_key", name="uq_model_storeys_version_key"),
    )


def downgrade() -> None:
    op.drop_table("model_storeys")
    op.drop_index(op.f("ix_model_parts_created_at"), table_name="model_parts")
    op.drop_table("model_parts")
    op.drop_index("uq_building_model_versions_approved", table_name="building_model_versions")
    op.drop_index(
        op.f("ix_building_model_versions_created_at"), table_name="building_model_versions"
    )
    op.drop_table("building_model_versions")
