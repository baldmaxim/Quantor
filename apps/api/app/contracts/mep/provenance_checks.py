"""Неизменяемое происхождение: калибровка, профиль, модели, прогон, корпус, проверка человеком."""

from __future__ import annotations

from collections.abc import Iterable

from app.contracts.mep.common import (
    ContractIssue,
    ProfileRef,
    ScaleStatus,
    SheetRef,
    Tool,
    calibration_fingerprint,
    canonical_sha256,
    issue,
)
from app.contracts.mep.evidence import (
    CORRECTED_FIELD,
    EvidenceElement,
    EvidenceInputMode,
    EvidenceProvenance,
    EvidenceStatus,
    MepEvidenceGraph,
    ReviewAction,
    ReviewEvent,
    ReviewStatus,
)
from app.contracts.mep.network import MepNetworkGraph
from app.contracts.mep.profile import MepSystemProfile

CORRECTIONS = frozenset(CORRECTED_FIELD)
STATUS_ACTIONS: dict[ReviewStatus, frozenset[ReviewAction]] = {
    ReviewStatus.CONFIRMED: frozenset(
        {ReviewAction.CONFIRM, ReviewAction.ADD_MISSING, *CORRECTIONS}
    ),
    ReviewStatus.REJECTED: frozenset({ReviewAction.REJECT}),
    ReviewStatus.AMBIGUOUS: frozenset({ReviewAction.MARK_AMBIGUOUS}),
}


def check_sheets(sheets: Iterable[SheetRef]) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for sheet in sheets:
        snapshot = sheet.calibration
        if snapshot is None:
            if sheet.scale_status == ScaleStatus.CALIBRATED:
                found.append(issue("CALIBRATION_SNAPSHOT_MISSING", sheet.sheet_id, "нет снимка"))
            continue
        if sheet.scale_status != ScaleStatus.CALIBRATED:
            found.append(issue("CALIBRATION_STATUS_MISMATCH", sheet.sheet_id, "снимок без статуса"))
        if snapshot.calibration_id != sheet.scale_calibration_id:
            found.append(issue("CALIBRATION_ID_MISMATCH", sheet.sheet_id, "другая калибровка"))
        if snapshot.page_geometry_fingerprint != sheet.geometry_fingerprint:
            found.append(issue("CALIBRATION_GEOMETRY_MISMATCH", sheet.sheet_id, "другая страница"))
        if snapshot.fingerprint != calibration_fingerprint(snapshot):
            found.append(
                issue("CALIBRATION_FINGERPRINT_MISMATCH", sheet.sheet_id, "снимок изменён")
            )
    return found


def check_profile_pin(ref: ProfileRef, profile: MepSystemProfile) -> list[ContractIssue]:
    if ref.profile_sha256 is None:
        return [issue("PROFILE_NOT_PINNED", ref.profile_id, "нет хеша профиля")]
    if ref.profile_sha256 != canonical_sha256(profile):
        return [issue("PROFILE_FINGERPRINT_MISMATCH", ref.profile_id, "профиль изменён")]
    return []


def check_tools(tools: Iterable[Tool]) -> list[ContractIssue]:
    return [
        issue("MODEL_PROVENANCE_INCOMPLETE", tool.tool_id, "модель без хешей весов и конфигурации")
        for tool in tools
        if tool.model_id is not None and (tool.weights_sha256 is None or tool.config_sha256 is None)
    ]


def check_generation(graph: MepNetworkGraph) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    corpora = {corpus.corpus_id for corpus in graph.corpora}
    if len(corpora) != len(graph.corpora):
        found.append(issue("DUPLICATE_ID", None, "корпус описан дважды"))
    if graph.inference_steps and graph.run is None:
        found.append(issue("RUN_PROVENANCE_MISSING", graph.graph_id, "шаги без прогона"))
    for step in graph.inference_steps:
        if graph.run is not None and step.run_id != graph.run.run_id:
            found.append(issue("STEP_RUN_MISMATCH", step.id, "шаг не из прогона графа"))
        if step.retrieved_case_ids and step.corpus_id is None:
            found.append(issue("CORPUS_NOT_PINNED", step.id, "случаи без корпуса"))
        if step.corpus_id is not None and step.corpus_id not in corpora:
            found.append(issue("UNKNOWN_CORPUS", step.id, step.corpus_id))
    return found


def check_review(graph: MepEvidenceGraph) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    tools = {tool.tool_id for tool in graph.tools}
    histories = [
        *(e.review_history for e in graph.elements),
        *(r.review_history for r in graph.relations),
    ]
    events = [event.event_id for history in histories for event in history]
    if len(set(events)) != len(events):
        found.append(issue("DUPLICATE_ID", None, "событие проверки повторяется"))
    mode = graph.input_mode
    for element in graph.elements:
        if mode == EvidenceInputMode.MODEL_EXTRACTED and (
            element.original or element.review_history
        ):
            found.append(issue("INPUT_MODE_CONFLICT", element.id, "проверка в MODEL_EXTRACTED"))
        if mode == EvidenceInputMode.HUMAN_GT and element.original is not None:
            found.append(issue("INPUT_MODE_CONFLICT", element.id, "предсказание в HUMAN_GT"))
        if element.original is not None and element.original.tool_id not in tools:
            found.append(issue("UNKNOWN_TOOL", element.id, element.original.tool_id))
        if mode == EvidenceInputMode.HYBRID_REVIEWED:
            found += _hybrid_element(element)
    for relation in graph.relations:
        found += _history(relation.id, relation.review, relation.review_history, required=False)
        if mode == EvidenceInputMode.MODEL_EXTRACTED and relation.review_history:
            found.append(issue("INPUT_MODE_CONFLICT", relation.id, "проверка в MODEL_EXTRACTED"))
        if mode == EvidenceInputMode.HYBRID_REVIEWED and (
            relation.review != ReviewStatus.UNREVIEWED and not relation.review_history
        ):
            found.append(issue("REVIEW_HISTORY_MISSING", relation.id, "нет истории проверки"))
    return found


def _history(
    owner: str, review: ReviewStatus, history: tuple[ReviewEvent, ...], *, required: bool
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    if required and not history:
        found.append(issue("REVIEW_HISTORY_MISSING", owner, "нет истории проверки"))
    moments = [event.reviewed_at for event in history]
    if moments != sorted(moments):
        found.append(issue("REVIEW_HISTORY_ORDER", owner, "история не по времени"))
    allowed = STATUS_ACTIONS.get(review)
    if history and allowed is not None and history[-1].action not in allowed:
        found.append(issue("REVIEW_STATUS_UNSUPPORTED", owner, f"{review} не следует из истории"))
    return found


def _hybrid_element(element: EvidenceElement) -> list[ContractIssue]:
    human = element.provenance == EvidenceProvenance.HUMAN_GROUND_TRUTH
    touched = (
        human
        or element.status == EvidenceStatus.HUMAN_CONFIRMED
        or element.review != ReviewStatus.UNREVIEWED
    )
    found = _history(element.id, element.review, element.review_history, required=touched)
    actions = {event.action for event in element.review_history}
    added = ReviewAction.ADD_MISSING in actions
    if human and not added and element.original is None:
        found.append(issue("ORIGINAL_PREDICTION_MISSING", element.id, "исправлено без исходного"))
    if added and element.original is not None:
        found.append(
            issue("ORIGINAL_PREDICTION_CONFLICT", element.id, "добавлен, но был предсказан")
        )
    if actions & CORRECTIONS and not human:
        found.append(issue("CORRECTION_NOT_REFLECTED", element.id, "исправлен, но не human"))
    original = element.original
    if original is None:
        return found
    current: dict[str, object] = {
        "class_key": element.class_key,
        "system_key": element.system_key,
        "geometry": element.geometry,
        "attributes": [(a.key, a.value, a.unit) for a in element.attributes],
    }
    before: dict[str, object] = {
        "class_key": original.class_key,
        "system_key": original.system_key,
        "geometry": original.geometry,
        "attributes": [(a.key, a.value, a.unit) for a in original.attributes],
    }
    for action, field in CORRECTED_FIELD.items():
        if current[field] != before[field] and action not in actions:
            found.append(issue("UNRECORDED_CORRECTION", element.id, f"{field} изменён без записи"))
    return found
