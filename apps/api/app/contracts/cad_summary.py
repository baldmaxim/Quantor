"""Контракт сводки распознавания CAD по проекту: сколько листов в каком состоянии."""

from __future__ import annotations

from pydantic import BaseModel


class CadProjectSummaryRead(BaseModel):
    """Листы последних открываемых ревизий проекта по состоянию конвейера CAD.

    Инвариант: `sheets_total` = `sheets_done` + `sheets_running` + `sheets_failed` + `sheets_idle`.
    """

    sheets_total: int
    # Хоть один этап выполнен, активных этапов и ошибок нет.
    sheets_done: int
    # Хоть один этап в очереди или выполняется.
    sheets_running: int
    # Активных этапов нет, у какого-либо этапа последнее задание закончилось отказом.
    sheets_failed: int
    # Ничего не запускалось.
    sheets_idle: int
    # Сколько ревизий учтено (последняя открываемая у каждого PDF-документа проекта).
    documents_total: int
