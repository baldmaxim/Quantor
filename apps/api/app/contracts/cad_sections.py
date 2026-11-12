"""Контракты задания «Разрезы» (`cad_sections`): файл генератора и ответы API.

Файл генератора - схема `cad_sections.v2` или `v3`. Генератор (`cad_mep/run_sections.py` движка)
распознаёт разрезы АР по тексту PDF и пишет кандидатов уровней; сервер их не пересчитывает: высота
в свету и толщина перекрытия - значения генератора, принимает или отклоняет человек. Координаты
разметки - нормализованные 0..1 от левого верхнего угла отображаемой страницы, поворот уже учтён
(ADR-0008).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SECTIONS_SCHEMA = "cad_sections.v3"
# Принимаются v2 и v3 (v3 = v2 + роли размеров окон и `windows[]` у уровня); прочие - вне контракта.
ACCEPTED_SECTIONS_SCHEMAS = frozenset({"cad_sections.v2", SECTIONS_SCHEMA})
MAX_DECIDE_LEVELS = 500
MAX_REQUEST_PAGES = 1000

UnitCoord = Annotated[float, Field(ge=0.0, le=1.0)]
# Прямоугольник [x0, y0, x1, y1] в долях отображаемой страницы.
Box = tuple[UnitCoord, UnitCoord, UnitCoord, UnitCoord]
LevelStatus = Literal["candidate", "accepted", "rejected"]
# `sill`, `window`, `above_window` - оконная цепочка (v3): подоконник, окно, надоконная часть.
DimRole = Literal["clear", "structure", "sill", "window", "above_window", "other"]
Decision = Literal["accept", "reject", "reset"]


class SectionDim(BaseModel):
    """Размер на разрезе: значение, роль (в свету / конструкция / прочее) и рамка."""

    model_config = ConfigDict(extra="ignore")

    value_mm: int
    role: DimRole
    bbox: Box


class SectionMarkup(BaseModel):
    """Разметка уровня на странице: отметки, полоса между ними и размеры."""

    model_config = ConfigDict(extra="ignore")

    upper_mark: Box
    lower_mark: Box
    band: Box
    dims: list[SectionDim]


class SectionWindow(BaseModel):
    """Окно на уровне разреза (v3): отметки от чистого пола уровня, кандидат.

    `dims` - индексы звеньев подоконника, окна и надоконной части в `markup.dims` уровня.
    Связи окна разреза с проёмом плана нет: высоты окон в проёмы плана не переносятся.
    """

    model_config = ConfigDict(extra="ignore")

    sill_mm: int
    height_mm: int
    head_mm: int
    source: Literal["observed"]
    dims: list[Annotated[int, Field(ge=0)]]
    bbox: Box
    cut: str | None = None


class SectionLevelFile(BaseModel):
    """Уровень из `sections.json`: кандидат, поля сверх контракта сервер не читает."""

    model_config = ConfigDict(extra="ignore")

    elevation_mm: int
    upper_elevation_mm: int
    floor: int | None = None
    clear_height_mm: int | None = None
    structure_mm: int | None = None
    cut: str | None = None
    source: Literal["observed"]
    evidence: str
    markup: SectionMarkup
    # Только `cad_sections.v3`; в v2 поля нет. Сервер окна не хранит и в расчёт не берёт.
    windows: list[SectionWindow] = Field(default_factory=list)


class SectionPageFile(BaseModel):
    """Разрез страницы: заголовок, корпус, секция, линии разреза и уровни."""

    model_config = ConfigDict(extra="ignore")

    page_index: Annotated[int, Field(ge=0)]
    title: str | None = None
    corps: str | None = None
    section: str | None = None
    cuts: list[str] = Field(default_factory=list)
    page_size_pt: tuple[float, float]
    rotation: int
    levels: list[SectionLevelFile]


class SectionIssue(BaseModel):
    """Замечание генератора; в базе не хранится, читается из артефакта."""

    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    page_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class SectionsSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pdf_sha256: str
    pages: list[int] = Field(default_factory=list)


class SectionsFile(BaseModel):
    """`sections.json` целиком; поле `schema` проверяет обработчик до разбора модели."""

    model_config = ConfigDict(extra="ignore")

    generator_version: str
    source: SectionsSource
    sections: list[SectionPageFile]
    issues: list[SectionIssue] = Field(default_factory=list)


# ------------------------------------------------------------------ запросы и ответы API


class SectionsJobCreate(BaseModel):
    """Постановка задания: ревизия с PDF и, если нужно, подмножество страниц (индексы с 0)."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    page_indexes: list[Annotated[int, Field(ge=0)]] | None = Field(
        default=None, min_length=1, max_length=MAX_REQUEST_PAGES
    )


class SectionsDecide(BaseModel):
    """Решение человека по уровням: принять, отклонить или вернуть в кандидаты."""

    model_config = ConfigDict(extra="forbid")

    level_ids: list[UUID] = Field(min_length=1, max_length=MAX_DECIDE_LEVELS)
    decision: Decision


class SectionsJobRead(BaseModel):
    job_id: UUID
    revision_id: UUID
    status: str
    attempt: int
    error_code: str | None
    error_message: str | None
    page_indexes: list[int] | None
    created_at: datetime
    finished_at: datetime | None


class SectionLevelRead(BaseModel):
    id: UUID
    job_id: UUID
    seq: int
    page_index: int
    cut: str | None
    corps: str | None
    section: str | None
    floor: int | None
    elevation_mm: int
    upper_elevation_mm: int
    clear_height_mm: int | None
    structure_mm: int | None
    evidence: str
    markup: SectionMarkup
    status: LevelStatus
    decided_by: UUID | None
    decided_at: datetime | None


class SectionPageRead(BaseModel):
    page_index: int
    title: str | None
    corps: str | None
    section: str | None
    cuts: list[str]
    page_size_pt: tuple[float, float]
    rotation: int


class SectionIssueRead(BaseModel):
    code: str
    message: str
    page_index: int | None
    bbox: tuple[float, float, float, float] | None


class SectionsRead(BaseModel):
    """Последнее задание ревизии, кандидаты уровней и данные артефакта выполненного задания."""

    revision_id: UUID
    job: SectionsJobRead | None
    # Задание, чей результат лежит в `levels`, `pages`, `issues` (последнее выполненное).
    result_job_id: UUID | None
    levels: list[SectionLevelRead]
    issues: list[SectionIssueRead]
    pages: list[SectionPageRead]


class SectionsDecided(BaseModel):
    levels: list[SectionLevelRead]
