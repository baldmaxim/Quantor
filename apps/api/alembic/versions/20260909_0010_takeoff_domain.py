"""Ручной обмер: строка списка и её геометрия

Revision ID: 0010_takeoff_domain
Revises: 0009_scale_calibration
Create Date: 2026-09-09

Первая пользовательская сущность подсчёта (ADR-0019). До сих пор портал хранил только
свидетельства распознавалки; теперь появляется место, куда человек кладёт свои обмеры.

`measurements` намеренно отдельна от `regions`: область — свидетельство, измерение —
намерение. Общая таблица означала бы, что исправление разметки молча меняет посчитанный
объём.

Два CHECK делают невозможное непредставимым:

- единица показа не может разойтись с типом геометрии;
- многоугольник не может состоять из двух точек.

Второй записан через `jsonb_array_length`: проверка в приложении ловит ошибку пользователя,
проверка здесь — ошибку программиста.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_takeoff_domain"
down_revision: str | None = "0009_scale_calibration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GEOMETRY_TYPES = ("count", "line", "polyline", "polygon")
_UNITS = ("pcs", "m", "m2")
_SOURCES = ("manual", "ai", "imported")


def upgrade() -> None:
    op.create_table(
        "takeoff_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column(
            "geometry_type",
            sa.Enum(*_GEOMETRY_TYPES, name="geometry_type", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "display_unit",
            sa.Enum(*_UNITS, name="quantity_unit", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("color_key", sa.String(length=32), server_default="accent", nullable=False),
        sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        # Единица показа не может разойтись с типом: иначе однажды покажем площадь в метрах.
        sa.CheckConstraint(
            "(geometry_type = 'count' and display_unit = 'pcs')"
            " or (geometry_type in ('line', 'polyline') and display_unit = 'm')"
            " or (geometry_type = 'polygon' and display_unit = 'm2')",
            name=op.f("ck_takeoff_items_unit_matches_geometry"),
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_takeoff_items_name_not_blank")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_takeoff_items_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_takeoff_items")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_takeoff_items_project_name")),
    )
    op.create_index(op.f("ix_takeoff_items_created_at"), "takeoff_items", ["created_at"])
    op.create_index(
        "ix_takeoff_items_project_id_ordinal", "takeoff_items", ["project_id", "ordinal"]
    )
    # Список проекта читается на каждом открытии рабочей области; архивные строки в нём
    # не участвуют.
    op.create_index(
        "ix_takeoff_items_active",
        "takeoff_items",
        ["project_id", "ordinal"],
        postgresql_where=sa.text("archived_at is null"),
    )

    op.create_table(
        "measurements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("takeoff_item_id", sa.Uuid(), nullable=False),
        sa.Column("sheet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "geometry_type",
            sa.Enum(*_GEOMETRY_TYPES, name="geometry_type", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source",
            sa.Enum(*_SOURCES, name="measurement_source", native_enum=False, length=32),
            server_default="manual",
            nullable=False,
        ),
        sa.Column("scale_calibration_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "measurement_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
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
        # Многоугольник из двух точек не имеет площади. Получить его нельзя ни через API,
        # ни ручным SQL.
        sa.CheckConstraint(
            "jsonb_typeof(points) = 'array' and ("
            "(geometry_type = 'count' and jsonb_array_length(points) = 1)"
            " or (geometry_type = 'line' and jsonb_array_length(points) = 2)"
            " or (geometry_type = 'polyline' and jsonb_array_length(points) >= 2)"
            " or (geometry_type = 'polygon' and jsonb_array_length(points) >= 3))",
            name=op.f("ck_measurements_points_match_geometry"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_measurements_version_positive")),
        sa.ForeignKeyConstraint(
            ["takeoff_item_id"],
            ["takeoff_items.id"],
            name=op.f("fk_measurements_takeoff_item_id_takeoff_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheets.id"],
            name=op.f("fk_measurements_sheet_id_sheets"),
            ondelete="CASCADE",
        ),
        # NO ACTION, а не RESTRICT: проверка откладывается до конца операции, поэтому
        # удаление листа с каскадом на измерения и калибровки проходит, а точечное
        # удаление калибровки из-под живого измерения — нет. Величина без основания
        # не величина.
        sa.ForeignKeyConstraint(
            ["scale_calibration_id"],
            ["scale_calibrations.id"],
            name=op.f("fk_measurements_scale_calibration_id_scale_calibrations"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measurements")),
    )
    op.create_index(op.f("ix_measurements_created_at"), "measurements", ["created_at"])
    op.create_index("ix_measurements_item_id", "measurements", ["takeoff_item_id"])
    op.create_index(
        "ix_measurements_sheet_id_item_id", "measurements", ["sheet_id", "takeoff_item_id"]
    )
    # Активные измерения листа: их читает просмотрщик при каждом открытии.
    op.create_index(
        "ix_measurements_active",
        "measurements",
        ["sheet_id", "takeoff_item_id"],
        postgresql_where=sa.text("deleted_at is null"),
    )


def downgrade() -> None:
    op.drop_index("ix_measurements_active", table_name="measurements")
    op.drop_index("ix_measurements_sheet_id_item_id", table_name="measurements")
    op.drop_index("ix_measurements_item_id", table_name="measurements")
    op.drop_index(op.f("ix_measurements_created_at"), table_name="measurements")
    op.drop_table("measurements")

    op.drop_index("ix_takeoff_items_active", table_name="takeoff_items")
    op.drop_index("ix_takeoff_items_project_id_ordinal", table_name="takeoff_items")
    op.drop_index(op.f("ix_takeoff_items_created_at"), table_name="takeoff_items")
    op.drop_table("takeoff_items")
