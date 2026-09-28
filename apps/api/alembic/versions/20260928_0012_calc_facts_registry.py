"""Расчётный контур: реестр фактов

Revision ID: 0012_calc_facts_registry
Revises: 0011_measurement_holes
Create Date: 2026-09-28

Первые таблицы расчётного контура стадии П (ADR-0030, PROMPT 01): источники, утверждения о
фактах, их свидетельства, конфликты источников и решения человека. Таблиц запусков,
результатов, ВОР и вопросов нет: они появятся в своих промтах вместе с писателем и читателем.

Ограничения делают невозможное непредставимым:

- утверждение из ВОР Заказчика не может быть допущено к расчёту — ВОР объект сверки, а не
  эталон;
- у источника по ключу факта действует одно утверждение, новое значение — новая версия;
- отзыв всегда с отметкой времени, свидетельство — всегда с содержанием;
- по ключу действует одно решение человека.

Ссылки на ревизии и листы документов — значения без внешних ключей: свидетельство — снимок, а
внешний ключ к таблицам документов изменил бы поведение их удаления.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_calc_facts_registry"
down_revision: str | None = "0011_measurement_holes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_CLASSES = (
    "ARCHITECTURE",
    "APARTMENT_SCHEDULE",
    "ROOM_SCHEDULE",
    "MEP_DESIGN",
    "CONSUMER_TABLE",
    "AIR_EXCHANGE_TABLE",
    "FIXTURE_TABLE",
    "EXPLANATORY_NOTE",
    "TECHNICAL_CONDITIONS",
    "ADJACENT_TASK",
    "BRAND_LIST",
    "TECHNICAL_REQUIREMENTS",
    "CUSTOMER_VOR",
    "MANUAL",
)
_STAGES = ("P", "RD", "UNKNOWN")
_DISCIPLINES = ("VK", "OV", "EOM", "SS", "APT")
_VALUE_KINDS = ("NUMBER", "COUNT", "BOOLEAN", "ENUM", "TEXT", "RANGE")
_METHODS = (
    "DOCUMENT_EXPLICIT",
    "TABLE_EXPLICIT",
    "GEOMETRY_MEASURED",
    "CALCULATED",
    "INFERRED",
    "NORMATIVE",
    "MANUFACTURER_RULE",
    "ASSUMPTION",
    "MANUAL",
)
_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
_REVIEW = ("UNREVIEWED", "CONFIRMED", "REJECTED")
_FACT_STATUS = ("ACTIVE", "SUPERSEDED", "WITHDRAWN")
_EVIDENCE_KINDS = ("MANUAL_ENTRY", "DOCUMENT_FRAGMENT", "ASSUMPTION_BASIS")
_CONFLICT_STATUS = ("OPEN", "RESOLVED", "REOPENED", "OBSOLETE")

_VOR_NEVER_ELIGIBLE = "source_class <> 'CUSTOMER_VOR' or calculation_eligible = false"


def _enum(values: Sequence[str], name: str, length: int) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "calc_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_class", _enum(_SOURCE_CLASSES, "calc_source_class", 32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "document_stage",
            _enum(_STAGES, "calc_document_stage", 16),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("section_code", sa.String(length=16), nullable=True),
        sa.Column("series_key", sa.String(length=100), nullable=True),
        sa.Column("document_revision_id", sa.Uuid(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("calculation_eligible", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created_at(),
        sa.CheckConstraint(_VOR_NEVER_ELIGIBLE, name=op.f("ck_calc_sources_vor_never_eligible")),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name=op.f("ck_calc_sources_title_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_sources_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_sources")),
    )
    op.create_index(op.f("ix_calc_sources_created_at"), "calc_sources", ["created_at"])
    op.create_index("ix_calc_sources_project_id", "calc_sources", ["project_id"])

    op.create_table(
        "calc_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_class", _enum(_SOURCE_CLASSES, "calc_source_class", 32), nullable=False),
        sa.Column("fact_type", sa.String(length=64), nullable=False),
        sa.Column("building", sa.String(length=64), nullable=True),
        sa.Column("section", sa.String(length=64), nullable=True),
        sa.Column("floor", sa.String(length=64), nullable=True),
        sa.Column("room", sa.String(length=64), nullable=True),
        sa.Column("discipline", _enum(_DISCIPLINES, "calc_discipline", 8), nullable=True),
        sa.Column("system_code", sa.String(length=64), nullable=True),
        sa.Column("subject_key", sa.String(length=480), nullable=False),
        sa.Column("fact_key", sa.String(length=560), nullable=False),
        sa.Column("value_kind", _enum(_VALUE_KINDS, "calc_value_kind", 16), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stated_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("method", _enum(_METHODS, "calc_fact_method", 32), nullable=False),
        sa.Column("confidence", _enum(_CONFIDENCE, "calc_confidence", 8), nullable=False),
        sa.Column(
            "review_status",
            _enum(_REVIEW, "calc_review_status", 16),
            server_default="UNREVIEWED",
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum(_FACT_STATUS, "calc_fact_status", 16),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("calculation_eligible", sa.Boolean(), nullable=False),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created_at(),
        # ВОР Заказчика — объект сверки, а не эталон: к расчёту не допускается никогда.
        sa.CheckConstraint(_VOR_NEVER_ELIGIBLE, name=op.f("ck_calc_facts_vor_never_eligible")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_calc_facts_version_positive")),
        sa.CheckConstraint(
            "(status = 'WITHDRAWN') = (withdrawn_at is not null)",
            name=op.f("ck_calc_facts_withdrawn_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_facts_project_id_projects"),
            ondelete="CASCADE",
        ),
        # NO ACTION: удаление проекта уносит источники и утверждения одной операцией, а
        # точечное удаление источника из-под утверждений — нет.
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["calc_sources.id"],
            name=op.f("fk_calc_facts_source_id_calc_sources"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["calc_facts.id"],
            name=op.f("fk_calc_facts_supersedes_id_calc_facts"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_facts")),
        sa.UniqueConstraint(
            "project_id",
            "fact_key",
            "source_id",
            "version",
            name=op.f("uq_calc_facts_version"),
        ),
    )
    op.create_index(op.f("ix_calc_facts_created_at"), "calc_facts", ["created_at"])
    op.create_index(
        "ix_calc_facts_project_id_fact_key", "calc_facts", ["project_id", "fact_key"]
    )
    op.create_index(
        "ix_calc_facts_project_id_fact_type", "calc_facts", ["project_id", "fact_type"]
    )
    op.create_index(
        "uq_calc_facts_active_per_source",
        "calc_facts",
        ["project_id", "fact_key", "source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "calc_fact_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum(_EVIDENCE_KINDS, "calc_evidence_kind", 32), nullable=False),
        sa.Column("document_revision_id", sa.Uuid(), nullable=True),
        sa.Column("page_index", sa.Integer(), nullable=True),
        sa.Column("sheet_id", sa.Uuid(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("locator", sa.String(length=200), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column(
            "alternatives",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "(kind = 'DOCUMENT_FRAGMENT' and document_revision_id is not null)"
            " or (kind = 'ASSUMPTION_BASIS' and basis is not null)"
            " or (kind = 'MANUAL_ENTRY' and author_id is not null)",
            name=op.f("ck_calc_fact_evidence_kind_has_content"),
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["calc_facts.id"],
            name=op.f("fk_calc_fact_evidence_fact_id_calc_facts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_fact_evidence")),
    )
    op.create_index(
        op.f("ix_calc_fact_evidence_created_at"), "calc_fact_evidence", ["created_at"]
    )
    op.create_index("ix_calc_fact_evidence_fact_id", "calc_fact_evidence", ["fact_id"])

    op.create_table(
        "calc_fact_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("fact_key", sa.String(length=560), nullable=False),
        sa.Column("fact_type", sa.String(length=64), nullable=False),
        sa.Column("subject_key", sa.String(length=480), nullable=False),
        sa.Column("status", _enum(_CONFLICT_STATUS, "calc_conflict_status", 16), nullable=False),
        sa.Column(
            "claim_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_fact_conflicts_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_fact_conflicts")),
        sa.UniqueConstraint("project_id", "fact_key", name=op.f("uq_calc_fact_conflicts_key")),
    )
    op.create_index(
        op.f("ix_calc_fact_conflicts_created_at"), "calc_fact_conflicts", ["created_at"]
    )

    op.create_table(
        "calc_manual_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("fact_key", sa.String(length=560), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=True),
        sa.Column("chosen_fact_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_calc_manual_overrides_reason_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_manual_overrides_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conflict_id"],
            ["calc_fact_conflicts.id"],
            name=op.f("fk_calc_manual_overrides_conflict_id_calc_fact_conflicts"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["chosen_fact_id"],
            ["calc_facts.id"],
            name=op.f("fk_calc_manual_overrides_chosen_fact_id_calc_facts"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_manual_overrides")),
    )
    op.create_index(
        op.f("ix_calc_manual_overrides_created_at"), "calc_manual_overrides", ["created_at"]
    )
    # Действует одно решение на ключ: новое отзывает прежнее.
    op.create_index(
        "uq_calc_manual_overrides_active",
        "calc_manual_overrides",
        ["project_id", "fact_key"],
        unique=True,
        postgresql_where=sa.text("revoked_at is null"),
    )


def downgrade() -> None:
    op.drop_index("uq_calc_manual_overrides_active", table_name="calc_manual_overrides")
    op.drop_index(op.f("ix_calc_manual_overrides_created_at"), table_name="calc_manual_overrides")
    op.drop_table("calc_manual_overrides")

    op.drop_index(op.f("ix_calc_fact_conflicts_created_at"), table_name="calc_fact_conflicts")
    op.drop_table("calc_fact_conflicts")

    op.drop_index("ix_calc_fact_evidence_fact_id", table_name="calc_fact_evidence")
    op.drop_index(op.f("ix_calc_fact_evidence_created_at"), table_name="calc_fact_evidence")
    op.drop_table("calc_fact_evidence")

    op.drop_index("uq_calc_facts_active_per_source", table_name="calc_facts")
    op.drop_index("ix_calc_facts_project_id_fact_type", table_name="calc_facts")
    op.drop_index("ix_calc_facts_project_id_fact_key", table_name="calc_facts")
    op.drop_index(op.f("ix_calc_facts_created_at"), table_name="calc_facts")
    op.drop_table("calc_facts")

    op.drop_index("ix_calc_sources_project_id", table_name="calc_sources")
    op.drop_index(op.f("ix_calc_sources_created_at"), table_name="calc_sources")
    op.drop_table("calc_sources")
