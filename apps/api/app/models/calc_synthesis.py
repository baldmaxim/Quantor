"""Запуски синтеза структуры и решения инженера (ADR-0030, PROMPT 05).

```text
CalcSynthesisRun          запуск: исходный запуск расчёта, синтезатор@версия и отпечаток
                          реализации, сценарий, снимок фактов для структуры, версии правил и
                          недоступные правила, решения на входе, граф, варианты, нерешённое
CalcSynthesisDecision     решение инженера по варианту запуска — вход следующего запуска
```

Граф хранится целиком в запуске (JSONB по контракту `CalcSystemGraph`): у узлов и связей
стабильные идентификаторы внутри запуска, и PROMPT 06 ссылается на них парой (запуск, элемент).
Нормализованные таблицы узлов и связей пока не нужны: граф читается и воспроизводится только
целиком, а объём демо и ожидаемых графов стадии П — десятки элементов.

Обе таблицы только дописываются — тот же триггер, что у запусков расчёта. Решение инженера —
не факт объекта: в реестр фактов оно не пишется.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, event, text
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.calc.enums import CalcScenario, CalcSynthesisStatus
from app.db.base import Base
from app.models.calc_runs import install_append_only
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class CalcSynthesisRun(CreatedAtMixin, Base):
    __tablename__ = "calc_synthesis_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # NO ACTION: исходный запуск расчёта не исчезает из-под синтеза; при удалении проекта
    # оба уходят каскадом одной операцией.
    calculation_run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_runs.id", ondelete="NO ACTION"), nullable=False
    )
    calculation_result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    synthesizer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    synthesizer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    synthesizer_title: Mapped[str] = mapped_column(String(200), nullable=False)
    synthesizer_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    implementation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario: Mapped[CalcScenario] = mapped_column(
        str_enum(CalcScenario, name="calc_scenario", length=16), nullable=False
    )
    scope: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    status: Mapped[CalcSynthesisStatus] = mapped_column(
        str_enum(CalcSynthesisStatus, name="calc_synthesis_status", length=16), nullable=False
    )
    versions: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_bindings: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    rule_bindings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_absences: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    """Правила, которых не было на момент запуска, и почему: повтор видит то же самое."""
    decision_inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    applied_decision_ids: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    # none_as_null: отсутствие графа — SQL NULL; на этом держится согласование со статусом.
    graph: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))
    graph_sha256: Mapped[str | None] = mapped_column(String(64))
    variants: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    unresolved: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    assumptions: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    warnings: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    blocking_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    failure: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))
    nodes_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint("synthesizer_version >= 1", name="synthesizer_version_positive"),
        CheckConstraint(
            "(status in ('SUCCEEDED', 'PARTIAL')) = (graph_sha256 is not null)",
            name="graph_on_result",
        ),
        CheckConstraint("(graph is null) = (graph_sha256 is null)", name="graph_consistent"),
        CheckConstraint(
            "(status = 'BLOCKED') = (jsonb_array_length(blocking_reasons) > 0)",
            name="reasons_on_block",
        ),
        CheckConstraint("(status = 'FAILED') = (failure is not null)", name="failure_on_fail"),
        Index("ix_calc_synthesis_runs_project_id_created_at", "project_id", "created_at"),
        Index(
            "uq_calc_synthesis_runs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key is not null"),
        ),
    )


class CalcSynthesisDecision(CreatedAtMixin, Base):
    """Решение инженера: какая кратность выбрана из диапазона запуска и почему."""

    __tablename__ = "calc_synthesis_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    synthesis_run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("calc_synthesis_runs.id", ondelete="NO ACTION"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_key: Mapped[str | None] = mapped_column(String(64))
    alternatives: Mapped[list[int]] = mapped_column(pg.JSONB, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint("selected_count >= 0", name="selected_count_non_negative"),
        CheckConstraint("length(btrim(comment)) > 0", name="comment_not_blank"),
        Index("ix_calc_synthesis_decisions_run", "synthesis_run_id"),
    )


for _model in (CalcSynthesisRun, CalcSynthesisDecision):
    event.listen(_model.__table__, "after_create", install_append_only(_model.__tablename__))
