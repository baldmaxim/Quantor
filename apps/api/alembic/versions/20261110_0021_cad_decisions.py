"""Решения человека по результатам CAD и тип замечания «Трасса»

Revision ID: 0021_cad_decisions
Revises: 0020_cad_remarks
Create Date: 2026-11-10

ADR-0036 п. 8 (трассы механики): таблица `cad_decisions` хранит неизменяемые решения человека,
одобрение вида (`view_approval`) и принятие трасс этажа (`mep_acceptance`). Запись привязана к
заданию, попытке, странице, виду и sha256 DXF, на который решение дано. Тип замечания `route`
добавляется в CHECK `cad_remarks`.

Откат удаляет таблицу решений и возвращает прежний CHECK; замечания типа `route` перед этим
переводятся в `other`, иначе прежний CHECK не примет строки.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_cad_decisions"
down_revision: str | None = "0020_cad_remarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_REMARK_TYPES = (
    "missing_wall",
    "false_wall",
    "missing_door",
    "door_geometry",
    "missing_gate",
    "missing_glazing",
    "monolith",
    "room_boundary",
    "wrong_class",
    "other",
)
NEW_REMARK_TYPES = (*OLD_REMARK_TYPES[:-1], "route", "other")


def _types(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_cad_remarks_type_known"), "cad_remarks", type_="check")
    op.create_check_constraint(
        op.f("ck_cad_remarks_type_known"), "cad_remarks", f"type in ({_types(NEW_REMARK_TYPES)})"
    )

    op.create_table(
        "cad_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("artifact_sha256", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind in ('view_approval', 'mep_acceptance')",
            name=op.f("ck_cad_decisions_kind_known"),
        ),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_cad_decisions_attempt_positive")),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_cad_decisions_page_index_non_negative")
        ),
        sa.CheckConstraint("view >= 0", name=op.f("ck_cad_decisions_view_non_negative")),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cad_decisions_artifact_sha256_hex"),
        ),
        sa.CheckConstraint(
            "comment is null or char_length(comment) <= 2000",
            name=op.f("ck_cad_decisions_comment_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_decisions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_decisions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_cad_decisions_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_cad_decisions_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["user_identities.id"],
            name=op.f("fk_cad_decisions_decided_by_user_identities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_decisions")),
        sa.UniqueConstraint(
            "kind",
            "job_id",
            "attempt",
            "page_index",
            "view",
            name="uq_cad_decisions_kind_job_attempt_page_view",
        ),
    )
    op.create_index("ix_cad_decisions_job_id", "cad_decisions", ["job_id"])


def downgrade() -> None:
    op.drop_table("cad_decisions")
    op.execute("update cad_remarks set type = 'other' where type = 'route'")
    op.drop_constraint(op.f("ck_cad_remarks_type_known"), "cad_remarks", type_="check")
    op.create_check_constraint(
        op.f("ck_cad_remarks_type_known"), "cad_remarks", f"type in ({_types(OLD_REMARK_TYPES)})"
    )
