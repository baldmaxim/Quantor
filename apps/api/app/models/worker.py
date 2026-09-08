"""Исполнитель заданий.

Таблица нужна ради одного различия, которое иначе неразличимо: пустая очередь и
отсутствующий воркер выглядят в `jobs` одинаково. «Заданий нет» и «брать их некому» —
разные состояния установки, и диагностика обязана их развести.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Worker(Base):
    """Живой процесс-исполнитель и его текущая работа."""

    __tablename__ = "workers"

    # Ключ — строка вида «хост:pid:короткий-uuid», а не UUID: она читаема в логах
    # и в админке, и по ней сразу видно, где именно крутится исполнитель.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    host: Mapped[str] = mapped_column(String(255), nullable=False)
    pid: Mapped[int] = mapped_column(nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Какие типы заданий берёт. Позволит позже развести тяжёлое распознавание
    # и лёгкие операции по разным процессам, не меняя схему.
    job_types: Mapped[list[Any]] = mapped_column(pg.JSONB, nullable=False, server_default="[]")

    current_job_id: Mapped[UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_workers_heartbeat_at", "heartbeat_at"),)
