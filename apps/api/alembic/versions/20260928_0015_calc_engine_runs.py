"""Расчётный контур: запуски расчётного ядра

Revision ID: 0015_calc_engine_runs
Revises: 0014_calc_rule_registry
Create Date: 2026-09-28

Расчётное ядро (ADR-0030, PROMPT 04) — три таблицы:

- `calc_runs` — запуск: калькулятор с версией и отпечатком, сценарий, область, дата выбора
  правил, версии ядра и политик, снимок фактов и точные версии правил с содержанием (JSONB по
  контрактам), причины блокировки, ошибка, допущения, отпечаток результата, ключ
  идемпотентности. Снимок и правила — внутри запуска: отдельная таблица входов пользы не
  дала бы, а изменения реестров после запуска его не касаются;
- `calc_run_steps` — шаги: входы с источниками и переводами единиц, параметры, выходы,
  пояснение, отпечаток, источник повторного использования, допущение;
- `calc_run_results` — инженерные величины запуска с шагом-источником и явным округлением.
  Это ещё не позиции Расчётного паспорта.

Запуск записывается одной транзакцией сразу в итоговом состоянии, поэтому все три таблицы
только дописываются: триггер `calc_runs_append_only` запрещает UPDATE и DELETE, кроме
каскада при удалении проекта.

Откат удаляет таблицы вместе с запусками: до этой ревизии хранить их было негде.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_calc_engine_runs"
down_revision: str | None = "0014_calc_rule_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("calc_runs", "calc_run_steps", "calc_run_results")

# Тот же текст, что в `app/models/calc_runs.py`; совпадение проверяет
# test_schema_matches_migrations.
APPEND_ONLY_FUNCTION = """
create or replace function calc_runs_append_only() returns trigger
language plpgsql as $$
begin
    if tg_op = 'DELETE' and pg_trigger_depth() > 1 then
        return old;
    end if;
    raise exception '% is append-only: a calculation run is never changed, start a new run',
        tg_table_name;
end
$$
"""


def _trigger(table: str) -> str:
    return (
        f"create trigger trg_{table}_append_only before update or delete on {table} "
        "for each row execute function calc_runs_append_only()"
    )


def upgrade() -> None:
    op.create_table(
        "calc_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("calculator_id", sa.String(length=100), nullable=False),
        sa.Column("calculator_version", sa.Integer(), nullable=False),
        sa.Column("calculator_title", sa.String(length=200), nullable=False),
        sa.Column("calculator_sha256", sa.String(length=64), nullable=False),
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
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "BLOCKED",
                "SUCCEEDED",
                "FAILED",
                name="calc_run_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("rule_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_bindings_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "blocking_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("results_count", sa.Integer(), nullable=False),
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
            "(status = 'BLOCKED') = (jsonb_array_length(blocking_reasons) > 0)",
            name=op.f("ck_calc_runs_reasons_on_block"),
        ),
        sa.CheckConstraint(
            "(status = 'FAILED') = (failure is not null)", name=op.f("ck_calc_runs_failure_on_fail")
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED') = (result_sha256 is not null)",
            name=op.f("ck_calc_runs_result_on_success"),
        ),
        sa.CheckConstraint(
            "calculator_version >= 1", name=op.f("ck_calc_runs_calculator_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_calc_runs_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_runs")),
    )
    op.create_index(op.f("ix_calc_runs_created_at"), "calc_runs", ["created_at"], unique=False)
    op.create_index(
        "ix_calc_runs_project_id_created_at",
        "calc_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_calc_runs_idempotency",
        "calc_runs",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key is not null"),
    )
    op.create_table(
        "calc_run_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("result_key", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "INTERMEDIATE",
                "ENGINEERING",
                name="calc_result_category",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "discipline",
            sa.Enum(
                "VK", "OV", "EOM", "SS", "APT", name="calc_discipline", native_enum=False, length=8
            ),
            nullable=False,
        ),
        sa.Column("system_code", sa.String(length=64), nullable=True),
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
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("output", sa.String(length=40), nullable=False),
        sa.Column("rounding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["calc_runs.id"],
            name=op.f("fk_calc_run_results_run_id_calc_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_run_results")),
        sa.UniqueConstraint("run_id", "result_key", name="uq_calc_run_results_key"),
    )
    op.create_index(
        op.f("ix_calc_run_results_created_at"), "calc_run_results", ["created_at"], unique=False
    )
    op.create_table(
        "calc_run_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "EXECUTED",
                "REUSED",
                "NOT_APPLIED",
                name="calc_step_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(length=120), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=True),
        sa.Column(
            "rule_type",
            sa.Enum(
                "PHYSICS",
                "GEOMETRY",
                "NORMATIVE",
                "MANUFACTURER",
                "ENGINEERING",
                "TENDER_ASSUMPTION",
                name="calc_rule_type",
                native_enum=False,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("rule_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("implementation_key", sa.String(length=120), nullable=True),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "roundings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("assumption", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reused_from_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'REUSED') = (reused_from_run_id is not null)",
            name=op.f("ck_calc_run_steps_reuse_has_source"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["calc_runs.id"],
            name=op.f("fk_calc_run_steps_run_id_calc_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_run_steps")),
        sa.UniqueConstraint("run_id", "step_key", name="uq_calc_run_steps_key"),
    )
    op.create_index(
        op.f("ix_calc_run_steps_created_at"), "calc_run_steps", ["created_at"], unique=False
    )

    # asyncpg не принимает несколько команд в одном подготовленном запросе.
    op.execute(APPEND_ONLY_FUNCTION)
    for table in _TABLES:
        op.execute(_trigger(table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"drop trigger if exists trg_{table}_append_only on {table}")
    op.execute("drop function if exists calc_runs_append_only()")

    op.drop_index(op.f("ix_calc_run_steps_created_at"), table_name="calc_run_steps")
    op.drop_table("calc_run_steps")
    op.drop_index(op.f("ix_calc_run_results_created_at"), table_name="calc_run_results")
    op.drop_table("calc_run_results")
    op.drop_index("uq_calc_runs_idempotency", table_name="calc_runs")
    op.drop_index("ix_calc_runs_project_id_created_at", table_name="calc_runs")
    op.drop_index(op.f("ix_calc_runs_created_at"), table_name="calc_runs")
    op.drop_table("calc_runs")
