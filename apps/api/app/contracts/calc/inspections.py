"""Сбор фактов из распознанного пакета (ADR-0030, PROMPT 02).

Сбор — проход адаптеров по одной ревизии документа: таблицы и текст блоков распознанного
пакета превращаются в кандидаты утверждений, детерминированно проверяются и записываются в
реестр фактов. Запись о сборе хранит, что было проверено и что не удалось: без неё система не
отличила бы «документ проверен, значения нет» от «документ ещё не смотрели».
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcDocumentStage,
    CalcInspectionIssueCode,
    CalcSourceClass,
    CalcStageBasis,
    CalcTableKind,
)
from app.contracts.calc.subjects import SubjectCode


class CalcInspectionCreate(BaseModel):
    """Заявление документа перед сбором: что это за документ, какой стадии, какого корпуса.

    Имя файла доказательством не считается. Штамп подсказывает стадию и раздел, но решает
    человек: заявленное расходится со штампом — это видно в сводке сбора.
    """

    model_config = ConfigDict(extra="forbid")

    document_revision_id: uuid.UUID
    source_class: CalcSourceClass
    """Что это за документ: АР, пояснительная записка, ВК стадии П, ВОР Заказчика."""
    document_stage: CalcDocumentStage
    building: SubjectCode
    """Корпус, к которому относится документ. Без корпуса этажи разных домов слились бы."""
    discipline: CalcDiscipline | None = None
    """Раздел инженерного документа: без него «В1» водопровода не отличить от вытяжки."""

    @model_validator(mode="after")
    def _not_manual(self) -> CalcInspectionCreate:
        if self.source_class is CalcSourceClass.MANUAL:
            raise ValueError("ручной ввод — не документ: его не собирают, а вводят")
        return self


class CalcTableCountRead(BaseModel):
    kind: CalcTableKind
    count: int
    extracted: bool
    """Извлекаются ли из таблиц этого вида факты. Нет — таблица найдена, но не разобрана."""


class CalcFactTypeCountRead(BaseModel):
    fact_type: str
    accepted: int


class CalcInspectionIssueRead(BaseModel):
    code: CalcInspectionIssueCode
    fact_type: str | None
    message: str
    count: int


class CalcInspectionSummary(BaseModel):
    """Итог сбора: хранится вместе с записью о сборе и показывается пользователю."""

    regions_total: int
    text_regions: int
    image_regions: int
    """Блоки-изображения не используются: их описание написала модель распознавалки."""
    tables_total: int
    tables: list[CalcTableCountRead]
    candidates: int
    accepted: int
    rejected: int
    created: int
    unchanged: int
    superseded: int
    withdrawn: int
    by_fact_type: list[CalcFactTypeCountRead]
    issues: list[CalcInspectionIssueRead]
    stamp_stage: CalcDocumentStage | None
    """Стадия по штампам документа, если они единодушны."""
    stamp_section: str | None
    """Марка раздела по шифру в штампе: «АР», «ВК»."""
    stage_basis: CalcStageBasis
    limitations: list[str]


class CalcInspectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    document_revision_id: uuid.UUID
    source_class: CalcSourceClass
    document_stage: CalcDocumentStage
    building: str
    discipline: CalcDiscipline | None
    extractor_version: str
    inspected_fact_types: list[str]
    summary: CalcInspectionSummary
    created_by: uuid.UUID | None
    created_at: datetime


class CalcCollectableDocumentRead(BaseModel):
    """Ревизия документа проекта глазами сбора фактов."""

    document_id: uuid.UUID
    document_revision_id: uuid.UUID
    title: str
    recognized: bool
    """Есть ли у ревизии распознанный текст. Без него автоматический сбор невозможен."""
    latest: bool
    """Последняя ревизия документа: собирать факты можно только из неё."""
    regions_count: Annotated[int, Field(ge=0)]
    stamp_stage: CalcDocumentStage | None
    stamp_section: str | None
    suggested_class: CalcSourceClass | None
    suggested_discipline: CalcDiscipline | None
    last_inspection: CalcInspectionRead | None
    inspection_current: bool
    """Последний сбор сделан текущей версией адаптеров."""
