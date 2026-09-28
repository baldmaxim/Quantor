"""Расчётный контур: сбор исходных данных стадии П

Revision ID: 0013_calc_stage_p_inputs
Revises: 0012_calc_facts_registry
Create Date: 2026-09-28

Сбор фактов из распознанного пакета (ADR-0030, PROMPT 02):

- запись о сборе: что заявлено о документе, какая версия адаптеров, какие факты проверены и
  что не удалось. Без неё «документ проверен, значения нет» не отличить от «ещё не смотрели»;
- свидетельство по блоку распознанного пакета: блок, отпечаток его текста и место таблицы или
  фрагмента. Ссылка на блок — значение без внешнего ключа: свидетельство — снимок;
- квалификатор места утверждения (тип квартиры, вид прибора) и ссылка на сбор;
- источник адаптера один на ревизию, класс, стадию и серию.

Требования к исходным данным и матрица готовности не хранятся: это декларации кода и
представление, считаемое при чтении.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_calc_stage_p_inputs"
down_revision: str | None = "0012_calc_facts_registry"
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

_OLD_EVIDENCE_CHECK = (
    "(kind = 'DOCUMENT_FRAGMENT' and document_revision_id is not null)"
    " or (kind = 'ASSUMPTION_BASIS' and basis is not null)"
    " or (kind = 'MANUAL_ENTRY' and author_id is not null)"
)
_EVIDENCE_CHECK = (
    _OLD_EVIDENCE_CHECK
    + " or (kind in ('REGION_TABLE', 'REGION_TEXT') and document_revision_id is not null"
    " and region_id is not null and region_sha256 is not null and region_locator is not null)"
)


def _enum(values: Sequence[str], name: str, length: int) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    op.create_table(
        "calc_source_inspections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_class", _enum(_SOURCE_CLASSES, "calc_source_class", 32), nullable=False),
        sa.Column("document_stage", _enum(_STAGES, "calc_document_stage", 16), nullable=False),
        sa.Column("building", sa.String(length=64), nullable=False),
        sa.Column("discipline", _enum(_DISCIPLINES, "calc_discipline", 8), nullable=True),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column(
            "inspected_fact_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_class <> 'MANUAL'", name=op.f("ck_calc_source_inspections_not_manual")
        ),
        sa.CheckConstraint(
            "length(btrim(building)) > 0",
            name=op.f("ck_calc_source_inspections_building_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_source_inspections_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_source_inspections")),
    )
    op.create_index(
        op.f("ix_calc_source_inspections_created_at"), "calc_source_inspections", ["created_at"]
    )
    op.create_index(
        "ix_calc_source_inspections_revision",
        "calc_source_inspections",
        ["project_id", "document_revision_id", "created_at"],
    )

    op.add_column("calc_facts", sa.Column("qualifier", sa.String(length=64), nullable=True))
    op.add_column("calc_facts", sa.Column("inspection_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_calc_facts_inspection_id_calc_source_inspections"),
        "calc_facts",
        "calc_source_inspections",
        ["inspection_id"],
        ["id"],
        ondelete="NO ACTION",
    )

    op.add_column("calc_fact_evidence", sa.Column("region_id", sa.Uuid(), nullable=True))
    op.add_column(
        "calc_fact_evidence", sa.Column("region_sha256", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "calc_fact_evidence",
        sa.Column("region_locator", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint(
        op.f("ck_calc_fact_evidence_kind_has_content"), "calc_fact_evidence", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_calc_fact_evidence_kind_has_content"), "calc_fact_evidence", _EVIDENCE_CHECK
    )

    op.create_index(
        "uq_calc_sources_adapter",
        "calc_sources",
        ["project_id", "document_revision_id", "source_class", "document_stage", "series_key"],
        unique=True,
        postgresql_where=sa.text("series_key like 'calc:recognized:%'"),
    )


def downgrade() -> None:
    op.drop_index("uq_calc_sources_adapter", table_name="calc_sources")

    # Свидетельства по блокам без своих колонок не представимы: при откате они удаляются, а
    # утверждения остаются — без свидетельства блока, но с пояснением способа извлечения.
    op.execute("delete from calc_fact_evidence where kind in ('REGION_TABLE', 'REGION_TEXT')")
    op.drop_constraint(
        op.f("ck_calc_fact_evidence_kind_has_content"), "calc_fact_evidence", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_calc_fact_evidence_kind_has_content"), "calc_fact_evidence", _OLD_EVIDENCE_CHECK
    )
    op.drop_column("calc_fact_evidence", "region_locator")
    op.drop_column("calc_fact_evidence", "region_sha256")
    op.drop_column("calc_fact_evidence", "region_id")

    op.drop_constraint(
        op.f("fk_calc_facts_inspection_id_calc_source_inspections"),
        "calc_facts",
        type_="foreignkey",
    )
    op.drop_column("calc_facts", "inspection_id")
    op.drop_column("calc_facts", "qualifier")

    op.drop_index("ix_calc_source_inspections_revision", table_name="calc_source_inspections")
    op.drop_index(
        op.f("ix_calc_source_inspections_created_at"), table_name="calc_source_inspections"
    )
    op.drop_table("calc_source_inspections")
