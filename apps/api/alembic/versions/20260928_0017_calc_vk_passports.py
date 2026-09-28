"""Расчётный контур: паспорта систем ВК и ожидаемые количества

Revision ID: 0017_calc_vk_passports
Revises: 0016_calc_system_synthesis
Create Date: 2026-09-28

Рабочий калькулятор ВК стадии П (ADR-0030, PROMPT 06):

- `calc_passports` — Расчётный паспорт системы: комплект расчёта, система, область,
  калькулятор и синтезатор с отпечатками, ссылки на запуски трёх сценариев, разделы паспорта
  (JSONB по контракту), итоговый статус READY / PARTIAL / BLOCKED;
- `calc_expected_quantities` — позиция паспорта: стабильный ключ, сценарий, категория, тип,
  значение или диапазон, полнота, происхождение, типоразмер и материал колонками, тело позиции
  по контракту. «Не определено» числом не бывает — ограничение `blocked_has_no_value`.

Обе таблицы только дописываются — триггер функции `calc_runs_append_only` (ревизия 0015).

Запуски расчёта получают статус PARTIAL: часть шагов выполнена, часть заблокирована своими
причинами. Ограничения `result_on_success` и `reasons_on_block` расширяются на него; прежние
запуски не меняются. Откат отказывает, если частичные запуски уже есть: прежние ограничения
их не допускают, а удалять неизменяемые запуски откат не вправе.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_calc_vk_passports"
down_revision: str | None = "0016_calc_system_synthesis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("calc_passports", "calc_expected_quantities")
_RUN_CHECKS = {
    "result_on_success": (
        "(status in ('SUCCEEDED', 'PARTIAL')) = (result_sha256 is not null)",
        "(status = 'SUCCEEDED') = (result_sha256 is not null)",
    ),
    "reasons_on_block": (
        "(status in ('BLOCKED', 'PARTIAL')) = (jsonb_array_length(blocking_reasons) > 0)",
        "(status = 'BLOCKED') = (jsonb_array_length(blocking_reasons) > 0)",
    ),
}


def _trigger(table: str) -> str:
    return (
        f"create trigger trg_{table}_append_only before update or delete on {table} "
        "for each row execute function calc_runs_append_only()"
    )


def _run_checks(index: int) -> None:
    for name, definitions in _RUN_CHECKS.items():
        op.drop_constraint(op.f(f"ck_calc_runs_{name}"), "calc_runs", type_="check")
        op.create_check_constraint(op.f(f"ck_calc_runs_{name}"), "calc_runs", definitions[index])


def upgrade() -> None:
    _run_checks(0)
    op.create_table(
        "calc_passports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column("system_title", sa.String(length=200), nullable=False),
        sa.Column(
            "discipline",
            sa.Enum(
                "VK", "OV", "EOM", "SS", "APT", name="calc_discipline", native_enum=False, length=8
            ),
            nullable=False,
        ),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scope_key", sa.String(length=480), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "READY",
                "PARTIAL",
                "BLOCKED",
                name="calc_passport_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("calculator_id", sa.String(length=100), nullable=False),
        sa.Column("calculator_version", sa.Integer(), nullable=False),
        sa.Column("calculator_sha256", sa.String(length=64), nullable=False),
        sa.Column("synthesizer_id", sa.String(length=100), nullable=False),
        sa.Column("synthesizer_version", sa.Integer(), nullable=False),
        sa.Column("implementation_sha256", sa.String(length=64), nullable=False),
        sa.Column("runs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("passport_sha256", sa.String(length=64), nullable=False),
        sa.Column("quantities_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "calculator_version >= 1", name=op.f("ck_calc_passports_calculator_version_positive")
        ),
        sa.CheckConstraint(
            "quantities_count >= 0", name=op.f("ck_calc_passports_quantities_count_positive")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_passports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_calc_passports_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_passports")),
    )
    op.create_index("ix_calc_passports_batch_id", "calc_passports", ["batch_id"], unique=False)
    op.create_index(
        op.f("ix_calc_passports_created_at"), "calc_passports", ["created_at"], unique=False
    )
    op.create_index(
        "ix_calc_passports_project_id_created_at",
        "calc_passports",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_calc_passports_idempotency",
        "calc_passports",
        ["project_id", "idempotency_key", "system_code", "scope_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key is not null"),
    )
    op.create_table(
        "calc_expected_quantities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("passport_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("quantity_key", sa.String(length=120), nullable=False),
        sa.Column(
            "scenario",
            sa.Enum(
                "MINIMUM",
                "EXPECTED",
                "TENDER_SAFE",
                name="calc_scenario",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "PIPE",
                "INSULATION",
                "FITTING",
                "VALVE",
                "EQUIPMENT",
                "SUPPORT",
                "SLEEVE",
                "CONNECTION",
                "OTHER",
                name="calc_quantity_category",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=48), nullable=False),
        sa.Column(
            "completeness",
            sa.Enum(
                "COMPLETE",
                "RANGE",
                "PARTIAL",
                "UNRESOLVED_BREAKDOWN",
                "BLOCKED",
                name="calc_completeness",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "derivation",
            sa.Enum(
                "OBSERVED",
                "CALCULATED",
                "TOPOLOGY",
                "RULE",
                "FALLBACK",
                "AGGREGATE",
                "NOT_DETERMINED",
                name="calc_quantity_derivation",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("low", sa.Text(), nullable=True),
        sa.Column("high", sa.Text(), nullable=True),
        sa.Column("size", sa.String(length=64), nullable=True),
        sa.Column("material", sa.Text(), nullable=True),
        sa.Column("calculation_run_id", sa.UUID(), nullable=True),
        sa.Column("synthesis_run_id", sa.UUID(), nullable=True),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(completeness = 'BLOCKED') = (value is null and low is null)",
            name=op.f("ck_calc_expected_quantities_blocked_has_no_value"),
        ),
        sa.CheckConstraint(
            "(low is null) = (high is null)",
            name=op.f("ck_calc_expected_quantities_range_has_both_bounds"),
        ),
        sa.CheckConstraint(
            "value is null or low is null", name=op.f("ck_calc_expected_quantities_value_or_range")
        ),
        sa.ForeignKeyConstraint(
            ["passport_id"],
            ["calc_passports.id"],
            name=op.f("fk_calc_expected_quantities_passport_id_calc_passports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_expected_quantities")),
        sa.UniqueConstraint(
            "passport_id", "scenario", "quantity_key", name="uq_calc_expected_quantities_key"
        ),
    )
    op.create_index(
        op.f("ix_calc_expected_quantities_created_at"),
        "calc_expected_quantities",
        ["created_at"],
        unique=False,
    )
    for table in _TABLES:
        op.execute(_trigger(table))


def downgrade() -> None:
    op.execute(
        "do $$ begin if exists (select 1 from calc_runs where status = 'PARTIAL') then "
        "raise exception 'calc_runs has PARTIAL runs: downgrade below 0017 would break them'; "
        "end if; end $$"
    )
    for table in reversed(_TABLES):
        op.execute(f"drop trigger if exists trg_{table}_append_only on {table}")
    op.drop_index(
        op.f("ix_calc_expected_quantities_created_at"), table_name="calc_expected_quantities"
    )
    op.drop_table("calc_expected_quantities")
    op.drop_index(
        "uq_calc_passports_idempotency",
        table_name="calc_passports",
        postgresql_where=sa.text("idempotency_key is not null"),
    )
    op.drop_index("ix_calc_passports_project_id_created_at", table_name="calc_passports")
    op.drop_index(op.f("ix_calc_passports_created_at"), table_name="calc_passports")
    op.drop_index("ix_calc_passports_batch_id", table_name="calc_passports")
    op.drop_table("calc_passports")
    _run_checks(1)
