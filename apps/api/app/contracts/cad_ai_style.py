"""Роль Claude «оформление» (`style`): классы подписей штриховки плана этажа.

Модель только классифицирует подписи по идентификатору из `hatch_signatures.json` движка. Числа
подписи (цвет, перо, угол, шаг) берёт сервер из пакета по идентификатору, не от модели; площадей и
количеств модель не выдаёт. Класс уходит движку подсказкой преобразования (`hatch_classes`).
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_ai_review import AiSourceCopy, AiUsage

StyleClassName = Literal["monolith", "masonry", "ignore"]
StyleConfidence = Literal["high", "medium", "low"]
MAX_STYLE_CLASSES = 20
STYLE_SIGNATURES_SCHEMA = "quantor.cad_hatch_signatures.v1"
MAX_SIGNATURE_ID = 100
_UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class AiStyleClass(BaseModel):
    """Ответ модели по одной подписи: идентификатор, класс, уверенность, обоснование."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    signature_id: str = Field(min_length=1, max_length=MAX_SIGNATURE_ID)
    class_: StyleClassName = Field(alias="class")
    confidence: StyleConfidence
    evidence: str = Field(min_length=1, max_length=400)


class AiStyleReport(BaseModel):
    """Отчёт роли `style` (схема ответа Claude CLI)."""

    model_config = ConfigDict(extra="forbid")

    classes: list[AiStyleClass] = Field(max_length=MAX_STYLE_CLASSES)
    limitations: list[str] = Field(max_length=12)


class AiStyleResolved(BaseModel):
    """Класс подписи с числами из пакета: то, что уйдёт движку в `hatch_classes`."""

    signature_id: str
    class_name: StyleClassName
    confidence: StyleConfidence
    evidence: str
    color: tuple[_UnitFloat, _UnitFloat, _UnitFloat]
    pen_pt: float = Field(gt=0, allow_inf_nan=False)
    angle_deg: float = Field(ge=0, lt=180, allow_inf_nan=False)
    pitch_pt: float = Field(gt=0, allow_inf_nan=False)


class AiStyleResult(BaseModel):
    """Итог роли `style` одного вида: хранится в задании под ключом `ai_style`."""

    cad_job_id: UUID
    cad_attempt: int
    revision_id: UUID
    page_index: int
    view: int
    model: str
    input_sha256: str
    signatures_sha256: str
    prompt_version_id: UUID | None = None
    prompt_version: int | None = None
    prompt_sha256: str
    bundle_sha256: str
    usage: AiUsage
    # Копии источников на kg_claude с sha256: происхождение документов, по которым шёл ответ.
    sources: dict[str, AiSourceCopy]
    classes: list[AiStyleResolved]
    # Что отброшено при проверке ответа: чужие id, заливки, повторы.
    dropped: list[str]
    limitations: list[str]
