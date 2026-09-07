"""Журнал административных действий.

Только добавление. Записи не редактируются и не удаляются, и держится это на двух
уровнях сразу: в API нет ни одной операции изменения, а база отвергает `update` и
`delete` триггером. Одного уровня мало — API можно обойти, а забытый триггер нечем
заметить.

Два отступления от общего стиля моделей, оба намеренные:

- **внешних ключей нет.** Ключ с `on delete set null` — это `update`, который триггер
  обязан отвергнуть; к тому же журнал должен пережить удаление того, о чём рассказывает.
  Поэтому личность актора продублирована текстом в `actor_label`;
- **`action` — обычная строка, а не перечисление с CHECK.** Словарь действий пополняется
  каждый этап, и миграция на каждое новое действие была бы трением без выигрыша.
  Соответствие `AuditAction` проверяется тестом.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Index, String, event
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Table

from app.db.base import Base
from app.domain import AuditResult
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class AuditEvent(CreatedAtMixin, Base):
    """Одно записанное действие."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()

    # --- кто ---
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    actor_label: Mapped[str | None] = mapped_column(String(320))
    """Почта или издатель:субъект. Копия намеренная: журнал переживает удаление личности."""
    actor_role: Mapped[str | None] = mapped_column(String(32))
    credential: Mapped[str | None] = mapped_column(String(16))

    # --- где ---
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    # --- что ---
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))

    result: Mapped[AuditResult] = mapped_column(
        str_enum(AuditResult, name="audit_result"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(64))

    # Безопасные сводки состояния до и после. Секреты вычищаются на записи, а не на
    # чтении: вычищенное на чтении уже лежит в базе и уже утекло в резервную копию.
    before_summary: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB)
    after_summary: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB)

    # --- откуда ---
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_audit_events_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_audit_events_actor_user_id_created_at", "actor_user_id", "created_at"),
        Index("ix_audit_events_action_created_at", "action", "created_at"),
        Index("ix_audit_events_resource_type_resource_id", "resource_type", "resource_id"),
    )


# Триггер вешается на создание таблицы, а не только в миграции: тестовая база собирается
# из метаданных, минуя Alembic, и без этого проверка «журнал нельзя переписать» проверяла
# бы пустоту.
#
# `truncate` строковые триггеры не вызывает, поэтому очистка таблиц между тестами
# продолжает работать.
_APPEND_ONLY_SQL = """
create or replace function audit_events_append_only() returns trigger
language plpgsql as $$
begin
    raise exception 'audit_events is append-only';
end
$$;

create trigger trg_audit_events_append_only
before update or delete on audit_events
for each row execute function audit_events_append_only();
"""


def _install_append_only(target: Table, connection: Connection, **kwargs: object) -> None:
    """Вешает запрет на изменение сразу после создания таблицы.

    Обычным обработчиком, а не `DDL(...).execute_if(...)`: конструктор `DDL` не
    типизирован, а подавлять проверку типов правилами проекта запрещено.
    """
    if connection.dialect.name != "postgresql":
        return
    connection.exec_driver_sql(_APPEND_ONLY_SQL)


event.listen(AuditEvent.__table__, "after_create", _install_append_only)
