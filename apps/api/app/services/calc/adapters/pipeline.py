"""Конвейер сбора фактов из распознанного документа — без базы и без побочных эффектов.

разбор блоков → извлечение кандидатов → детерминированная проверка (тип, место, единица,
значение, свидетельство) → слияние одинаковых → сводка.

Слияние: один и тот же факт, найденный в документе несколько раз с согласными значениями, —
одно утверждение с несколькими свидетельствами. Разные значения одного факта в одном документе
— противоречие документа: ни одно не записывается молча, оба видны в сводке.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from app.contracts.calc.enums import (
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcSourceClass,
    CalcTableKind,
)
from app.contracts.calc.fact_types import (
    FactUnitError,
    FactValueError,
    canonicalize,
    check_subject,
    fact_key,
    fact_type_def,
    values_agree,
)
from app.contracts.calc.inspections import CalcInspectionIssueRead, CalcTableCountRead
from app.contracts.calc.values import CalcFactValue
from app.errors import InvariantError
from app.services.calc.adapters.apartment_summary import extract_apartment_summary
from app.services.calc.adapters.candidates import (
    CalcCandidate,
    CandidateEvidence,
    CandidateIssue,
    CollectionDeclaration,
    Extraction,
)
from app.services.calc.adapters.customer_vor import extract_customer_vor
from app.services.calc.adapters.explications import extract_explications
from app.services.calc.adapters.parsed import parse_document
from app.services.calc.adapters.recognized import (
    IMAGE_BLOCK,
    TEXT_BLOCK,
    RecognizedDocument,
    StampSummary,
    summarize_stamps,
)
from app.services.calc.adapters.system_semantics import extract_system_functions
from app.services.calc.adapters.table_kinds import (
    EXTRACTED_KINDS,
    TABLE_KINDS_VERSION,
    UNEXTRACTED_FACT_TYPES,
)
from app.services.calc.adapters.text_values import (
    extract_contents_sheet_titles,
    extract_sheet_titles,
    extract_text_values,
)
from app.services.calc.adapters.water_summary import extract_water_summary

EXTRACTOR_VERSION: Final = f"calc.recognized.v3+{TABLE_KINDS_VERSION}"

DOCUMENT_FACT_TYPES: Final = frozenset(
    {
        "floor.apartments_count",
        "floor.kitchens_count",
        "floor.bathrooms_count",
        "floor.nonresidential_wet_rooms_count",
        "building.apartments_total",
        "building.apartments_by_type",
        "floor.elevation",
        "building.elevation_zero_abs",
        "building.floors_above_ground",
        "building.floors_below_ground",
        "building.sections_count",
        "building.residents_count",
        "floor.height",
        "system.inlet_pressure",
        "system.supply_temperature",
        "system.present",
        "system.function",
    }
)
"""Что адаптеры версии v1 ищут в документе. Документ, прошедший сбор, проверен на эти факты."""

VOR_FACT_TYPES: Final = frozenset({"system.present"})
"""Что ищет адаптер ВОР Заказчика: в ВОР документ проверяется только на это."""

_ADAPTER_METHODS: Final = frozenset(
    {CalcFactMethod.TABLE_EXPLICIT, CalcFactMethod.TABLE_COUNTED, CalcFactMethod.DOCUMENT_EXPLICIT}
)
_EVIDENCE_LIMIT: Final = 20
_ISSUE_LIMIT: Final = 200


@dataclass(frozen=True, slots=True)
class AcceptedCandidate:
    candidate: CalcCandidate
    fact_key: str
    canonical: CalcFactValue
    evidence: tuple[CandidateEvidence, ...]


@dataclass(frozen=True, slots=True)
class CollectionResult:
    accepted: tuple[AcceptedCandidate, ...]
    issues: tuple[CalcInspectionIssueRead, ...]
    tables: tuple[CalcTableCountRead, ...]
    candidates_total: int
    rejected: int
    stamp: StampSummary
    inspected_fact_types: frozenset[str]
    regions_total: int
    text_regions: int
    image_regions: int
    tables_total: int


def validate_candidate(
    candidate: CalcCandidate, region_ids: frozenset[str]
) -> AcceptedCandidate | CandidateIssue:
    definition = fact_type_def(candidate.fact_type)
    if definition is None:
        raise InvariantError(f"адаптер выдал неизвестный тип факта {candidate.fact_type}")
    if candidate.method not in _ADAPTER_METHODS:
        raise InvariantError(f"адаптер выдал метод {candidate.method}")
    if not candidate.evidence or any(
        str(item.region.id) not in region_ids for item in candidate.evidence
    ):
        raise InvariantError("кандидат без свидетельства из этого документа")
    problem = check_subject(definition, candidate.subject)
    if problem is not None:
        return CandidateIssue(
            CalcInspectionIssueCode.UNSCOPED, f"Место не подходит: {problem}", candidate.fact_type
        )
    if candidate.source_class is CalcSourceClass.CUSTOMER_VOR and not (
        definition.customer_vor_admissible
    ):
        return CandidateIssue(
            CalcInspectionIssueCode.VOR_NOT_ADMISSIBLE,
            "Этот факт из ВОР Заказчика не хранится",
            candidate.fact_type,
        )
    try:
        canonical = canonicalize(definition, candidate.value)
    except FactUnitError as error:
        return CandidateIssue(
            CalcInspectionIssueCode.UNIT_MISMATCH, f"Единица: {error}", candidate.fact_type
        )
    except FactValueError as error:
        return CandidateIssue(
            CalcInspectionIssueCode.VALUE_INVALID, f"Значение: {error}", candidate.fact_type
        )
    return AcceptedCandidate(
        candidate=candidate,
        fact_key=fact_key(definition.key, candidate.subject),
        canonical=canonical,
        evidence=candidate.evidence,
    )


def _describe(value: CalcFactValue) -> str:
    raw = value.model_dump(mode="json")
    return str(raw.get("value", raw))


def _merge(
    accepted: list[AcceptedCandidate],
) -> tuple[list[AcceptedCandidate], list[CandidateIssue]]:
    groups: dict[tuple[str, CalcSourceClass, str], list[AcceptedCandidate]] = {}
    for item in accepted:
        key = (item.candidate.extractor, item.candidate.source_class, item.fact_key)
        groups.setdefault(key, []).append(item)
    merged: list[AcceptedCandidate] = []
    issues: list[CandidateIssue] = []
    for items in groups.values():
        first = items[0]
        definition = fact_type_def(first.candidate.fact_type)
        if definition is None:
            raise InvariantError("тип факта пропал между проверкой и слиянием")
        if not all(values_agree(definition, first.canonical, item.canonical) for item in items):
            values = sorted({_describe(item.canonical) for item in items})
            issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.SELF_CONTRADICTION,
                    f"Документ сообщает разные значения ({', '.join(values[:4])}): "
                    f"{first.fact_key}",
                    first.candidate.fact_type,
                    count=len(items),
                )
            )
            continue
        evidence: list[CandidateEvidence] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            for piece in item.evidence:
                if piece.signature() not in seen and len(evidence) < _EVIDENCE_LIMIT:
                    seen.add(piece.signature())
                    evidence.append(piece)
        merged.append(
            AcceptedCandidate(
                candidate=first.candidate,
                fact_key=first.fact_key,
                canonical=first.canonical,
                evidence=tuple(evidence),
            )
        )
    return merged, issues


def _aggregate(issues: list[CandidateIssue]) -> tuple[CalcInspectionIssueRead, ...]:
    counts: Counter[tuple[CalcInspectionIssueCode, str | None, str]] = Counter()
    for issue in issues:
        counts[(issue.code, issue.fact_type, issue.message)] += issue.count
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][0].value, item[0][2]))
    return tuple(
        CalcInspectionIssueRead(code=code, fact_type=fact_type, message=message, count=count)
        for (code, fact_type, message), count in ordered[:_ISSUE_LIMIT]
    )


def collect(document: RecognizedDocument, declaration: CollectionDeclaration) -> CollectionResult:
    parsed = parse_document(document)
    vor = declaration.source_class is CalcSourceClass.CUSTOMER_VOR
    composition = declaration.source_class is CalcSourceClass.PROJECT_COMPOSITION
    extraction = Extraction()
    if vor:
        extraction.extend(extract_customer_vor(parsed, declaration))
    elif not composition:
        extraction.extend(extract_explications(parsed, declaration))
        extraction.extend(extract_apartment_summary(parsed, declaration))
        extraction.extend(extract_sheet_titles(parsed, declaration))
        extraction.extend(extract_contents_sheet_titles(parsed, declaration))
        extraction.extend(extract_text_values(parsed, declaration))
        extraction.extend(extract_system_functions(parsed, declaration))
        extraction.extend(extract_water_summary(parsed, declaration))

    kinds: Counter[CalcTableKind] = Counter(
        table.classification.kind for region in parsed for table in region.tables
    )
    tables = tuple(
        CalcTableCountRead(kind=kind, count=count, extracted=not vor and kind in EXTRACTED_KINDS)
        for kind, count in sorted(kinds.items(), key=lambda item: item[0].value)
    )
    issues = list(extraction.issues)
    if not vor and not composition:
        for kind, fact_types in UNEXTRACTED_FACT_TYPES.items():
            if kinds[kind]:
                issues.extend(
                    CandidateIssue(
                        CalcInspectionIssueCode.TABLE_NOT_EXTRACTED,
                        f"Найдена таблица вида {kind.value}: извлечение ещё не реализовано",
                        fact_type,
                        count=kinds[kind],
                    )
                    for fact_type in fact_types
                )

    region_ids = frozenset(str(region.id) for region in document.regions)
    accepted: list[AcceptedCandidate] = []
    rejected = 0
    for candidate in extraction.candidates:
        checked = validate_candidate(candidate, region_ids)
        if isinstance(checked, CandidateIssue):
            issues.append(checked)
            rejected += 1
        else:
            accepted.append(checked)
    merged, contradictions = _merge(accepted)
    issues.extend(contradictions)
    rejected += sum(issue.count for issue in contradictions)

    return CollectionResult(
        accepted=tuple(merged),
        issues=_aggregate(issues),
        tables=tables,
        candidates_total=len(extraction.candidates),
        rejected=rejected,
        stamp=summarize_stamps([region.stamp for region in parsed if region.stamp is not None]),
        inspected_fact_types=(
            frozenset() if composition else VOR_FACT_TYPES if vor else DOCUMENT_FACT_TYPES
        ),
        regions_total=len(document.regions),
        text_regions=sum(1 for region in document.regions if region.block_type == TEXT_BLOCK),
        image_regions=sum(1 for region in document.regions if region.block_type == IMAGE_BLOCK),
        tables_total=sum(kinds.values()),
    )
