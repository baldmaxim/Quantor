"""Чертёж наложением на модель: листы планов на отметке этажа и их привязка к сетке осей версии."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ModelSheetOverlayRead(BaseModel):
    """Вид листа плана на отметке этажа модели и его привязка к сетке осей модели.

    `matrix` - подобие pt страницы (от левого верхнего угла, как кадр вида) → мм системы здания
    модели: `x = a·x_pt + b·y_pt + c`, `y = d·x_pt + e·y_pt + f`, `[a, b, c, d, e, f]`.
    Нет привязки -
    `None` и причина в `reason`.
    """

    revision_id: uuid.UUID
    document_id: uuid.UUID | None
    job_id: uuid.UUID
    page_index: int
    view: int
    label: str
    group_label: str
    # Отметка листа по паспорту, мм; нет в паспорте - `None`.
    base_z_mm: int | None = None
    status: Literal["registered", "unregistered"]
    reason: str | None = None
    matrix: list[float] | None = Field(default=None, min_length=6, max_length=6)
    rotation_deg: float | None = None
    scale_mm_per_pt: float | None = None
    # Масштаб листа по размерной проверке (кадр вида); не подтверждён - `None`.
    frame_scale_mm_per_pt: float | None = None
    rms_mm: float | None = None
    max_mm: float | None = None
    axes_used: list[str] = []


class ModelSheetOverlayList(BaseModel):
    storey_key: str
    elevation_mm: float
    items: list[ModelSheetOverlayRead]
    # Почему листов нет (нет сетки осей в модели, нет листов на отметке); есть - `None`.
    message: str | None = None
