"""Зоны листа во вкладке CAD: помещения квартир, помещения МОП, двери

Revision ID: 0023_cad_zones
Revises: 0022_cad_decision_revoke
Create Date: 2026-11-10

ADR-0036: таблица `cad_zones` хранит разметку человека на листе (помещения и двери) в
нормализованных координатах от левого верхнего угла. Площадь, периметр и ширину сервер считает
при чтении по геометрии страницы и калибровке листа; в таблице их нет.

Откат удаляет таблицу вместе с зонами.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_cad_zones"
down_revision: str | None = "0022_cad_decision_revoke"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Те же значения, что `ZONE_KIND_VALUES` в `app/models/cad_zone.py`.
ZONE_KINDS = ("room_apartment", "room_mop", "door")


def upgrade() -> None:
    kinds = ", ".join(f"'{value}'" for value in ZONE_KINDS)
    op.create_table(
        "cad_zones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("apartment_no", sa.Text(), nullable=True),
        sa.Column("room_mark", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("door_height_mm", sa.Integer(), nullable=True),
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
        sa.CheckConstraint("page_index >= 0", name=op.f("ck_cad_zones_page_index_non_negative")),
        sa.CheckConstraint(f"kind in ({kinds})", name=op.f("ck_cad_zones_kind_known")),
        sa.CheckConstraint(
            "kind <> 'room_apartment' or (apartment_no is not null and apartment_no <> '')",
            name=op.f("ck_cad_zones_apartment_no_required"),
        ),
        sa.CheckConstraint(
            "door_height_mm is null or (kind = 'door' and door_height_mm between 1500 and 3500)",
            name=op.f("ck_cad_zones_door_height_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(points) = 'array'", name=op.f("ck_cad_zones_points_is_array")
        ),
        sa.CheckConstraint(
            "(kind = 'door' and jsonb_array_length(points) = 2) or "
            "(kind <> 'door' and jsonb_array_length(points) >= 3)",
            name=op.f("ck_cad_zones_points_count"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_zones_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_zones_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_zones_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_zones")),
    )
    op.create_index(op.f("ix_cad_zones_created_at"), "cad_zones", ["created_at"])
    op.create_index("ix_cad_zones_revision_page", "cad_zones", ["revision_id", "page_index"])


def downgrade() -> None:
    op.drop_table("cad_zones")
