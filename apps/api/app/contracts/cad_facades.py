"""Контракты задания «Фасады» (`cad_facades`): файл генератора и ответы API (ADR-0048).

Файл генератора - схема `cad_facades.v1`. Генератор (`cad_facades/run_facades.py` движка) читает
только векторы и текст PDF: виды фасадов, оси из заголовка, отметки, этажи и окна векторного вида.
Сервер ничего не досчитывает: привязка по отметкам, окна и их высоты - значения генератора
(кандидаты), принимает или отклоняет человек. Растр не анализируется, OCR нет, размерные линии не
читаются. Координаты `bbox` и положения - доли отображаемой страницы 0..1 от левого верхнего угла,
поворот уже учтён (ADR-0008); высоты - мм от ±0,000 по привязке вида.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FACADES_SCHEMA = "cad_facades.v1"
MAX_DECIDE_VIEWS = 500
MAX_REQUEST_PAGES = 1000

# Прямоугольник [x0, y0, x1, y1] в долях отображаемой страницы.
Box = tuple[float, float, float, float]
ViewStatus = Literal["candidate", "accepted", "rejected"]
ViewBody = Literal["vector", "raster"]
ScaleStatus = Literal["fitted", "weak", "text_only", "none"]
Decision = Literal["accept", "reject", "reset"]


class FacadeScale(BaseModel):
    """Вертикальная привязка вида `z = z0 - (y - y0) * k` по остриям отметок."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    status: ScaleStatus
    mm_per_pt: float | None = None
    residual_mm: float | None = None
    marks_used: int = 0


class FacadeAxis(BaseModel):
    """Марка оси под видом; `u_mm` - мм вдоль фасада от марки `axis_from`, `None` без привязки."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    label: str
    label_full: str | None = None
    x: float
    y: float
    u_mm: int | None = None


class FacadeMark(BaseModel):
    """Отметка по тексту; `tip` - острие знака (доли страницы), `None` - знака в векторах нет."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    value_mm: int
    text: str
    bbox: Box
    tip: tuple[float, float] | None = None
    used: bool = False
    fit_dev_mm: int | None = None


class FacadeFloor(BaseModel):
    """Подпись этажа («2 этаж», «тех. пространство»); `mark_mm` - отметка на той же высоте."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    label: str
    floor: int | None = None
    mark_mm: int | None = None
    label_z_mm: int | None = None
    bbox: Box


class FacadeWindow(BaseModel):
    """Окно векторного вида: горизонталь - мм от оси `axis_from`, высоты - мм от ±0,000."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    bbox: Box
    u0_mm: int | None = None
    u1_mm: int | None = None
    width_mm: int
    z_bottom_mm: int
    z_top_mm: int
    height_mm: int
    cells: int = 0
    hatch: int = 0
    sash: int = 0
    source: Literal["observed"]


class FacadeViewFile(BaseModel):
    """Вид из `facades.json`: кандидат, поля сверх контракта сервер не читает."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    id: str
    page_index: Annotated[int, Field(ge=0)]
    bbox: Box
    title: str
    axis_from: str | None = None
    axis_to: str | None = None
    corps: str | None = None
    section: str | None = None
    body: ViewBody
    image_cover: float | None = None
    scale: FacadeScale
    axes: list[FacadeAxis] = Field(default_factory=list)
    marks: list[FacadeMark] = Field(default_factory=list)
    floors: list[FacadeFloor] = Field(default_factory=list)
    windows: list[FacadeWindow] = Field(default_factory=list)


class FacadeIssue(BaseModel):
    """Замечание генератора; в базе не хранится, читается из артефакта."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    code: str
    message: str
    page_index: int | None = None
    bbox: Box | None = None


class FacadesSource(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    pdf_sha256: str
    pages: list[int] = Field(default_factory=list)


class FacadesFile(BaseModel):
    """`facades.json` целиком; поле `schema` проверяет обработчик до разбора модели.

    NaN и бесконечности запрещены: в JSONB и в ответ API они не попадают.
    """

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    generator_version: str
    source: FacadesSource
    views: list[FacadeViewFile]
    issues: list[FacadeIssue] = Field(default_factory=list)


# ------------------------------------------------------------------ запросы и ответы API


class FacadesJobCreate(BaseModel):
    """Постановка задания: ревизия с PDF и, если нужно, подмножество страниц (индексы с 0)."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    page_indexes: list[Annotated[int, Field(ge=0)]] | None = Field(
        default=None, min_length=1, max_length=MAX_REQUEST_PAGES
    )


class FacadesDecide(BaseModel):
    """Решение человека по видам: принять, отклонить или вернуть в кандидаты."""

    model_config = ConfigDict(extra="forbid")

    view_ids: list[UUID] = Field(min_length=1, max_length=MAX_DECIDE_VIEWS)
    decision: Decision


class FacadesJobRead(BaseModel):
    job_id: UUID
    revision_id: UUID
    status: str
    attempt: int
    error_code: str | None
    error_message: str | None
    page_indexes: list[int] | None
    created_at: datetime
    finished_at: datetime | None


class FacadeViewRead(BaseModel):
    id: UUID
    job_id: UUID
    seq: int
    page_index: int
    view_key: str
    title: str
    axis_from: str | None
    axis_to: str | None
    corps: str | None
    section: str | None
    body: ViewBody
    scale_status: ScaleStatus
    mm_per_pt: float | None
    residual_mm: float | None
    bbox: Box
    axes: list[FacadeAxis]
    marks: list[FacadeMark]
    floors: list[FacadeFloor]
    windows: list[FacadeWindow]
    window_count: int
    status: ViewStatus
    decided_by: UUID | None
    decided_at: datetime | None


class FacadeIssueRead(BaseModel):
    code: str
    message: str
    page_index: int | None
    bbox: Box | None


class FacadesRead(BaseModel):
    """Последнее задание ревизии, кандидаты видов и замечания артефакта выполненного задания."""

    revision_id: UUID
    job: FacadesJobRead | None
    # Задание, чей результат лежит в `views` и `issues` (последнее выполненное).
    result_job_id: UUID | None
    views: list[FacadeViewRead]
    issues: list[FacadeIssueRead]


class FacadesDecided(BaseModel):
    views: list[FacadeViewRead]
