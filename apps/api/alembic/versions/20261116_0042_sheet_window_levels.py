"""Ручные подоконник и высота окна листа

Revision ID: 0042_sheet_window_levels
Revises: 0041_cad_style_profiles
Create Date: 2026-11-16

ADR-0048 п. 5: последний источник высоты окна - ручной ввод. `cad_sheet_levels.window_sill_mm` и
`window_head_mm` - подоконник и верх окна от чистого пола листа, мм; задаются вместе (оба пусты
или оба заданы), подоконник ниже верха, верх не выше 6000. Пустые - высота окна не задана.

Откат удаляет оба столбца вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_sheet_window_levels"
down_revision: str | None = "0041_cad_style_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "cad_sheet_levels"
_RANGE = "ck_cad_sheet_levels_window_levels_range"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("window_sill_mm", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("window_head_mm", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f(_RANGE),
        _TABLE,
        "(window_sill_mm is null and window_head_mm is null)"
        " or (window_sill_mm is not null and window_head_mm is not null"
        " and window_sill_mm >= 0 and window_sill_mm < window_head_mm"
        " and window_head_mm <= 6000)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_RANGE), _TABLE, type_="check")
    op.drop_column(_TABLE, "window_head_mm")
    op.drop_column(_TABLE, "window_sill_mm")
