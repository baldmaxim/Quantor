"""Сопоставление позиций ВОР Заказчика с объектами Quantor моделью Claude (CLI на kg_claude).

Модель получает позиции и описания объектов БЕЗ количеств и не возвращает чисел: только пары
«позиция - объекты», уверенность и обоснование. Связь создаёт человек (существующий PUT связей).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_ai_review import AiUsage
from app.contracts.cad_vor import CadVorItemRead
from app.contracts.vor_fill import VorObjectKind
from app.domain import JobStatus

AiVorConfidence = Literal["high", "medium", "low"]
# Предел позиций в пакете: столько же сопоставлений модель вправе вернуть.
MAX_VOR_ITEMS = 500
MAX_VOR_OBJECTS = 500


class AiVorMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vor_item_id: str = Field(min_length=1, max_length=64)
    group_keys: list[str] = Field(max_length=50)
    confidence: AiVorConfidence
    rationale: str = Field(max_length=600)


class AiVorUnmatched(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(max_length=300)


class AiVorMapReport(BaseModel):
    """Ответ модели по схеме `schema.json`."""

    model_config = ConfigDict(extra="forbid")

    matches: list[AiVorMatch] = Field(max_length=MAX_VOR_ITEMS)
    unmatched_objects: list[AiVorUnmatched] = Field(max_length=MAX_VOR_OBJECTS)
    limitations: list[str] = Field(max_length=12)


class AiVorMapObjectRef(BaseModel):
    """Объект Quantor в пакете: название и вид, без количеств."""

    group_key: str
    kind: VorObjectKind
    title: str


class AiVorMapResult(BaseModel):
    document_id: UUID
    model: str
    prompt_version_id: UUID | None = None
    prompt_version: int | None = None
    prompt_sha256: str
    bundle_sha256: str
    items_count: int
    objects_count: int
    usage: AiUsage
    # Отчёт после отбрасывания чужих идентификаторов и ключей.
    report: AiVorMapReport
    # Что отброшено при проверке отчёта (чужие позиции и ключи): агрегат, не часть отчёта модели.
    dropped: list[str]


class AiVorMapObjectRead(AiVorMapObjectRef):
    # Позиция уже связана с этим объектом в проекте.
    linked: bool


class AiVorMapSuggestionRead(BaseModel):
    item: CadVorItemRead
    objects: list[AiVorMapObjectRead]
    confidence: AiVorConfidence
    rationale: str


class AiVorMapUnmatchedRead(BaseModel):
    object: AiVorMapObjectRef
    reason: str


class AiVorMapRead(BaseModel):
    """Последнее задание сопоставления проекта и его предложения."""

    # Пилот включён для проекта и ВОР загружен: кнопка запуска доступна.
    available: bool
    job_id: UUID | None
    status: JobStatus | None
    error_message: str | None
    # Задание посчитано по другому документу ВОР, чем текущий: предложения не показываются.
    stale: bool
    model: str | None
    prompt_version: int | None
    suggestions: list[AiVorMapSuggestionRead]
    unmatched: list[AiVorMapUnmatchedRead]
    limitations: list[str]
