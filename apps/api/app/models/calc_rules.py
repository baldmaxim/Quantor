"""Реестр правил расчётного контура (ADR-0030, PROMPT 03).

```text
CalcRuleDefinition       стабильный ключ правила в пространстве: `vk.riser.vertical_length`
  └── CalcRuleVersion × N    содержание версии, статус, кто и когда утвердил или вывел
        └── CalcRuleReview × N   решение проверяющего: из какого статуса, в какой, почему
```

Здесь только правила Quantor. 365 правил старого портала — карантинный каталог в данных
пакета (`services/calc/rules/data`): в этих таблицах их нет, и статуса UNVERIFIED_LEGACY
таблица версий не принимает.

Содержание версии хранится колонками и JSONB по частям контракта `CalcRuleContent`: строгую
структуру проверяет Pydantic, база хранит и защищает. Исполняемого кода нет ни в одной
колонке — только текст формулы и ключ детерминированной реализации.

Неизменяемость утверждённой версии держит триггер базы, а не только сервис: изменить
содержание версии не в статусе DRAFT, вернуть её в черновик или удалить её нельзя никаким
путём записи, включая прямой UPDATE. Журнал решений только дописывается.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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

from app.contracts.calc.enums import CalcDiscipline, CalcRuleStatus, CalcRuleType
from app.db.base import Base
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk

# Правила старого портала в рабочие таблицы не попадают: только собственные статусы Quantor.
_OWN_STATUSES = "status in ('DRAFT', 'APPROVED', 'DEPRECATED', 'REJECTED')"


class CalcRuleDefinition(CreatedAtMixin, Base):
    """Логическое правило: стабильный ключ без версии. Ключ не меняется никогда."""

    __tablename__ = "calc_rule_definitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(120), nullable=False)
    discipline: Mapped[CalcDiscipline] = mapped_column(
        str_enum(CalcDiscipline, name="calc_discipline", length=8), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    # passive_deletes="all": ORM не обнуляет ссылки дочерних строк при удалении — решает база
    # (внешний ключ и триггер), а не молчаливое «осиротение» версий и решений.
    versions: Mapped[list[CalcRuleVersion]] = relationship(
        back_populates="rule", order_by="CalcRuleVersion.version", passive_deletes="all"
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "rule_key", name="uq_calc_rule_definitions_key"),
    )


class CalcRuleVersion(CreatedAtMixin, Base):
    """Версия правила. Черновик редактируется; после решения содержание неизменно."""

    __tablename__ = "calc_rule_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    # NO ACTION: логическое правило не удаляется из-под своих версий.
    rule_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("calc_rule_definitions.id", ondelete="NO ACTION"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CalcRuleStatus] = mapped_column(
        str_enum(CalcRuleStatus, name="calc_rule_status", length=24),
        nullable=False,
        default=CalcRuleStatus.DRAFT,
        server_default=CalcRuleStatus.DRAFT.value,
    )

    # Содержание версии — части контракта CalcRuleContent.
    rule_type: Mapped[CalcRuleType] = mapped_column(
        str_enum(CalcRuleType, name="calc_rule_type", length=24), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    formula_text: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_key: Mapped[str | None] = mapped_column(String(120))
    inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    dimension_checks: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    applicability: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    impact: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    legacy_provenance: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    """Снимок карантинного каталога: от каких старых правил версия происходит и их опасности."""
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    edited_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    """Последний, кто менял содержание черновика: утверждать свою правку он не может."""

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    deprecation_reason: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    rule: Mapped[CalcRuleDefinition] = relationship(back_populates="versions")
    reviews: Mapped[list[CalcRuleReview]] = relationship(
        back_populates="rule_version", order_by="CalcRuleReview.created_at", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint(_OWN_STATUSES, name="own_statuses"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "valid_from is null or valid_to is null or valid_from <= valid_to", name="valid_period"
        ),
        # Утверждённая и устаревшая версии прошли утверждение, отклонённая и черновик — нет.
        CheckConstraint(
            "(approved_at is not null) = (status in ('APPROVED', 'DEPRECATED'))",
            name="approval_consistent",
        ),
        CheckConstraint(
            "(deprecated_at is not null) = (status = 'DEPRECATED')", name="deprecation_consistent"
        ),
        CheckConstraint(
            "(rejected_at is not null) = (status = 'REJECTED')", name="rejection_consistent"
        ),
        CheckConstraint(
            "status not in ('APPROVED', 'DEPRECATED') or implementation_key is not null",
            name="approved_has_implementation",
        ),
        UniqueConstraint("rule_id", "version", name="uq_calc_rule_versions_version"),
        # Один черновик на правило: новая версия открывается, когда прежний черновик решён.
        Index(
            "uq_calc_rule_versions_draft",
            "rule_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        # Одна действующая утверждённая версия: для нового расчёта выбор однозначен.
        Index(
            "uq_calc_rule_versions_approved",
            "rule_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
    )


class CalcRuleReview(CreatedAtMixin, Base):
    """Решение по версии: утверждение, отклонение, вывод из действия. Только дописывается."""

    __tablename__ = "calc_rule_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("calc_rule_versions.id", ondelete="NO ACTION"),
        nullable=False,
    )
    from_status: Mapped[CalcRuleStatus] = mapped_column(
        str_enum(CalcRuleStatus, name="calc_rule_status", length=24), nullable=False
    )
    to_status: Mapped[CalcRuleStatus] = mapped_column(
        str_enum(CalcRuleStatus, name="calc_rule_status", length=24), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    legacy_review: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    """Разбор старых правил: по каждой опасности — итог и комментарий."""

    rule_version: Mapped[CalcRuleVersion] = relationship(back_populates="reviews")

    __table_args__ = (
        CheckConstraint("from_status <> to_status", name="changes_status"),
        CheckConstraint("length(btrim(comment)) > 0", name="comment_not_blank"),
        Index("ix_calc_rule_reviews_rule_version_id", "rule_version_id"),
    )


# Защита в базе, а не только в сервисе: сервис ловит ошибку пользователя, триггер — ошибку
# программиста и прямую запись мимо API. Вешается и здесь, и в миграции 0014: тестовая база
# строится из метаданных, минуя Alembic, и без этого проверка неизменяемости проверяла бы
# пустоту. `truncate` строковые триггеры не вызывает — очистка таблиц между тестами работает.
#
# Правила переходов:
# - DRAFT: содержание меняется; DRAFT → APPROVED | REJECTED; удалить можно;
# - APPROVED: меняются только статус (→ DEPRECATED) и поля вывода из действия;
# - DEPRECATED, REJECTED: не меняется ничего;
# - ключ правила, номер, автор и время создания версии не меняются никогда;
# - удалить версию не в статусе DRAFT нельзя.
_VERSION_GUARD_FUNCTION = """
create or replace function calc_rule_versions_guard() returns trigger
language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        if old.status <> 'DRAFT' then
            raise exception 'calc_rule_versions: % version cannot be deleted', old.status;
        end if;
        return old;
    end if;
    if new is not distinct from old then
        return new;
    end if;
    if (new.id, new.rule_id, new.version, new.created_at, new.created_by)
        is distinct from (old.id, old.rule_id, old.version, old.created_at, old.created_by) then
        raise exception 'calc_rule_versions: identity of a version is immutable';
    end if;
    if old.status = 'DRAFT' then
        if new.status not in ('DRAFT', 'APPROVED', 'REJECTED') then
            raise exception 'calc_rule_versions: transition % -> % is not allowed',
                old.status, new.status;
        end if;
        return new;
    end if;
    if old.status = 'APPROVED' and new.status in ('APPROVED', 'DEPRECATED')
        and (to_jsonb(new) - array['status', 'deprecated_at', 'deprecated_by',
                                   'deprecation_reason'])
            = (to_jsonb(old) - array['status', 'deprecated_at', 'deprecated_by',
                                     'deprecation_reason']) then
        return new;
    end if;
    raise exception 'calc_rule_versions: % version is immutable, create a new version',
        old.status;
end
$$
"""

_VERSION_GUARD_TRIGGER = """
create trigger trg_calc_rule_versions_guard
before update or delete on calc_rule_versions
for each row execute function calc_rule_versions_guard()
"""

_APPEND_ONLY_FUNCTION = """
create or replace function calc_rules_append_only() returns trigger
language plpgsql as $$
begin
    raise exception '% is append-only', tg_table_name;
end
$$
"""

# Ключ правила стабилен: определение не переписывается. Удалить его не даст внешний ключ
# версий, а версию не в статусе DRAFT — триггер выше.
_DEFINITIONS_TRIGGER = """
create trigger trg_calc_rule_definitions_append_only
before update on calc_rule_definitions
for each row execute function calc_rules_append_only()
"""

_REVIEWS_TRIGGER = """
create trigger trg_calc_rule_reviews_append_only
before update or delete on calc_rule_reviews
for each row execute function calc_rules_append_only()
"""


def _install(*statements: str) -> Callable[..., None]:
    """Обработчик `after_create`: обычной функцией, а не `DDL(...)` — тот не типизирован.

    asyncpg не принимает несколько команд в одном подготовленном запросе, поэтому функция и
    триггер выполняются отдельными вызовами.
    """

    def listener(target: Table, connection: Connection, **kwargs: object) -> None:
        if connection.dialect.name != "postgresql":
            return
        for statement in statements:
            connection.exec_driver_sql(statement)

    return listener


event.listen(
    CalcRuleDefinition.__table__,
    "after_create",
    _install(_APPEND_ONLY_FUNCTION, _DEFINITIONS_TRIGGER),
)
event.listen(
    CalcRuleVersion.__table__,
    "after_create",
    _install(_VERSION_GUARD_FUNCTION, _VERSION_GUARD_TRIGGER),
)
event.listen(
    CalcRuleReview.__table__,
    "after_create",
    _install(_APPEND_ONLY_FUNCTION, _REVIEWS_TRIGGER),
)
