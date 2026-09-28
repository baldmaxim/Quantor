"""Расчётные паспорта систем и ожидаемые количества (ADR-0030, PROMPT 06).

```text
CalcPassport               паспорт системы: комплект расчёта ВК (batch), система, область,
                           калькулятор и синтезатор с отпечатками, запуски трёх сценариев,
                           разделы паспорта (JSONB по контракту), итоговый статус
  └── CalcExpectedQuantity позиция: стабильный ключ, сценарий, категория, тип, значение или
                           диапазон, полнота, происхождение, ссылки на запуски и элементы графа
```

Ключ позиции (`vk.b1.pipe.riser`) стабилен между паспортами: по нему PROMPT 09 сопоставит
позицию с ВОР Заказчика и сравнит паспорта. Технические характеристики хранятся
структурированно: значение, диапазон, единица, типоразмер, материал — колонками, остальное —
телом позиции по контракту.

Обе таблицы только дописываются — триггер той же функции `calc_runs_append_only`, кроме
каскада при удалении проекта. Пересчёт — новый паспорт.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.contracts.calc.enums import (
    CalcCompleteness,
    CalcDiscipline,
    CalcPassportStatus,
    CalcQuantityCategory,
    CalcQuantityDerivation,
    CalcScenario,
)
from app.db.base import Base
from app.models.calc_runs import install_append_only
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class CalcPassport(CreatedAtMixin, Base):
    __tablename__ = "calc_passports"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    """Комплект расчёта: паспорта систем одного нажатия «Рассчитать ВК»."""
    system_code: Mapped[str] = mapped_column(String(64), nullable=False)
    system_title: Mapped[str] = mapped_column(String(200), nullable=False)
    discipline: Mapped[CalcDiscipline] = mapped_column(
        str_enum(CalcDiscipline, name="calc_discipline", length=8), nullable=False
    )
    scope: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    scope_key: Mapped[str] = mapped_column(String(480), nullable=False)
    status: Mapped[CalcPassportStatus] = mapped_column(
        str_enum(CalcPassportStatus, name="calc_passport_status", length=16), nullable=False
    )
    calculator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    calculator_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculator_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    synthesizer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    synthesizer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    implementation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    runs: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    """Запуски расчёта и синтеза по сценариям — ссылки на неизменяемые запуски."""
    body: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    passport_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quantities_count: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    quantities: Mapped[list[CalcExpectedQuantity]] = relationship(
        order_by="CalcExpectedQuantity.position", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint("calculator_version >= 1", name="calculator_version_positive"),
        CheckConstraint("quantities_count >= 0", name="quantities_count_positive"),
        Index("ix_calc_passports_project_id_created_at", "project_id", "created_at"),
        Index("ix_calc_passports_batch_id", "batch_id"),
        # Повтор запроса комплекта с тем же ключом не создаёт вторые паспорта.
        Index(
            "uq_calc_passports_idempotency",
            "project_id",
            "idempotency_key",
            "system_code",
            "scope_key",
            unique=True,
            postgresql_where=text("idempotency_key is not null"),
        ),
    )


class CalcExpectedQuantity(CreatedAtMixin, Base):
    __tablename__ = "calc_expected_quantities"

    id: Mapped[uuid.UUID] = uuid_pk()
    passport_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_passports.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_key: Mapped[str] = mapped_column(String(120), nullable=False)
    scenario: Mapped[CalcScenario] = mapped_column(
        str_enum(CalcScenario, name="calc_scenario", length=16), nullable=False
    )
    system_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[CalcQuantityCategory] = mapped_column(
        str_enum(CalcQuantityCategory, name="calc_quantity_category", length=16), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(48), nullable=False)
    completeness: Mapped[CalcCompleteness] = mapped_column(
        str_enum(CalcCompleteness, name="calc_completeness", length=24), nullable=False
    )
    derivation: Mapped[CalcQuantityDerivation] = mapped_column(
        str_enum(CalcQuantityDerivation, name="calc_quantity_derivation", length=16),
        nullable=False,
    )
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    """Точное десятичное число строкой — или пусто, если диапазон или «не определено»."""
    low: Mapped[str | None] = mapped_column(Text)
    high: Mapped[str | None] = mapped_column(Text)
    size: Mapped[str | None] = mapped_column(String(64))
    """Типоразмер из документа; пусто — UNKNOWN, диаметр не угадывается."""
    material: Mapped[str | None] = mapped_column(Text)
    calculation_run_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    synthesis_run_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    body: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "passport_id", "scenario", "quantity_key", name="uq_calc_expected_quantities_key"
        ),
        CheckConstraint("(low is null) = (high is null)", name="range_has_both_bounds"),
        CheckConstraint("value is null or low is null", name="value_or_range"),
        # «Не определено» не бывает числом: у BLOCKED нет ни значения, ни диапазона.
        CheckConstraint(
            "(completeness = 'BLOCKED') = (value is null and low is null)",
            name="blocked_has_no_value",
        ),
    )


for _model in (CalcPassport, CalcExpectedQuantity):
    event.listen(_model.__table__, "after_create", install_append_only(_model.__tablename__))
