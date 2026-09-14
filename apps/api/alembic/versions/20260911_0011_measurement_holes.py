"""Отверстия многоугольника в измерении

Revision ID: 0011_measurement_holes
Revises: 0010_takeoff_domain
Create Date: 2026-09-11

Многоугольник измерения получает отверстия (ADR-0026) — минимально и без перелома прежнего
контракта: `points` остаётся внешним контуром, рядом появляется `holes` — список колец в том же
каноне нормализованных точек.

Существующие строки получают `[]` значением по умолчанию: их геометрия и величина не меняются,
многоугольник без отверстий считается прежним правилом `area.v1` с прежним отпечатком входа.

CHECK делает непредставимым то, что база способна выразить: отверстия только у многоугольника,
каждое кольцо — массив минимум из трёх точек. Топология — внутри контура, без касаний — остаётся
сервису.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_measurement_holes"
down_revision: str | None = "0010_takeoff_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HOLES_CHECK = (
    "jsonb_typeof(holes) = 'array'"
    " and (geometry_type = 'polygon' or jsonb_array_length(holes) = 0)"
    " and not jsonb_path_exists(holes,"
    " 'strict $[*] ? (@.type() != \"array\" || @.size() < 3)')"
)


def upgrade() -> None:
    op.add_column(
        "measurements",
        sa.Column(
            "holes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_measurements_holes_match_geometry"), "measurements", _HOLES_CHECK
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_measurements_holes_match_geometry"), "measurements", type_="check")
    op.drop_column("measurements", "holes")
