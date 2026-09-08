"""Асинхронное задание: единственный источник правды о ходе долгой операции."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import JobScope, JobStatus, JobType
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
    project_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    # Граница арендатора принадлежит самому заданию, а не выводится джойном через проект.
    # Выведенная означала, что задание без проекта не принадлежит никому — то есть доступно
    # всем: ровно эта дыра и закрывается здесь.
    #
    # NULL — не «неизвестно», а «общесистемное»: обслуживание установки, невидимое ни одному
    # пространству. Отсюда и отсутствие NOT NULL: инвариант держит CHECK ниже, а не nullability.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

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

    # --- исполнение отдельным процессом ---
    #
    # Все отметки времени ниже ставит база (`now()`), а не приложение. Это не придирка:
    # `created_at` задания ставит процесс API (осознанно, см. ограничения этапа), и если
    # аренду мерить теми же часами, то два процесса с разошедшимися часами начнут отбирать
    # задания друг у друга.

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Снимок на момент постановки: изменение умолчания не должно задним числом
    # оживлять давно отказавшие задания.
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    worker_id: Mapped[str | None] = mapped_column(String(64))
    # Срок владения. Истёк — задание считается брошенным и возвращается в очередь.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Не раньше этого времени задание можно брать. На этом стоит отсрочка повтора.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Идентификаторы входных и выходных артефактов задания: без них происхождение
    # результата не восстановить.
    payload: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    project: Mapped[Project | None] = relationship(back_populates="jobs")

    @property
    def scope(self) -> JobScope:
        """Область видимости задания. Выводится, а не хранится."""
        if self.workspace_id is None:
            return JobScope.SYSTEM
        return JobScope.PROJECT if self.project_id is not None else JobScope.WORKSPACE

    __table_args__ = (
        CheckConstraint(
            "progress is null or (progress >= 0 and progress <= 1)", name="progress_range"
        ),
        CheckConstraint("attempt >= 0 and attempt <= max_attempts + 1", name="attempt_range"),
        # Три допустимых состояния пары и одно недопустимое:
        #
        #   workspace_id | project_id | смысл
        #   NOT NULL     | NULL       | задание пространства
        #   NOT NULL     | NOT NULL   | задание проекта
        #   NULL         | NULL       | общесистемное
        #   NULL         | NOT NULL   | непредставимо — его и запрещает этот CHECK
        CheckConstraint("project_id is null or workspace_id is not null", name="workspace_scope"),
        # Композитный ключ вместо одноколоночного: он и есть гарантия того, что арендатор
        # задания совпадает с арендатором его проекта. Проверка в сервисе даёт понятную ошибку,
        # но не удержит запись мимо API — миграцию или ручной SQL.
        #
        # Режим MATCH SIMPLE (умолчание PostgreSQL) не проверяет ключ, когда project_id пуст,
        # — ровно то, что нужно заданиям пространства и общесистемным. Промежуток между этим
        # ключом и CHECK выше закрыт: как только project_id задан, workspace_id обязан быть.
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="CASCADE",
            # Страховка на будущее: если проект начнёт переезжать между пространствами,
            # его задания переедут вместе с ним, а не станут молча чужими.
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        Index("ix_jobs_project_id_created_at", "project_id", "created_at"),
        # Покрывает и список заданий пространства, и `where workspace_id is null` для
        # общесистемных: btree индексирует NULL, отдельный частичный индекс не нужен.
        Index("ix_jobs_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
        # Частичные индексы под два горячих запроса воркера: «что взять» и «что брошено».
        # Без условия они покрывали бы и завершённые задания, которых со временем
        # становится большинство.
        Index(
            "ix_jobs_claim",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_jobs_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
    )
