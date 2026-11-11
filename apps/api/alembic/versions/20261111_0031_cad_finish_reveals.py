"""Отделка: откосы дверей в слоях стен шаблона

Revision ID: 0031_cad_finish_reveals
Revises: 0030_cad_finishes
Create Date: 2026-11-11

ADR-0042, п. 6: колонка `cad_finish_templates.walls_include_reveals` - откосы дверных проёмов
входят в площадь слоёв стен (по умолчанию нет). Основание слоя стен (`bases`) лежит внутри JSONB
слоёв и миграции не требует.

Откат удаляет колонку вместе со значениями.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_cad_finish_reveals"
down_revision: str | None = "0030_cad_finishes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cad_finish_templates",
        sa.Column(
            "walls_include_reveals",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cad_finish_templates", "walls_include_reveals")
