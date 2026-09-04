"""Проект — верхнеуровневая рабочая единица портала."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import ProjectStatus
from app.models.mixins import TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.job import Job


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()

    # Граница организации/рабочего пространства. Аутентификации на Stage 1 нет, поэтому
    # здесь всегда идентификатор dev-пространства. Колонка заведена сразу, чтобы добавление
    # арендаторов позже не переписывало каждый запрос.
    workspace_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, name="status"),
        nullable=False,
        default=ProjectStatus.ACTIVE,
    )

    documents: Mapped[list[Document]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_projects_workspace_id_updated_at", "workspace_id", "updated_at"),
        Index("ix_projects_workspace_id_name", "workspace_id", "name"),
    )
