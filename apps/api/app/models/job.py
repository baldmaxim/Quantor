"""Асинхронное задание: единственный источник правды о ходе долгой операции."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import JobStatus, JobType
from app.models.mixins import TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.project import Project


class Job(TimestampMixin, Base):
    """Состояние задания живёт в базе, а не в памяти процесса (ADR-0005).

    Исполнитель на Stage 1 внутренний, но контракт состояния уже такой, чтобы вынести
    исполнение в отдельный воркер без изменения API и интерфейса.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )

    job_type: Mapped[JobType] = mapped_column(str_enum(JobType, name="job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, name="status"),
        nullable=False,
        default=JobStatus.QUEUED,
    )

    progress: Mapped[float | None] = mapped_column(Float)
    stage: Mapped[str | None] = mapped_column(String(64))

    # Повтор с тем же ключом не создаёт второе задание — на этом строится идемпотентность
    # загрузки и импорта.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Идентификаторы входных и выходных артефактов задания: без них происхождение
    # результата не восстановить.
    payload: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    project: Mapped[Project | None] = relationship(back_populates="jobs")

    __table_args__ = (
        CheckConstraint(
            "progress is null or (progress >= 0 and progress <= 1)", name="progress_range"
        ),
        Index("ix_jobs_project_id_created_at", "project_id", "created_at"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )
