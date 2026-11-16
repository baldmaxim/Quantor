"""Обмен расчётами с TENDER: токены, выпуски базы объекта, репозитории расчётов и версии

Revision ID: 0043_tender_exchange
Revises: 0040_cad_facade_views
Create Date: 2026-11-16

ADR-0051: `api_tokens` - персональные токены `qtk_…` (в базе только sha256 и префикс для показа);
`tender_base_releases` - неизменяемые выпуски базы объекта (ZIP в хранилище, виды и sha256 в
базе); `tender_calcs` - репозитории расчётов (проект, раздел, система, название);
`tender_calc_versions` - неизменяемые версии расчёта: метаданные, виды (ключи файлов в хранилище),
свод объёмов, вопросы и предупреждения приёма. Одна действующая версия на репозиторий.

Откат удаляет таблицы вместе с данными (файлы в хранилище остаются).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0043_tender_exchange"
down_revision: str | None = "0042_sheet_window_levels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("jsonb_typeof(scopes) = 'array'", name=op.f("ck_api_tokens_scopes_is_array")),
        sa.CheckConstraint(
            "char_length(token_hash) = 64", name=op.f("ck_api_tokens_token_hash_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_identities.id"],
            name=op.f("fk_api_tokens_user_id_user_identities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_api_tokens_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index("ix_api_tokens_user_id_workspace_id", "api_tokens", ["user_id", "workspace_id"])

    op.create_table(
        "tender_base_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("released_by", sa.Uuid(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("include_dxf", sa.Boolean(), nullable=False),
        sa.Column("views", pg.JSONB(), nullable=False),
        sa.Column("package_key", sa.Text(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("number >= 1", name=op.f("ck_tender_base_releases_number_positive")),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_tender_base_releases_size_non_negative")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(views) = 'array'", name=op.f("ck_tender_base_releases_views_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tender_base_releases_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tender_base_releases_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["released_by"],
            ["user_identities.id"],
            name=op.f("fk_tender_base_releases_released_by_user_identities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["user_identities.id"],
            name=op.f("fk_tender_base_releases_revoked_by_user_identities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_base_releases")),
        sa.UniqueConstraint(
            "project_id", "number", name=op.f("uq_tender_base_releases_project_id_number")
        ),
    )
    op.create_index("ix_tender_base_releases_workspace_id", "tender_base_releases", ["workspace_id"])

    op.create_table(
        "tender_calcs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("discipline", sa.String(length=8), nullable=False),
        sa.Column("system", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "discipline in ('mech', 'eom', 'ss')", name=op.f("ck_tender_calcs_discipline_known")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tender_calcs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tender_calcs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_identities.id"],
            name=op.f("fk_tender_calcs_created_by_user_identities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_calcs")),
        sa.UniqueConstraint(
            "project_id",
            "discipline",
            "system",
            "title",
            name=op.f("uq_tender_calcs_project_id_discipline_system_title"),
        ),
    )
    op.create_index("ix_tender_calcs_workspace_id", "tender_calcs", ["workspace_id"])

    op.create_table(
        "tender_calc_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calc_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("base_release_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("producer", pg.JSONB(), nullable=False),
        sa.Column("fit", pg.JSONB(), nullable=False),
        sa.Column("package_key", sa.Text(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("views", pg.JSONB(), nullable=False),
        sa.Column("quantities", pg.JSONB(), nullable=False),
        sa.Column("questions", pg.JSONB(), nullable=False),
        sa.Column("warnings", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("withdrawn_by", sa.Uuid(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("number >= 1", name=op.f("ck_tender_calc_versions_number_positive")),
        sa.CheckConstraint(
            "status in ('active', 'superseded', 'withdrawn')",
            name=op.f("ck_tender_calc_versions_status_known"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(fit) = 'array'", name=op.f("ck_tender_calc_versions_fit_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(views) = 'array'", name=op.f("ck_tender_calc_versions_views_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(quantities) = 'array'",
            name=op.f("ck_tender_calc_versions_quantities_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(questions) = 'array'",
            name=op.f("ck_tender_calc_versions_questions_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(warnings) = 'array'",
            name=op.f("ck_tender_calc_versions_warnings_is_array"),
        ),
        sa.CheckConstraint(
            "(status = 'withdrawn') = (withdrawn_at is not null)",
            name=op.f("ck_tender_calc_versions_withdrawn_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["calc_id"],
            ["tender_calcs.id"],
            name=op.f("fk_tender_calc_versions_calc_id_tender_calcs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_release_id"],
            ["tender_base_releases.id"],
            name=op.f("fk_tender_calc_versions_base_release_id_tender_base_releases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["user_identities.id"],
            name=op.f("fk_tender_calc_versions_uploaded_by_user_identities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawn_by"],
            ["user_identities.id"],
            name=op.f("fk_tender_calc_versions_withdrawn_by_user_identities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_calc_versions")),
        sa.UniqueConstraint(
            "calc_id", "number", name=op.f("uq_tender_calc_versions_calc_id_number")
        ),
        sa.UniqueConstraint(
            "calc_id",
            "package_sha256",
            name=op.f("uq_tender_calc_versions_calc_id_package_sha256"),
        ),
    )
    op.create_index(
        "uq_tender_calc_versions_active",
        "tender_calc_versions",
        ["calc_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_tender_calc_versions_base_release_id", "tender_calc_versions", ["base_release_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tender_calc_versions_base_release_id", table_name="tender_calc_versions")
    op.drop_index("uq_tender_calc_versions_active", table_name="tender_calc_versions")
    op.drop_table("tender_calc_versions")
    op.drop_index("ix_tender_calcs_workspace_id", table_name="tender_calcs")
    op.drop_table("tender_calcs")
    op.drop_index("ix_tender_base_releases_workspace_id", table_name="tender_base_releases")
    op.drop_table("tender_base_releases")
    op.drop_index("ix_api_tokens_user_id_workspace_id", table_name="api_tokens")
    op.drop_table("api_tokens")
