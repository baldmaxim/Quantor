"""Кандидат утверждения — то, что адаптер нашёл, до детерминированной проверки и записи."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDiscipline,
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcSourceClass,
    CalcTableKind,
)
from app.contracts.calc.facts import CalcRegionTableLocator, CalcRegionTextLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcFactValue
from app.services.calc.adapters.recognized import RecognizedRegion

LABEL_LIMIT = 200
EXCERPT_LIMIT = 500


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class CollectionDeclaration:
    """Что человек заявил о документе перед сбором."""

    source_class: CalcSourceClass
    building: str
    discipline: CalcDiscipline | None


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    region: RecognizedRegion
    locator: CalcRegionTableLocator | CalcRegionTextLocator
    label: str
    """Для человека: «„Экспликация квартир 9 этажа“: 7 строк „Квартира №“»."""
    excerpt: str

    def signature(self) -> tuple[str, str]:
        return str(self.region.id), self.locator.model_dump_json()


@dataclass(frozen=True, slots=True)
class CalcCandidate:
    extractor: str
    """Какой адаптер нашёл: у каждого своя серия источника."""
    source_class: CalcSourceClass
    fact_type: str
    subject: CalcFactSubject
    value: CalcFactValue
    """Как в документе: в единице документа."""
    method: CalcFactMethod
    confidence: CalcConfidence
    note: str
    """Техническое пояснение способа извлечения."""
    evidence: tuple[CandidateEvidence, ...]


@dataclass(frozen=True, slots=True)
class CandidateIssue:
    code: CalcInspectionIssueCode
    message: str
    fact_type: str | None = None
    count: int = 1


@dataclass(frozen=True, slots=True)
class TableSeen:
    kind: CalcTableKind
    extracted: bool


@dataclass(slots=True)
class Extraction:
    candidates: list[CalcCandidate] = field(default_factory=list)
    issues: list[CandidateIssue] = field(default_factory=list)

    def extend(self, other: Extraction) -> None:
        self.candidates.extend(other.candidates)
        self.issues.extend(other.issues)
