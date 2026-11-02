"""Версия тендера: замороженный комплект ревизий документов (ADR-0035).

```text
Project
  └── TenderVersion × N            черновик собирается, замороженная неизменна
        └── TenderVersionDocument × N   по одной ревизии на документ, раздел, участие в модели
```

Версия тендера не ссылается на `plangeom`, модель здания и Revit: это ответ на вопрос «по каким
чертежам». Необязательная связь с версией HUBTender — только записанные значения
(`external_tender_id`, `external_version`); писать на ту сторону портал не умеет.

Неизменяемость замороженной версии держит триггер базы, а не только сервис: изменить и удалить
замороженную строку, а также добавить, изменить и удалить строку её состава нельзя никаким
путём записи, включая прямой SQL. Образец — `calc_rule_versions` (ADR-0030). Ревизию из состава
версии удалить нельзя внешним ключом RESTRICT.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain import TenderVersionStatus
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class TenderVersion(CreatedAtMixin, Base):
    __tablename__ = "tender_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)

    # Порядковый номер в проекте. Выдаётся сервисом под блокировкой проекта: max + 1.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))

    # Необязательная связь со строкой `tenders` в HUBTender. Несколько комплектов могут
    # ссылаться на одну строку, если документы менялись без клонирования тендера.
    external_tender_id: Mapped[str | None] = mapped_column(String(128))
    external_version: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[TenderVersionStatus] = mapped_column(
        str_enum(TenderVersionStatus, name="tender_version_status"),
        nullable=False,
        default=TenderVersionStatus.DRAFT,
        server_default=TenderVersionStatus.DRAFT.value,
    )
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        # Составной ключ держит согласованность пространства: версия не может оказаться в
        # одном пространстве, а её проект — в другом. RESTRICT: проект не исчезает из-под версий.
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("project_id", "number", name="uq_tender_versions_project_number"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint(
            "status <> 'frozen' or (manifest_sha256 is not null and frozen_at is not null)",
            name="frozen_has_manifest",
        ),
        # Не больше одного черновика на проект: два параллельных комплекта не нужны и путают.
        Index(
            "uq_tender_versions_draft",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )


class TenderVersionDocument(Base):
    """Строка состава: какая ревизия документа входит в версию тендера."""

    __tablename__ = "tender_version_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE нужен только удалению черновика целиком; замороженную версию не удалит триггер.
    tender_version_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("tender_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    document_revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Раздел комплекта (АР, КР…) задаёт человек: штамп читается не везде.
    section: Mapped[str | None] = mapped_column(String(16))
    use_in_model: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint(
            "tender_version_id", "document_id", name="uq_tender_version_documents_version_document"
        ),
        Index("ix_tender_version_documents_document_revision_id", "document_revision_id"),
    )


# Защита в базе: сервис ловит ошибку пользователя, триггер — ошибку программиста и прямую запись
# мимо API. Вешается и здесь, и в миграции 0019: тестовая база строится из метаданных, минуя
# Alembic. `truncate` строковые триггеры не вызывает — очистка таблиц между тестами работает.
_VERSION_GUARD_FUNCTION = """
create or replace function tender_versions_guard() returns trigger
language plpgsql as $$
begin
    if old.status = 'frozen' then
        raise exception 'tender_versions: frozen version is immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end
$$
"""

_VERSION_GUARD_TRIGGER = """
create trigger trg_tender_versions_guard
before update or delete on tender_versions
for each row execute function tender_versions_guard()
"""

# Родителя может уже не быть: каскадное удаление черновика приходит после удаления самой строки.
# Замороженная версия до этого не доходит — её удаление останавливает триггер выше.
_DOCUMENTS_GUARD_FUNCTION = """
create or replace function tender_version_documents_guard() returns trigger
language plpgsql as $$
begin
    if tg_op <> 'INSERT' and exists (
        select 1 from tender_versions
         where id = old.tender_version_id and status = 'frozen'
    ) then
        raise exception 'tender_version_documents: composition of a frozen version is immutable';
    end if;
    if tg_op <> 'DELETE' and exists (
        select 1 from tender_versions
         where id = new.tender_version_id and status = 'frozen'
    ) then
        raise exception 'tender_version_documents: composition of a frozen version is immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end
$$
"""

_DOCUMENTS_GUARD_TRIGGER = """
create trigger trg_tender_version_documents_guard
before insert or update or delete on tender_version_documents
for each row execute function tender_version_documents_guard()
"""


def _install(*statements: str) -> Callable[..., None]:
    """Обработчик `after_create`: функция и триггер выполняются отдельными вызовами (asyncpg)."""

    def listener(target: Table, connection: Connection, **kwargs: object) -> None:
        if connection.dialect.name != "postgresql":
            return
        for statement in statements:
            connection.exec_driver_sql(statement)

    return listener


event.listen(
    TenderVersion.__table__,
    "after_create",
    _install(_VERSION_GUARD_FUNCTION, _VERSION_GUARD_TRIGGER),
)
event.listen(
    TenderVersionDocument.__table__,
    "after_create",
    _install(_DOCUMENTS_GUARD_FUNCTION, _DOCUMENTS_GUARD_TRIGGER),
)
