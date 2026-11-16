"""Автопринятие уровней разрезов

Revision ID: 0039_section_levels_auto_accept
Revises: 0038_plan_alignments
Create Date: 2026-11-16

ADR-0050: уровень разреза, который генератор разложил по отметкам точно и с которым не расходится ни
один уровень того же корпуса, секции и интервала, принимается системой при публикации результата.
`cad_section_levels.auto_accepted` отличает такое принятие от решения человека: у него нет автора
(`decided_by` пуст), есть время. Ограничение `decided_matches_status` допускает принятие без автора
только с этим признаком; признак без статуса `accepted` запрещён.

Откат возвращает автопринятые строки в кандидаты (автора у них нет) и удаляет столбец.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_section_levels_auto_accept"
down_revision: str | None = "0038_plan_alignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "cad_section_levels"
_DECIDED = "ck_cad_section_levels_decided_matches_status"
_OLD = (
    "(status = 'candidate' and decided_by is null and decided_at is null)"
    " or (status <> 'candidate' and decided_by is not null and decided_at is not null)"
)
_NEW = (
    "(status = 'candidate' and decided_by is null and decided_at is null and not auto_accepted)"
    " or (status <> 'candidate' and decided_at is not null"
    " and (decided_by is not null) <> auto_accepted"
    " and (status = 'accepted' or not auto_accepted))"
)


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("auto_accepted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint(op.f(_DECIDED), _TABLE, type_="check")
    op.create_check_constraint(op.f(_DECIDED), _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(op.f(_DECIDED), _TABLE, type_="check")
    op.execute(
        sa.text(
            "update cad_section_levels set status = 'candidate', decided_at = null,"
            " auto_accepted = false where auto_accepted"
        )
    )
    op.create_check_constraint(op.f(_DECIDED), _TABLE, _OLD)
    op.drop_column(_TABLE, "auto_accepted")
