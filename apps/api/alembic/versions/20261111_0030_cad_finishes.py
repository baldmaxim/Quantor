"""Отделка помещений в пилоте CAD: шаблоны отделки проекта, тип помещения и шаблон у зоны

Revision ID: 0030_cad_finishes
Revises: 0029_cad_zone_parking
Create Date: 2026-11-11

ADR-0042: таблица `cad_finish_templates` (шаблон: типы помещений, высота стен, слои пола, стен и
потолка), колонки `cad_zones.room_type` (код справочника) и `cad_zones.finish_template_id`
(явное назначение; шаблон удалён - назначение снимается). Хранимый тип миграция не заполняет:
для зоны без заданного типа сервер выводит его из названия при чтении.

Откат удаляет колонки зон и таблицу шаблонов вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0030_cad_finishes"
down_revision: str | None = "0029_cad_zone_parking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Те же значения, что `CadRoomType` в `app/contracts/cad_room_types.py`.
ROOM_TYPES = (
    "lift_hall",
    "vestibule",
    "airlock",
    "corridor",
    "stair",
    "entrance_hall",
    "pui",
    "garbage",
    "tech",
    "mop_other",
    "living",
    "kitchen",
    "bath",
    "wc",
    "hall",
    "storage",
    "balcony",
    "apt_other",
)


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _json_array_column(name: str) -> sa.Column[Any]:
    return sa.Column(name, pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "cad_finish_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        _json_array_column("room_types"),
        sa.Column("wall_height_mm", sa.Integer(), nullable=True),
        _json_array_column("floor_layers"),
        _json_array_column("wall_layers"),
        _json_array_column("ceiling_layers"),
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
        sa.CheckConstraint(
            "char_length(name) between 1 and 200", name=op.f("ck_cad_finish_templates_name_length")
        ),
        sa.CheckConstraint(
            "wall_height_mm is null or wall_height_mm between 1000 and 6000",
            name=op.f("ck_cad_finish_templates_wall_height_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(room_types) = 'array'",
            name=op.f("ck_cad_finish_templates_room_types_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(floor_layers) = 'array'",
            name=op.f("ck_cad_finish_templates_floor_layers_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(wall_layers) = 'array'",
            name=op.f("ck_cad_finish_templates_wall_layers_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(ceiling_layers) = 'array'",
            name=op.f("ck_cad_finish_templates_ceiling_layers_is_array"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_finish_templates_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_finish_templates")),
        sa.UniqueConstraint("project_id", "name", name="uq_cad_finish_templates_project_name"),
    )

    op.add_column("cad_zones", sa.Column("room_type", sa.String(length=32), nullable=True))
    op.add_column("cad_zones", sa.Column("finish_template_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_cad_zones_finish_template_id_cad_finish_templates"),
        "cad_zones",
        "cad_finish_templates",
        ["finish_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_cad_zones_finish_template_id"), "cad_zones", ["finish_template_id"], unique=False
    )
    op.create_check_constraint(
        op.f("ck_cad_zones_room_type_known"),
        "cad_zones",
        f"room_type is null or room_type in ({_quoted(ROOM_TYPES)})",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_cad_zones_room_type_known"), "cad_zones", type_="check")
    op.drop_index(op.f("ix_cad_zones_finish_template_id"), table_name="cad_zones")
    op.drop_constraint(
        op.f("fk_cad_zones_finish_template_id_cad_finish_templates"),
        "cad_zones",
        type_="foreignkey",
    )
    op.drop_column("cad_zones", "finish_template_id")
    op.drop_column("cad_zones", "room_type")
    op.drop_table("cad_finish_templates")
