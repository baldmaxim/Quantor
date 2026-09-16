"""Смысловые проверки профиля и `MepEvidenceGraph`.

Структура (типы, диапазоны координат, обязательные поля) проверяется при разборе модели. Здесь —
то, что видно только на графе целиком: ссылки, согласованность происхождения, профиль.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.contracts.mep.common import (
    ContractIssue,
    ProfileRef,
    ScalarValue,
    ScaleStatus,
    issue,
)
from app.contracts.mep.evidence import (
    Availability,
    EvidenceAttribute,
    EvidenceElement,
    EvidenceInputMode,
    EvidenceProvenance,
    EvidenceRelation,
    EvidenceStatus,
    MepEvidenceGraph,
    ReviewStatus,
    SourceRef,
    SourceType,
)
from app.contracts.mep.profile import AttributeDef, MepSystemProfile, ValueType
from app.contracts.mep.provenance_checks import (
    check_profile_pin,
    check_review,
    check_sheets,
    check_tools,
)


def duplicates(ids: Iterable[str]) -> list[ContractIssue]:
    return [
        issue("DUPLICATE_ID", key, f"идентификатор встречается {count} раза")
        for key, count in Counter(ids).items()
        if count > 1
    ]


def profile_mismatch(ref: ProfileRef, profile: MepSystemProfile) -> list[ContractIssue]:
    if (ref.profile_id, ref.profile_version) == (profile.profile_id, profile.profile_version):
        return []
    return [issue("PROFILE_MISMATCH", ref.profile_id, "граф построен по другому профилю")]


def value_matches(definition: AttributeDef, value: ScalarValue | None) -> bool:
    if value is None:
        return True
    if definition.value_type == ValueType.BOOLEAN:
        return isinstance(value, bool)
    if definition.value_type == ValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if definition.value_type == ValueType.NUMBER:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if not isinstance(value, str):
        return False
    return not definition.allowed_values or value in definition.allowed_values


def validate_profile(profile: MepSystemProfile) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for group in (profile.classes, profile.attributes, profile.relation_types, profile.systems):
        found += duplicates(item.key for item in group)
    known = {item.key for item in profile.attributes}
    for class_def in profile.classes:
        for key in class_def.attribute_keys:
            if key not in known:
                found.append(issue("UNKNOWN_ATTRIBUTE", class_def.key, f"атрибут {key} не описан"))
    return found


# --------------------------------------------------------------------------- evidence


def validate_evidence_graph(
    graph: MepEvidenceGraph, profile: MepSystemProfile | None = None
) -> list[ContractIssue]:
    found = duplicates([*(e.id for e in graph.elements), *(r.id for r in graph.relations)])
    found += duplicates(sheet.sheet_id for sheet in graph.sheets)
    found += _references(graph)
    found += check_sheets(graph.sheets)
    found += check_tools(graph.tools)
    found += check_review(graph)
    elements = {element.id: element for element in graph.elements}
    for element in graph.elements:
        found += _element(graph, element, elements)
    for relation in graph.relations:
        found += _relation(relation, elements)
    found += _duplicate_geometry(graph.elements)
    if profile is not None:
        found += profile_mismatch(graph.profile, profile)
        found += check_profile_pin(graph.profile, profile)
        found += _against_profile(graph, profile, elements)
    return found


def _references(graph: MepEvidenceGraph) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    sheets = {sheet.sheet_id for sheet in graph.sheets}
    levels = {level.level_id for level in graph.levels}
    tools = {tool.tool_id for tool in graph.tools}
    subjects = {*(e.id for e in graph.elements), *(r.id for r in graph.relations)}
    for sheet in graph.sheets:
        if sheet.level_id is not None and sheet.level_id not in levels:
            found.append(issue("UNKNOWN_LEVEL", sheet.sheet_id, "уровень листа не описан"))
    for element in graph.elements:
        if element.sheet_id not in sheets:
            found.append(issue("UNKNOWN_SHEET", element.id, "лист элемента не описан"))
        if element.level_id is not None and element.level_id not in levels:
            found.append(issue("UNKNOWN_LEVEL", element.id, "уровень элемента не описан"))
    for owner, sources in _all_sources(graph):
        for source in sources:
            if source.tool_id is not None and source.tool_id not in tools:
                found.append(issue("UNKNOWN_TOOL", owner, f"инструмент {source.tool_id} не описан"))
    for availability in graph.source_availability:
        if availability.sheet_id not in sheets:
            found.append(issue("UNKNOWN_SHEET", availability.sheet_id, "лист канала не описан"))
    for gap in graph.gaps:
        for subject in gap.subject_ids:
            if subject not in subjects:
                found.append(issue("UNKNOWN_SUBJECT", subject, f"пробел {gap.code} ссылается мимо"))
    return found


def _all_sources(graph: MepEvidenceGraph) -> Iterable[tuple[str, tuple[SourceRef, ...]]]:
    yield from ((element.id, element.sources) for element in graph.elements)
    yield from ((relation.id, relation.sources) for relation in graph.relations)


def _element(
    graph: MepEvidenceGraph, element: EvidenceElement, elements: dict[str, EvidenceElement]
) -> list[ContractIssue]:
    found = _origin(graph.input_mode, element.id, element.provenance, element.status)
    found += _review(element.id, element.status, element.review)
    found += _sources(graph, element.id, element.sheet_id, element.provenance, element.sources)
    if element.kind == "text" and not (element.text and element.text.strip()):
        found.append(issue("TEXT_WITHOUT_CONTENT", element.id, "текстовый элемент без текста"))
    unresolved_fields = {entry.field for entry in element.unresolved}
    if element.class_key is None and "class_key" not in unresolved_fields:
        found.append(issue("CLASS_UNRESOLVED_WITHOUT_REASON", element.id, "нет причины"))
    if element.provenance == EvidenceProvenance.UNRESOLVED and not element.unresolved:
        found.append(issue("UNRESOLVED_WITHOUT_REASON", element.id, "unresolved без причины"))
    sheet = next((s for s in graph.sheets if s.sheet_id == element.sheet_id), None)
    for attribute in element.attributes:
        found += _attribute(element.id, attribute, elements)
        calibrated = sheet is not None and sheet.scale_status == ScaleStatus.CALIBRATED
        if attribute.derivation == "measured" and not calibrated:
            found.append(
                issue("METRIC_WITHOUT_SCALE", element.id, f"{attribute.key} снят без калибровки")
            )
    return found


def _attribute(
    owner: str, attribute: EvidenceAttribute, elements: dict[str, EvidenceElement]
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for source_id in attribute.source_element_ids:
        source = elements.get(source_id)
        if source is None:
            found.append(issue("UNKNOWN_EVIDENCE", owner, f"источник {source_id} не найден"))
        elif source.kind != "text":
            found.append(issue("ATTRIBUTE_SOURCE_NOT_TEXT", owner, f"{source_id} — не текст"))
    return found


def _relation(
    relation: EvidenceRelation, elements: dict[str, EvidenceElement]
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for end in (relation.from_id, relation.to_id):
        if end not in elements:
            found.append(issue("RELATION_MISSING_ENDPOINT", relation.id, f"нет элемента {end}"))
    if relation.from_id == relation.to_id:
        found.append(issue("RELATION_SELF", relation.id, "связь элемента с самим собой"))
    found += _review(relation.id, relation.status, relation.review)
    return found


def _origin(
    mode: EvidenceInputMode, owner: str, provenance: EvidenceProvenance, status: EvidenceStatus
) -> list[ContractIssue]:
    human = provenance == EvidenceProvenance.HUMAN_GROUND_TRUTH
    if mode == EvidenceInputMode.MODEL_EXTRACTED and (
        human or status == EvidenceStatus.HUMAN_CONFIRMED
    ):
        return [issue("INPUT_MODE_CONFLICT", owner, "в MODEL_EXTRACTED нет участия человека")]
    if mode == EvidenceInputMode.HUMAN_GT and provenance not in (
        EvidenceProvenance.HUMAN_GROUND_TRUTH,
        EvidenceProvenance.UNRESOLVED,
    ):
        return [issue("INPUT_MODE_CONFLICT", owner, "HUMAN_GT содержит только разметку человека")]
    if human and status != EvidenceStatus.HUMAN_CONFIRMED:
        return [issue("PROVENANCE_STATUS_MISMATCH", owner, "разметка человека — human_confirmed")]
    return []


def _review(owner: str, status: EvidenceStatus, review: ReviewStatus) -> list[ContractIssue]:
    if status == EvidenceStatus.HUMAN_CONFIRMED and review != ReviewStatus.CONFIRMED:
        return [issue("HUMAN_CONFIRMED_NOT_REVIEWED", owner, "подтверждение без проверки")]
    return []


REQUIRED_SOURCE: dict[EvidenceProvenance, SourceType] = {
    EvidenceProvenance.BASE_RECOGNITION_OBSERVED: SourceType.BASE_REGION_TEXT,
    EvidenceProvenance.HUMAN_GROUND_TRUTH: SourceType.HUMAN_ANNOTATION,
}


def _sources(
    graph: MepEvidenceGraph,
    owner: str,
    sheet_id: str,
    provenance: EvidenceProvenance,
    sources: tuple[SourceRef, ...],
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    required = REQUIRED_SOURCE.get(provenance)
    if required is not None and all(source.source_type != required for source in sources):
        found.append(issue("PROVENANCE_SOURCE_MISMATCH", owner, f"нужен источник {required}"))
    automatic = (EvidenceProvenance.MEP_MODEL_OBSERVED, EvidenceProvenance.DETERMINISTIC_EXTRACTED)
    if provenance in automatic and all(source.tool_id is None for source in sources):
        found.append(issue("MISSING_TOOL", owner, "автоматический элемент без инструмента"))
    unavailable = {
        a.source_type
        for a in graph.source_availability
        if a.sheet_id == sheet_id and a.availability == Availability.UNAVAILABLE
    }
    for source in sources:
        if source.source_type in unavailable:
            found.append(
                issue("SOURCE_UNAVAILABLE", owner, f"канал {source.source_type} недоступен")
            )
    return found


def _duplicate_geometry(elements: Iterable[EvidenceElement]) -> list[ContractIssue]:
    seen: dict[tuple[str, str, str | None, str], str] = {}
    found: list[ContractIssue] = []
    for element in elements:
        key = (
            element.sheet_id,
            element.kind,
            element.class_key,
            element.geometry.model_dump_json(),
        )
        if key in seen:
            message = f"совпадает с {seen[key]}"
            found.append(issue("DUPLICATE_ELEMENT", element.id, message, warning=True))
        else:
            seen[key] = element.id
    return found


def _against_profile(
    graph: MepEvidenceGraph, profile: MepSystemProfile, elements: dict[str, EvidenceElement]
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for element in graph.elements:
        if element.system_key is not None and profile.system_def(element.system_key) is None:
            found.append(issue("UNKNOWN_SYSTEM", element.id, f"система {element.system_key}"))
        if element.class_key is None:
            continue
        class_def = profile.class_def(element.class_key)
        if class_def is None or class_def.layer != "evidence":
            found.append(issue("UNKNOWN_CLASS", element.id, f"класс {element.class_key}"))
            continue
        if class_def.evidence_kind != element.kind:
            found.append(issue("CLASS_KIND_MISMATCH", element.id, "вид не совпадает с классом"))
        if element.geometry.kind not in class_def.allowed_geometry:
            found.append(issue("GEOMETRY_NOT_ALLOWED", element.id, element.geometry.kind))
        for attribute in element.attributes:
            definition = profile.attribute_def(attribute.key)
            if definition is None or attribute.key not in class_def.attribute_keys:
                found.append(issue("UNKNOWN_ATTRIBUTE", element.id, attribute.key))
            elif not value_matches(definition, attribute.value):
                found.append(issue("ATTRIBUTE_TYPE_MISMATCH", element.id, attribute.key))
    for relation in graph.relations:
        definition_rel = profile.relation_def(relation.relation_key)
        if definition_rel is None:
            found.append(issue("UNKNOWN_RELATION", relation.id, relation.relation_key))
            continue
        start, end = elements.get(relation.from_id), elements.get(relation.to_id)
        if start is not None and start.kind not in definition_rel.from_kinds:
            found.append(issue("RELATION_KIND_MISMATCH", relation.id, "недопустимое начало"))
        if end is not None and end.kind not in definition_rel.to_kinds:
            found.append(issue("RELATION_KIND_MISMATCH", relation.id, "недопустимый конец"))
    return found
