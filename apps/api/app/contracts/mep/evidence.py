"""`MepEvidenceGraph` v0.3 — что показано на листе стадии П или подтверждено человеком.

Граф не содержит ничего, что придумал генератор РД: в перечислениях происхождения и статуса
для этого просто нет значения, и никакое поле не может его выразить.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.mep.common import (
    CONTRACT_VERSION,
    Attribute,
    Confidence,
    ContractModel,
    DocumentRef,
    Identifier,
    Level,
    NormPoint,
    ProfileKey,
    ProfileRef,
    Sha256,
    SheetRef,
    Tool,
)
from app.contracts.mep.profile import EvidenceKind


class EvidenceInputMode(StrEnum):
    """Как получен граф целиком (Track B, Track A, проверенный гибрид)."""

    MODEL_EXTRACTED = "MODEL_EXTRACTED"
    HUMAN_GT = "HUMAN_GT"
    HYBRID_REVIEWED = "HYBRID_REVIEWED"


class EvidenceProvenance(StrEnum):
    """Кто утверждает, что элемент есть на листе. `rd_prior_inferred` здесь нет намеренно."""

    BASE_RECOGNITION_OBSERVED = "base_recognition_observed"
    MEP_MODEL_OBSERVED = "mep_model_observed"
    DETERMINISTIC_EXTRACTED = "deterministic_extracted"
    HUMAN_GROUND_TRUTH = "human_ground_truth"
    UNRESOLVED = "unresolved"


class EvidenceStatus(StrEnum):
    """Насколько прямо элемент виден.

    `extraction_inferred` — вывод в пределах листа (подпись отнесена к ближайшему символу),
    а не достройка РД.
    """

    OBSERVED = "observed"
    EXTRACTION_INFERRED = "extraction_inferred"
    HUMAN_CONFIRMED = "human_confirmed"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    IGNORE_FOR_TRAIN = "ignore_for_train"


class SourceType(StrEnum):
    """Канал, из которого взят элемент.

    `base_region_text` — только тело TEXT-блока распознавалки. Описания IMAGE-блоков написаны её
    моделью и источником observed-evidence не являются, поэтому канала для них нет.
    """

    PDF_TEXT_LAYER = "pdf_text_layer"
    PAGE_RASTER = "page_raster"
    BASE_REGION_TEXT = "base_region_text"
    HUMAN_ANNOTATION = "human_annotation"


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"


class UnresolvedReason(StrEnum):
    NOT_VISIBLE = "not_visible"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    MISSING_SOURCE = "missing_source"
    OUT_OF_PROFILE = "out_of_profile"


class SourceAvailability(ContractModel):
    """Какие каналы были доступны. Отсутствие текстового слоя — `unavailable`, не ошибка."""

    source_type: SourceType
    sheet_id: Identifier
    availability: Availability
    note: str | None = None


class SourceRef(ContractModel):
    """Ссылка на конкретный артефакт-источник, а не его копия."""

    source_type: SourceType
    # Region.id, ключ растра, id текстового спана или id разметки — по типу источника.
    ref_id: Identifier
    tool_id: Identifier | None = None
    sha256: Sha256 | None = None


class PointGeometry(ContractModel):
    kind: Literal["point"] = "point"
    point: NormPoint


class BoxGeometry(ContractModel):
    kind: Literal["bbox"] = "bbox"
    min: NormPoint
    max: NormPoint

    @model_validator(mode="after")
    def _ordered(self) -> BoxGeometry:
        if self.max[0] < self.min[0] or self.max[1] < self.min[1]:
            raise ValueError("правый нижний угол рамки левее или выше левого верхнего")
        return self


class PolylineGeometry(ContractModel):
    kind: Literal["polyline"] = "polyline"
    points: Annotated[tuple[NormPoint, ...], Field(min_length=2)]


class PolygonGeometry(ContractModel):
    kind: Literal["polygon"] = "polygon"
    outer: Annotated[tuple[NormPoint, ...], Field(min_length=3)]
    holes: tuple[Annotated[tuple[NormPoint, ...], Field(min_length=3)], ...] = ()


EvidenceGeometry = Annotated[
    PointGeometry | BoxGeometry | PolylineGeometry | PolygonGeometry,
    Field(discriminator="kind"),
]


class EvidenceAttribute(Attribute):
    """Атрибут evidence.

    `labelled` — прочитан с листа (подпись «Ø50»), `measured` — снят с геометрии листа и
    требует калибровки. `source_element_ids` — текстовые элементы, из которых он прочитан.
    """

    derivation: Literal["labelled", "measured"] = "labelled"
    status: EvidenceStatus
    source_element_ids: tuple[Identifier, ...] = ()


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    CORRECT_CLASS = "correct_class"
    CORRECT_GEOMETRY = "correct_geometry"
    CORRECT_ATTRIBUTES = "correct_attributes"
    CORRECT_SYSTEM = "correct_system"
    MARK_AMBIGUOUS = "mark_ambiguous"
    REJECT = "reject"
    ADD_MISSING = "add_missing"


# Какие поля элемента меняет исправление — для сверки с исходным предсказанием.
CORRECTED_FIELD: dict[ReviewAction, str] = {
    ReviewAction.CORRECT_CLASS: "class_key",
    ReviewAction.CORRECT_GEOMETRY: "geometry",
    ReviewAction.CORRECT_ATTRIBUTES: "attributes",
    ReviewAction.CORRECT_SYSTEM: "system_key",
}


class ReviewEvent(ContractModel):
    """Одно действие проверяющего. История только дописывается и упорядочена по времени."""

    event_id: Identifier
    action: ReviewAction
    reviewer_id: Identifier
    reviewed_at: AwareDatetime
    note: Annotated[str, Field(max_length=1024)] | None = None


class OriginalPrediction(ContractModel):
    """Исходный выход модели или детерминированного экстрактора до исправлений человека."""

    provenance: Literal["mep_model_observed", "deterministic_extracted"]
    tool_id: Identifier
    class_key: ProfileKey | None
    system_key: ProfileKey | None = None
    geometry: EvidenceGeometry
    attributes: tuple[EvidenceAttribute, ...] = ()
    confidence: Confidence | None = None
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1)]


class UnresolvedField(ContractModel):
    field: Annotated[str, Field(min_length=1, max_length=128)]
    reason: UnresolvedReason
    note: str | None = None


class EvidenceElement(ContractModel):
    id: Identifier
    kind: EvidenceKind
    sheet_id: Identifier
    level_id: Identifier | None = None
    geometry: EvidenceGeometry
    # `None` — класс не определён; причина — в `unresolved`.
    class_key: ProfileKey | None
    system_key: ProfileKey | None = None
    text: str | None = None
    attributes: tuple[EvidenceAttribute, ...] = ()
    confidence: Confidence | None = None
    provenance: EvidenceProvenance
    status: EvidenceStatus
    review: ReviewStatus = ReviewStatus.UNREVIEWED
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    unresolved: tuple[UnresolvedField, ...] = ()
    # HYBRID_REVIEWED: что предсказала модель и что с этим сделал человек.
    original: OriginalPrediction | None = None
    review_history: tuple[ReviewEvent, ...] = ()


class EvidenceRelation(ContractModel):
    id: Identifier
    relation_key: ProfileKey
    from_id: Identifier
    to_id: Identifier
    confidence: Confidence | None = None
    provenance: EvidenceProvenance
    status: EvidenceStatus
    review: ReviewStatus = ReviewStatus.UNREVIEWED
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    review_history: tuple[ReviewEvent, ...] = ()


class EvidenceGap(ContractModel):
    """Известный пробел входа: чего не хватает, чтобы граф считался полным."""

    code: Annotated[str, Field(min_length=1, max_length=64)]
    sheet_id: Identifier | None = None
    subject_ids: tuple[Identifier, ...] = ()
    note: str | None = None


class MepEvidenceGraph(ContractModel):
    schema_version: Literal["0.3.0"] = CONTRACT_VERSION
    graph_id: Identifier
    input_mode: EvidenceInputMode
    profile: ProfileRef
    document: DocumentRef
    sheets: Annotated[tuple[SheetRef, ...], Field(min_length=1)]
    levels: tuple[Level, ...] = ()
    tools: tuple[Tool, ...] = ()
    source_availability: tuple[SourceAvailability, ...] = ()
    elements: tuple[EvidenceElement, ...]
    relations: tuple[EvidenceRelation, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
