"""Перенос решений человека на новый прогон: cad_decisions.carried_from_id

Revision ID: 0054_cad_decision_carried_from
Revises: 0052_ai_style_role
Create Date: 2026-11-27

Решение (`view_approval`, `mep_acceptance`), перенесённое на новый прогон движка при полном
совпадении геометрии вида, ссылается на исходное решение. Автор остаётся тем же человеком.
Удаление исходного решения (вместе с заданием) обнуляет ссылку, перенесённое решение остаётся.
Откат удаляет колонку.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_cad_decision_carried_from"
down_revision: str | None = "0052_ai_style_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cad_decisions", sa.Column("carried_from_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_cad_decisions_carried_from_id_cad_decisions"),
        "cad_decisions",
        "cad_decisions",
        ["carried_from_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_cad_decisions_carried_from_id_cad_decisions"), "cad_decisions", type_="foreignkey"
    )
    op.drop_column("cad_decisions", "carried_from_id")
