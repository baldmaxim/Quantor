"""Совмещение планов с уровнем

Revision ID: 0038_plan_alignments
Revises: 0037_sheet_registers
Create Date: 2026-11-15

Этап С3 (ADR-0043 п. 5): `plan_alignments` - совмещение вида CAD подтверждённого плана этажа с
системой координат уровня (эталонный план АР секции): поворот, сдвиг, согласные марки осей,
невязка, источник масштаба, кадр вида, итог и статус candidate / confirmed / rejected. Одна строка
на паспорт и вид. Значение `plan_align` типа задания (`jobs.job_type`) миграции не требует:
перечисление хранится как VARCHAR без CHECK.

Откат удаляет таблицу вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0038_plan_alignments"
down_revision: str | None = "0037_sheet_registers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "plan_alignments"


def _ck(name: str) -> str:
    return op.f(f"ck_{_TABLE}_{name}")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("passport_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("section_mark", sa.Text(), nullable=True),
        sa.Column("building", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("level_from", sa.Text(), nullable=True),
        sa.Column("level_to", sa.Text(), nullable=True),
        sa.Column("cad_job_id", sa.Uuid(), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("rotation_deg", sa.Integer(), nullable=True),
        sa.Column("dx_mm", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("dy_mm", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("axes", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("common_axes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("agreed_axes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("residual_rms_mm", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("residual_max_mm", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("scale_source", sa.String(length=24), nullable=True),
        sa.Column("mm_per_pdf_point", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("origin_pt", pg.JSONB(), nullable=True),
        sa.Column("reasons", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("versions", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("page_index >= 0", name=_ck("page_index_non_negative")),
        sa.CheckConstraint("view >= 0", name=_ck("view_non_negative")),
        sa.CheckConstraint(
            "result in ('reference', 'aligned', 'check', 'failed', 'not_run')",
            name=_ck("result_known"),
        ),
        sa.CheckConstraint(
            "rotation_deg is null or rotation_deg in (0, 90, 180, 270)",
            name=_ck("rotation_known"),
        ),
        sa.CheckConstraint(
            "scale_source is null or scale_source in ('calibration', 'dimension_chains')",
            name=_ck("scale_source_known"),
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'confirmed', 'rejected')", name=_ck("status_known")
        ),
        sa.CheckConstraint("jsonb_typeof(axes) = 'array'", name=_ck("axes_is_array")),
        sa.CheckConstraint("jsonb_typeof(reasons) = 'array'", name=_ck("reasons_is_array")),
        sa.CheckConstraint("jsonb_typeof(versions) = 'object'", name=_ck("versions_is_object")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_plan_alignments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passport_id"],
            ["sheet_passports.id"],
            name=op.f("fk_plan_alignments_passport_id_sheet_passports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_plan_alignments_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["plan_alignments.id"],
            name=op.f("fk_plan_alignments_reference_id_plan_alignments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_alignments")),
    )
    op.create_index("uq_plan_alignments_view", _TABLE, ["passport_id", "view"], unique=True)
    op.create_index("ix_plan_alignments_project", _TABLE, ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_plan_alignments_project", table_name=_TABLE)
    op.drop_index("uq_plan_alignments_view", table_name=_TABLE)
    op.drop_table(_TABLE)
