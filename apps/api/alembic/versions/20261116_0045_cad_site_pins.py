"""Ручная привязка корпуса к площадке по двум парам точек

Revision ID: 0045_cad_site_pins
Revises: 0044_cad_zone_quality
Create Date: 2026-11-16

ADR-0052: корпуса, которые автоматика не ставит на подземную часть (нет общих марок осей, лист
повёрнут), ставит человек. Таблица `cad_site_pins` хранит привязку: лист-источник (ревизия,
страница, вид), лист-цель, по две точки на каждом (мм кадра своего вида) и выведенный сервером
перевод вида источника в вид цели (поворот и сдвиг, без масштаба). Запись неизменяема, кроме
отзыва; действующая привязка на лист-источник одна (частичный уникальный индекс).

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_cad_site_pins"
down_revision: str | None = "0044_cad_zone_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "cad_site_pins"
_MM = (
    "source_x1_mm",
    "source_y1_mm",
    "source_x2_mm",
    "source_y2_mm",
    "target_x1_mm",
    "target_y1_mm",
    "target_x2_mm",
    "target_y2_mm",
    "rotation_deg",
    "offset_x_mm",
    "offset_y_mm",
    "baseline_mm",
    "residual_mm",
)


def upgrade() -> None:
    op.create_table(
        _T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_page_index", sa.Integer(), nullable=False),
        sa.Column("source_view", sa.Integer(), nullable=False),
        sa.Column("target_revision_id", sa.Uuid(), nullable=False),
        sa.Column("target_page_index", sa.Integer(), nullable=False),
        sa.Column("target_view", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.Float(), nullable=False) for name in _MM),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_page_index >= 0 and source_view >= 0 "
            "and target_page_index >= 0 and target_view >= 0",
            name=op.f("ck_cad_site_pins_sheet_address_non_negative"),
        ),
        sa.CheckConstraint(
            "(source_revision_id, source_page_index, source_view) "
            "<> (target_revision_id, target_page_index, target_view)",
            name=op.f("ck_cad_site_pins_source_differs_from_target"),
        ),
        sa.CheckConstraint(
            "baseline_mm > 0 and residual_mm >= 0", name=op.f("ck_cad_site_pins_distances_valid")
        ),
        sa.CheckConstraint(
            "note is null or char_length(note) <= 2000", name=op.f("ck_cad_site_pins_note_length")
        ),
        sa.CheckConstraint(
            "(revoked_at is null) = (revoked_by is null) "
            "and (revoke_reason is null or revoked_at is not null)",
            name=op.f("ck_cad_site_pins_revoke_consistent"),
        ),
        sa.CheckConstraint(
            "revoke_reason is null or char_length(revoke_reason) <= 2000",
            name=op.f("ck_cad_site_pins_revoke_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_site_pins_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_site_pins_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_site_pins_source_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_site_pins_target_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_identities.id"],
            name=op.f("fk_cad_site_pins_created_by_user_identities"),
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["user_identities.id"],
            name=op.f("fk_cad_site_pins_revoked_by_user_identities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_site_pins")),
    )
    op.create_index("ix_cad_site_pins_project_id", _T, ["project_id"])
    op.create_index(
        "uq_cad_site_pins_active_source",
        _T,
        ["source_revision_id", "source_page_index", "source_view"],
        unique=True,
        postgresql_where=sa.text("revoked_at is null"),
    )


def downgrade() -> None:
    op.drop_table(_T)
