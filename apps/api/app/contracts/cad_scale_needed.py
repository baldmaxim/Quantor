"""Контракт списка листов CAD проекта, которым нужен масштаб (ручная калибровка)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

# auto_scale_unconfirmed - автомасштаб не подтверждён размерными цепочками;
# scale_missing - преобразование прошло, но у вида нет принятого масштаба для зон и трасс;
# rerun_needed - лист откалиброван уже после последнего преобразования: осталось перезапустить.
CadScaleNeededReason = Literal["auto_scale_unconfirmed", "scale_missing", "rerun_needed"]


class CadScaleNeededItem(BaseModel):
    document_id: UUID
    document_title: str
    revision_id: UUID
    # Номер страницы с нуля.
    page_index: int
    page_label: str | None
    # Позиция листа в рабочей области (с 1, по порядку страниц ревизии); нет листа - `null`.
    sheet_position: int | None
    reason: CadScaleNeededReason
    convert_job_id: UUID
    # Вид листа для `scale_missing` и `rerun_needed` после него; у отказа преобразования - `null`.
    view: str | None


class CadScaleNeededRead(BaseModel):
    total: int
    items: list[CadScaleNeededItem]
