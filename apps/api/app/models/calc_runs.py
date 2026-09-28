"""Запуски расчётного ядра (ADR-0030, PROMPT 04).

```text
CalcRun                  запуск: калькулятор@версия, сценарий, область, снимок фактов,
                         точные версии правил, версии ядра, итог, причины блокировки
  ├── CalcRunStep × N    шаг: входы, параметры, выходы, переводы единиц, пояснение, отпечаток
  └── CalcRunResult × N  результат: значение, единица, шаг-источник, округление
```

Запуск исполняется синхронно одной транзакцией и записывается сразу в итоговом состоянии —
BLOCKED, SUCCEEDED или FAILED. Поэтому обновлений в штатной работе нет вовсе, и все три
таблицы только дописываются: триггер запрещает UPDATE и DELETE. Удалить запуск можно только
вместе с проектом — каскадом внешнего ключа (глубина триггера больше единицы).

Снимок фактов и версии правил хранятся в самом запуске (JSONB по контрактам Pydantic): после
запуска изменения реестра фактов и реестра правил его не меняют. Отдельных таблиц для входов и
допущений нет — это части запуска и шага, без самостоятельной жизни.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcResultCategory,
    CalcRuleType,
    CalcRunStatus,
    CalcScenario,
    CalcStepStatus,
)
from app.db.base import Base
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class CalcRun(CreatedAtMixin, Base):
    __tablename__ = "calc_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    calculator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    calculator_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculator_title: Mapped[str] = mapped_column(String(200), nullable=False)
    calculator_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario: Mapped[CalcScenario] = mapped_column(
        str_enum(CalcScenario, name="calc_scenario", length=16), nullable=False
    )
    scope: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    status: Mapped[CalcRunStatus] = mapped_column(
        str_enum(CalcRunStatus, name="calc_run_status", length=16), nullable=False
    )
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    """Дата, на которую выбирались действующие версии правил."""
    versions: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_bindings: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    rule_bindings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    blocking_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    # none_as_null: отсутствие — SQL NULL, а не JSON null; на этом держатся ограничения статуса.
    failure: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))
    assumptions: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    warnings: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    results_count: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    """Отпечаток запроса: тот же ключ идемпотентности с другим запросом — отказ, а не подмена."""
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    steps: Mapped[list[CalcRunStep]] = relationship(
        order_by="CalcRunStep.position", passive_deletes="all"
    )
    results: Mapped[list[CalcRunResult]] = relationship(
        order_by="CalcRunResult.position", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint("calculator_version >= 1", name="calculator_version_positive"),
        CheckConstraint(
            "(status = 'SUCCEEDED') = (result_sha256 is not null)", name="result_on_success"
        ),
        CheckConstraint(
            "(status = 'BLOCKED') = (jsonb_array_length(blocking_reasons) > 0)",
            name="reasons_on_block",
        ),
        CheckConstraint("(status = 'FAILED') = (failure is not null)", name="failure_on_fail"),
        Index("ix_calc_runs_project_id_created_at", "project_id", "created_at"),
        # Повтор запроса с тем же ключом не создаёт второй запуск.
        Index(
            "uq_calc_runs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key is not null"),
        ),
    )


class CalcRunStep(CreatedAtMixin, Base):
    __tablename__ = "calc_run_steps"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[CalcStepStatus] = mapped_column(
        str_enum(CalcStepStatus, name="calc_step_status", length=16), nullable=False
    )
    rule_key: Mapped[str | None] = mapped_column(String(120))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    rule_type: Mapped[CalcRuleType | None] = mapped_column(
        str_enum(CalcRuleType, name="calc_rule_type", length=24)
    )
    rule_content_sha256: Mapped[str | None] = mapped_column(String(64))
    implementation_key: Mapped[str | None] = mapped_column(String(120))
    inputs: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    roundings: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    assumption: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reused_from_run_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    """Запуск, из которого взят результат шага. Без внешнего ключа: ссылка — история."""

    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_calc_run_steps_key"),
        CheckConstraint(
            "(status = 'REUSED') = (reused_from_run_id is not null)", name="reuse_has_source"
        ),
    )


class CalcRunResult(CreatedAtMixin, Base):
    __tablename__ = "calc_run_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_runs.id", ondelete="CASCADE"), nullable=False
    )
    result_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    """Точное десятичное число строкой: без двоичного float и без скрытого округления."""
    unit: Mapped[str | None] = mapped_column(String(16))
    category: Mapped[CalcResultCategory] = mapped_column(
        str_enum(CalcResultCategory, name="calc_result_category", length=16), nullable=False
    )
    discipline: Mapped[CalcDiscipline] = mapped_column(
        str_enum(CalcDiscipline, name="calc_discipline", length=8), nullable=False
    )
    system_code: Mapped[str | None] = mapped_column(String(64))
    scenario: Mapped[CalcScenario] = mapped_column(
        str_enum(CalcScenario, name="calc_scenario", length=16), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[str] = mapped_column(String(40), nullable=False)
    rounding: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))

    __table_args__ = (UniqueConstraint("run_id", "result_key", name="uq_calc_run_results_key"),)


# Завершённый запуск не меняется никаким путём записи, включая прямой SQL. Исправление
# проекта — новый запуск. Удаление — только каскадом при удалении проекта: тогда триггер
# вызывается изнутри ссылочного действия, и pg_trigger_depth() больше единицы. Тот же текст — в
# миграции 0015; совпадение проверяет test_schema_matches_migrations.
_APPEND_ONLY_FUNCTION = """
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


def _install(table: str) -> Callable[..., None]:
    """Обработчик `after_create`: функция и триггер — отдельными вызовами (asyncpg)."""

    def listener(target: Table, connection: Connection, **kwargs: object) -> None:
        if connection.dialect.name != "postgresql":
            return
        connection.exec_driver_sql(_APPEND_ONLY_FUNCTION)
        connection.exec_driver_sql(_trigger(table))

    return listener


for _model in (CalcRun, CalcRunStep, CalcRunResult):
    event.listen(_model.__table__, "after_create", _install(_model.__tablename__))
