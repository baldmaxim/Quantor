"""Профили оформления проектировщика: профиль тома и его неизменяемые версии

Revision ID: 0041_cad_style_profiles
Revises: 0040_cad_facade_views
Create Date: 2026-11-16

ADR-0049 (решения 1, 2, 5, 6): `cad_style_profiles` - один профиль на том (документ), ключ
`profile_key` для движка; `cad_style_profile_versions` - неизменяемые версии с готовым объектом
`cad_engine.style_profile.v1` (JSONB), его sha256 и происхождением. UPDATE версии запрещён
триггером (тот же текст, что в `app/models/cad_style_profiles.py`); DELETE разрешён ради каскада.

Откат удаляет обе таблицы вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0041_cad_style_profiles"
down_revision: str | None = "0040_cad_facade_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "cad_style_profiles"
_V = "cad_style_profile_versions"

GUARD_FUNCTION = """
create or replace function cad_style_profile_versions_immutable() returns trigger
language plpgsql as $$
begin
    raise exception 'cad_style_profile_versions: a version is immutable, create a new version';
end
$$
"""

GUARD_TRIGGER = """
create trigger trg_cad_style_profile_versions_immutable
before update on cad_style_profile_versions
for each row execute function cad_style_profile_versions_immutable()
"""


def upgrade() -> None:
    op.create_table(
        _P,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_style_profiles_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_style_profiles_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_cad_style_profiles_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_style_profiles")),
        sa.UniqueConstraint("document_id", name=op.f("uq_cad_style_profiles_document_id")),
    )
    op.create_index(op.f("ix_cad_style_profiles_project_id"), _P, ["project_id"])
    op.create_index(op.f("ix_cad_style_profiles_created_at"), _P, ["created_at"])

    op.create_table(
        _V,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("style", pg.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source", pg.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_cad_style_profile_versions_version_positive")
        ),
        sa.CheckConstraint(
            "char_length(title) <= 200", name=op.f("ck_cad_style_profile_versions_title_length")
        ),
        sa.CheckConstraint(
            "char_length(sha256) = 64", name=op.f("ck_cad_style_profile_versions_sha256_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(style) = 'object'",
            name=op.f("ck_cad_style_profile_versions_style_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source) = 'object'",
            name=op.f("ck_cad_style_profile_versions_source_is_object"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            [f"{_P}.id"],
            name=op.f("fk_cad_style_profile_versions_profile_id_cad_style_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_style_profile_versions")),
        sa.UniqueConstraint(
            "profile_id",
            "version",
            name=op.f("uq_cad_style_profile_versions_profile_id_version"),
        ),
    )
    op.create_index(op.f("ix_cad_style_profile_versions_created_at"), _V, ["created_at"])
    op.execute(GUARD_FUNCTION)
    op.execute(GUARD_TRIGGER)


def downgrade() -> None:
    op.drop_table(_V)
    op.execute("drop function if exists cad_style_profile_versions_immutable()")
    op.drop_table(_P)
