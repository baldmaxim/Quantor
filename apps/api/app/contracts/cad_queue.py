"""Контракт очереди CAD проекта: что ждёт и что считает исполнитель CAD."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain import JobStatus, JobType


class CadQueueItemRead(BaseModel):
    job_id: UUID
    job_type: JobType
    status: JobStatus
    revision_id: UUID | None
    document_id: UUID | None
    document_name: str | None
    # Страницы задания, индексы с 0; пусто - задание не привязано к странице (или «все»).
    pages: list[int]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    max_attempts: int
    # Только для `queued`: сколько заданий CAD (всех пространств) исполнятся раньше этого.
    ahead: int | None
    # Только для `failed`.
    error_code: str | None


class CadQueueRead(BaseModel):
    items: list[CadQueueItemRead]
    # Общие счётчики исполнителя CAD по всем пространствам; только числа.
    running_total: int
    queued_total: int
