"""Отзыв решений человека по результатам CAD

Revision ID: 0022_cad_decision_revoke
Revises: 0021_cad_decisions
Create Date: 2026-11-10

ADR-0036 п. 8: решение (`view_approval`, `mep_acceptance`) можно отозвать, не удаляя запись:
в `cad_decisions` появляются `revoked_at`, `revoked_by`, `revoke_reason`. Одно действующее
решение на (kind, job_id, attempt, page_index, view) обеспечивает частичный уникальный индекс
по неотозванным записям; после отзыва можно решить заново - новой записью.

Откат удаляет отозванные записи (они уже не действуют) и возвращает полное UNIQUE-ограничение.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_cad_decision_revoke"
down_revision: str | None = "0021_cad_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_UNIQUE = "uq_cad_decisions_kind_job_attempt_page_view"
ACTIVE_UNIQUE = "uq_cad_decisions_active_kind_job_attempt_page_view"
COLUMNS = ["kind", "job_id", "attempt", "page_index", "view"]


def upgrade() -> None:
    op.add_column("cad_decisions", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column("cad_decisions", sa.Column("revoked_by", sa.Uuid()))
    op.add_column("cad_decisions", sa.Column("revoke_reason", sa.Text()))
    op.create_foreign_key(
        op.f("fk_cad_decisions_revoked_by_user_identities"),
        "cad_decisions",
        "user_identities",
        ["revoked_by"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_cad_decisions_revoke_consistent"),
        "cad_decisions",
        "(revoked_at is null) = (revoked_by is null) "
        "and (revoke_reason is null or revoked_at is not null)",
    )
    op.create_check_constraint(
        op.f("ck_cad_decisions_revoke_reason_length"),
        "cad_decisions",
        "revoke_reason is null or char_length(revoke_reason) <= 2000",
    )
    op.drop_constraint(OLD_UNIQUE, "cad_decisions", type_="unique")
    op.create_index(
        ACTIVE_UNIQUE,
        "cad_decisions",
        COLUMNS,
        unique=True,
        postgresql_where=sa.text("revoked_at is null"),
    )


def downgrade() -> None:
    op.execute("delete from cad_decisions where revoked_at is not null")
    op.drop_index(ACTIVE_UNIQUE, table_name="cad_decisions")
    op.create_unique_constraint(OLD_UNIQUE, "cad_decisions", COLUMNS)
    op.drop_constraint(op.f("ck_cad_decisions_revoke_reason_length"), "cad_decisions", type_="check")
    op.drop_constraint(op.f("ck_cad_decisions_revoke_consistent"), "cad_decisions", type_="check")
    op.drop_constraint(
        op.f("fk_cad_decisions_revoked_by_user_identities"), "cad_decisions", type_="foreignkey"
    )
    op.drop_column("cad_decisions", "revoke_reason")
    op.drop_column("cad_decisions", "revoked_by")
    op.drop_column("cad_decisions", "revoked_at")
