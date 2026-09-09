"""Проект — верхнеуровневая рабочая единица портала."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import ProjectSource, ProjectStatus
from app.models.mixins import TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.identity import Workspace
    from app.models.job import Job
    from app.models.takeoff import TakeoffItem


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()

    # Граница арендатора. На Stage 1 это был свободный UUID: рабочих пространств как
    # сущности не существовало. Внешний ключ появился вместе с ними (ADR-0012) и не даёт
    # завести проект в пространстве, которого нет.
    #
    # RESTRICT, а не CASCADE: удаление арендатора не должно молча уносить его проекты
    # вместе с документами и распознанными областями.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, name="status"),
        nullable=False,
        default=ProjectStatus.ACTIVE,
    )

    # Происхождение проекта. Для заведённых руками — manual и пустые внешние поля.
    source: Mapped[ProjectSource] = mapped_column(
        str_enum(ProjectSource, name="source"),
        nullable=False,
        default=ProjectSource.MANUAL,
        server_default=ProjectSource.MANUAL.value,
    )
    # Идентификатор в системе-источнике и человекочитаемая ссылка на него (номер тендера).
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Местное имя проекта. Отдельно от `name` потому, что у проекта из внешней системы
    # `name` — это её название, а не наше: переименование в портале не должно молча
    # затирать каноническое (ADR-0011, промт 06). Пусто — показывается каноническое.
    local_alias: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Когда связь с тендером была установлена в последний раз. Нужно разбору перепривязок:
    # без отметки времени история связи восстанавливается только по журналу.
    external_bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="projects")

    documents: Mapped[list[Document]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    # Строки обмера живут на уровне проекта: одна строка «Двери» на весь проект,
    # а измерения по ней — на разных листах (ADR-0019).
    takeoff_items: Mapped[list[TakeoffItem]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TakeoffItem.ordinal",
    )

    __table_args__ = (
        Index("ix_projects_workspace_id_updated_at", "workspace_id", "updated_at"),
        Index("ix_projects_workspace_id_name", "workspace_id", "name"),
        # Цель составного внешнего ключа из `jobs`. По данным избыточно — `id` и так первичный
        # ключ, — но PostgreSQL требует объявленной уникальности ровно на том наборе колонок,
        # на который ссылается ключ.
        UniqueConstraint("id", "workspace_id", name="uq_projects_id_workspace"),
        # Один тендер — один проект в рабочем пространстве. Без этого повторное нажатие
        # «Создать» на той же строке списка плодит дубликаты, и какой из них настоящий,
        # потом не разобрать.
        UniqueConstraint(
            "workspace_id", "source", "external_id", name="uq_projects_workspace_source_external"
        ),
    )
