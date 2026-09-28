"""Расчётный контур: синтез структуры системы

Revision ID: 0016_calc_system_synthesis
Revises: 0015_calc_engine_runs
Create Date: 2026-09-28

Синтез структуры инженерной системы стадии П (ADR-0030, PROMPT 05) — две таблицы:

- `calc_synthesis_runs` — запуск синтеза: исходный запуск расчёта и отпечаток его результата,
  синтезатор с версией, отпечатками определения и реализации, сценарий, область, снимок фактов
  для структуры, версии правил и недоступные правила, решения инженера на входе, граф системы
  целиком (JSONB по контракту), варианты, нерешённое, допущения, итог. Граф — внутри запуска:
  у элементов стабильные идентификаторы, отдельные таблицы узлов и связей пока не нужны;
- `calc_synthesis_decisions` — решение инженера по варианту запуска: какая кратность выбрана,
  из каких альтернатив, кем и почему. Это вход следующего запуска, а не факт объекта.

Обе таблицы только дописываются — триггер той же функции `calc_runs_append_only` (ревизия
0015), кроме каскада при удалении проекта.

Откат удаляет таблицы вместе с запусками синтеза и решениями.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_calc_system_synthesis"
down_revision: str | None = "0015_calc_engine_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("calc_synthesis_runs", "calc_synthesis_decisions")


def _trigger(table: str) -> str:
    return (
        f"create trigger trg_{table}_append_only before update or delete on {table} "
        "for each row execute function calc_runs_append_only()"
    )


def upgrade() -> None:
    op.create_table(
        "calc_synthesis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("calculation_run_id", sa.UUID(), nullable=False),
        sa.Column("calculation_result_sha256", sa.String(length=64), nullable=False),
        sa.Column("synthesizer_id", sa.String(length=100), nullable=False),
        sa.Column("synthesizer_version", sa.Integer(), nullable=False),
        sa.Column("synthesizer_title", sa.String(length=200), nullable=False),
        sa.Column("synthesizer_sha256", sa.String(length=64), nullable=False),
        sa.Column("implementation_sha256", sa.String(length=64), nullable=False),
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
                "PARTIAL",
                "SUCCEEDED",
                "FAILED",
                name="calc_synthesis_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("rule_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_bindings_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_absences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "decision_inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "applied_decision_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "graph", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("graph_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "variants", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "unresolved",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "blocking_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "failure", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("nodes_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
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
            name=op.f("ck_calc_synthesis_runs_reasons_on_block"),
        ),
        sa.CheckConstraint(
            "(status = 'FAILED') = (failure is not null)",
            name=op.f("ck_calc_synthesis_runs_failure_on_fail"),
        ),
        sa.CheckConstraint(
            "(status in ('SUCCEEDED', 'PARTIAL')) = (graph_sha256 is not null)",
            name=op.f("ck_calc_synthesis_runs_graph_on_result"),
        ),
        sa.CheckConstraint(
            "(graph is null) = (graph_sha256 is null)",
            name=op.f("ck_calc_synthesis_runs_graph_consistent"),
        ),
        sa.CheckConstraint(
            "synthesizer_version >= 1",
            name=op.f("ck_calc_synthesis_runs_synthesizer_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calc_runs.id"],
            name=op.f("fk_calc_synthesis_runs_calculation_run_id_calc_runs"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_synthesis_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_calc_synthesis_runs_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_synthesis_runs")),
    )
    op.create_index(
        op.f("ix_calc_synthesis_runs_created_at"),
        "calc_synthesis_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_calc_synthesis_runs_project_id_created_at",
        "calc_synthesis_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_calc_synthesis_runs_idempotency",
        "calc_synthesis_runs",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key is not null"),
    )
    op.create_table(
        "calc_synthesis_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("synthesis_run_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("variant_key", sa.String(length=64), nullable=True),
        sa.Column("alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(comment)) > 0", name=op.f("ck_calc_synthesis_decisions_comment_not_blank")
        ),
        sa.CheckConstraint(
            "selected_count >= 0",
            name=op.f("ck_calc_synthesis_decisions_selected_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calc_synthesis_decisions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["synthesis_run_id"],
            ["calc_synthesis_runs.id"],
            name=op.f("fk_calc_synthesis_decisions_synthesis_run_id_calc_synthesis_runs"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_synthesis_decisions")),
    )
    op.create_index(
        op.f("ix_calc_synthesis_decisions_created_at"),
        "calc_synthesis_decisions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_calc_synthesis_decisions_run",
        "calc_synthesis_decisions",
        ["synthesis_run_id"],
        unique=False,
    )

    # Функция calc_runs_append_only создана ревизией 0015; здесь — только триггеры.
    for table in _TABLES:
        op.execute(_trigger(table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"drop trigger if exists trg_{table}_append_only on {table}")
    op.drop_index("ix_calc_synthesis_decisions_run", table_name="calc_synthesis_decisions")
    op.drop_index(
        op.f("ix_calc_synthesis_decisions_created_at"), table_name="calc_synthesis_decisions"
    )
    op.drop_table("calc_synthesis_decisions")
    op.drop_index("uq_calc_synthesis_runs_idempotency", table_name="calc_synthesis_runs")
    op.drop_index("ix_calc_synthesis_runs_project_id_created_at", table_name="calc_synthesis_runs")
    op.drop_index(op.f("ix_calc_synthesis_runs_created_at"), table_name="calc_synthesis_runs")
    op.drop_table("calc_synthesis_runs")
