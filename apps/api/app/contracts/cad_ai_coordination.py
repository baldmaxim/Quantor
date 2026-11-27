"""Роль Claude «координация» (`coordination`): сопоставление осей этажа с осями эталонного этажа.

Модель только называет пары идентификаторов осей (`V1`, `H3`) целевого вида и эталона. Смещение в
мм считает детерминированный код по координатам осей из `walls.json`
(`services/cad_axis_coordination`); модель мм, градусов и координат не выдаёт. Итог - кандидат: он
используется только в сборке «Здания» и не пишется в `plan_alignments` (подтверждение человеком).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_ai_review import AiSourceCopy, AiUsage

CoordinationConfidence = Literal["high", "medium", "low"]
CoordinationStatus = Literal["ok", "rejected"]
AxisOrient = Literal["vertical", "horizontal"]
MAX_COORDINATION_PAIRS = 80
MAX_AXIS_ID = 16
COORDINATION_AXES_SCHEMA = "quantor.cad_axes_coordination.v1"


class AiCoordinationPair(BaseModel):
    """Ответ модели: ось целевого вида и ось эталона, которые она считает одной и той же."""

    model_config = ConfigDict(extra="forbid")

    target_axis_id: str = Field(min_length=1, max_length=MAX_AXIS_ID)
    reference_axis_id: str = Field(min_length=1, max_length=MAX_AXIS_ID)
    confidence: CoordinationConfidence
    evidence: str = Field(min_length=1, max_length=400)


class AiCoordinationReport(BaseModel):
    """Отчёт роли `coordination` (схема ответа Claude CLI)."""

    model_config = ConfigDict(extra="forbid")

    pairs: list[AiCoordinationPair] = Field(max_length=MAX_COORDINATION_PAIRS)
    notes: str = Field(max_length=1000)


class AiCoordinationView(BaseModel):
    """Вид-участник координации: адрес листа и задания, из которых взяты оси."""

    revision_id: UUID
    page_index: int = Field(ge=0)
    view: int = Field(ge=0)
    walls_job_id: UUID
    cad_job_id: UUID
    # Отпечаток осей вида (`cad_axis_coordination.axes_fingerprint`): пары идентификаторов из
    # результата применимы, только пока оси вида дают тот же отпечаток.
    axes_sha256: str | None = None


class AiCoordinationUsedPair(BaseModel):
    """Пара, по которой посчитано смещение: числа посчитал код, не модель."""

    target_axis_id: str
    reference_axis_id: str
    target_label: str
    reference_label: str
    orient: AxisOrient
    confidence: CoordinationConfidence
    evidence: str
    # Координаты осей в мм кадра своего вида, сдвиг эталон - цель и его остаток от общего сдвига.
    target_mm: float
    reference_mm: float
    shift_mm: float
    residual_mm: float


class AiCoordinationDropped(BaseModel):
    """Пара ответа вне расчёта: чужой id, повтор, другое направление, выброс."""

    target_axis_id: str
    reference_axis_id: str
    reason: str


class AiCoordinationResult(BaseModel):
    """Итог роли `coordination` пары видов: в задании под ключом `ai_coordination`."""

    target: AiCoordinationView
    reference: AiCoordinationView
    model: str
    target_input_sha256: str
    reference_input_sha256: str
    target_walls_sha256: str
    reference_walls_sha256: str
    prompt_version_id: UUID | None = None
    prompt_version: int | None = None
    prompt_sha256: str
    bundle_sha256: str
    usage: AiUsage
    sources: dict[str, AiSourceCopy]
    pairs: list[AiCoordinationUsedPair]
    dropped: list[AiCoordinationDropped]
    # Смещение вида в систему эталона (мм): `p_эталона = p_вида + offset_mm`; поворот только 0.
    offset_mm: tuple[float, float] | None
    status: CoordinationStatus
    reason: str | None
    notes: str = ""
    # Модель не вызывалась: результат скопирован из успешного задания той же пары видов с теми же
    # отпечатками осей и той же версией промта (`usage` нулевой).
    reused_from: UUID | None = None


class AiCoordinationSkipped(BaseModel):
    """Итог задания без вызова модели: эталона нет или вид сам эталон. Смещения не даёт."""

    status: Literal["skipped"] = "skipped"
    reason: str
    target: AiCoordinationView


class AiCoordinationStart(BaseModel):
    """Ручной запуск координации вида: адрес целевого листа."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    page_index: int = Field(ge=0)
    view: int = Field(ge=0)


class AiCoordinationStarted(BaseModel):
    """Поставленное (или уже идущее) задание координации; эталон находит исполнитель задания."""

    job_id: UUID
    status: str
    target_walls_job_id: UUID
