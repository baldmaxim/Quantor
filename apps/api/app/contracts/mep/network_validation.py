"""Смысловые проверки `MepNetworkGraph`: ссылки, происхождение, топология, профиль."""

from __future__ import annotations

from collections.abc import Iterable

from app.contracts.mep.common import (
    ContractIssue,
    ScaleStatus,
    SubjectRef,
    canonical_sha256,
    issue,
)
from app.contracts.mep.evidence import MepEvidenceGraph, ReviewStatus
from app.contracts.mep.network import (
    Derivation,
    GenerationProvenance,
    MepNetworkGraph,
    NetworkNode,
    NetworkSegment,
    Parameter,
    UnresolvedCode,
    Vertex,
)
from app.contracts.mep.profile import MepSystemProfile, NodeRole
from app.contracts.mep.provenance_checks import (
    check_generation,
    check_profile_pin,
    check_sheets,
    check_tools,
)
from app.contracts.mep.subjects import SubjectIndex
from app.contracts.mep.validation import duplicates, profile_mismatch, value_matches

# Узлы, которые обязаны быть подключены к сети.
CONNECTED_ROLES = (NodeRole.SOURCE, NodeRole.TERMINAL, NodeRole.EQUIPMENT, NodeRole.DEVICE)
STEP_BACKED = (
    GenerationProvenance.RD_PRIOR_INFERRED,
    GenerationProvenance.RETRIEVED_PATTERN,
    GenerationProvenance.DETERMINISTIC_RULE,
)


def validate_network_graph(
    graph: MepNetworkGraph,
    evidence: MepEvidenceGraph | None = None,
    profile: MepSystemProfile | None = None,
) -> list[ContractIssue]:
    ports = [port for node in graph.nodes for port in node.ports]
    found = duplicates(
        [
            *(system.id for system in graph.systems),
            *(node.id for node in graph.nodes),
            *(port.id for port in ports),
            *(segment.id for segment in graph.segments),
            *(step.id for step in graph.inference_steps),
            *(decision.id for decision in graph.unresolved),
        ]
    )
    found += _evidence_link(graph, evidence)
    found += check_sheets(graph.sheets)
    found += check_tools(graph.tools)
    found += check_generation(graph)
    found += _steps(graph, evidence)
    for owner, derivation in _derivations(graph):
        found += _derivation(graph, evidence, owner, derivation)
    found += _placement(graph)
    found += _topology(graph)
    if profile is not None:
        found += profile_mismatch(graph.profile, profile)
        found += check_profile_pin(graph.profile, profile)
        found += _against_profile(graph, profile)
    return found


def _evidence_link(
    graph: MepNetworkGraph, evidence: MepEvidenceGraph | None
) -> list[ContractIssue]:
    if evidence is None:
        return []
    ref = graph.evidence_graph
    if ref.graph_id != evidence.graph_id or ref.input_mode != evidence.input_mode:
        return [issue("EVIDENCE_GRAPH_MISMATCH", ref.graph_id, "ссылка на другой граф evidence")]
    if ref.sha256 != canonical_sha256(evidence):
        return [issue("EVIDENCE_GRAPH_MISMATCH", ref.graph_id, "хеш evidence не совпадает")]
    if graph.document != evidence.document:
        return [issue("EVIDENCE_GRAPH_MISMATCH", ref.graph_id, "другой исходный документ")]
    return []


def _steps(graph: MepNetworkGraph, evidence: MepEvidenceGraph | None) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    tools = {tool.tool_id for tool in graph.tools}
    earlier: set[str] = set()
    for step in graph.inference_steps:
        if step.tool_id not in tools:
            found.append(issue("UNKNOWN_TOOL", step.id, f"инструмент {step.tool_id} не описан"))
        for input_id in step.input_step_ids:
            if input_id not in earlier:
                found.append(issue("STEP_ORDER", step.id, f"вход {input_id} не предшествует шагу"))
        if evidence is not None:
            elements = {element.id for element in evidence.elements}
            relations = {relation.id for relation in evidence.relations}
            for evidence_id in step.evidence_ids:
                if evidence_id not in elements:
                    found.append(issue("UNKNOWN_EVIDENCE", step.id, evidence_id))
            for relation_id in step.relation_ids:
                if relation_id not in relations:
                    found.append(issue("UNKNOWN_EVIDENCE", step.id, relation_id))
        earlier.add(step.id)
    return found


def _parameters(owner: str, parameters: Iterable[Parameter]) -> Iterable[tuple[str, Derivation]]:
    return ((f"{owner}.{parameter.key}", parameter.derivation) for parameter in parameters)


def _derivations(graph: MepNetworkGraph) -> Iterable[tuple[str, Derivation]]:
    for system in graph.systems:
        yield system.id, system.derivation
    for node in graph.nodes:
        yield node.id, node.derivation
        yield from _parameters(node.id, node.parameters)
        for port in node.ports:
            yield from _parameters(port.id, port.parameters)
    for segment in graph.segments:
        yield segment.id, segment.derivation
        yield from _parameters(segment.id, segment.parameters)


def _derivation(
    graph: MepNetworkGraph, evidence: MepEvidenceGraph | None, owner: str, derivation: Derivation
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    steps = {step.id: step for step in graph.inference_steps}
    for step_id in derivation.step_ids:
        if step_id not in steps:
            found.append(issue("UNKNOWN_STEP", owner, f"шаг {step_id} не найден"))
    provenance = derivation.provenance
    if provenance == GenerationProvenance.EVIDENCE_OBSERVED and not derivation.evidence_ids:
        found.append(issue("OBSERVED_WITHOUT_EVIDENCE", owner, "observed без ссылки на evidence"))
    if provenance in STEP_BACKED and not derivation.step_ids:
        found.append(issue("INFERRED_WITHOUT_STEP", owner, f"{provenance} без шага вывода"))
    used = [steps[step_id] for step_id in derivation.step_ids if step_id in steps]
    if provenance == GenerationProvenance.RETRIEVED_PATTERN and not any(
        step.retrieved_case_ids for step in used
    ):
        found.append(issue("MISSING_RULE_OR_CASE", owner, "retrieved_pattern без случая корпуса"))
    if provenance == GenerationProvenance.DETERMINISTIC_RULE and not any(
        step.rule_ids for step in used
    ):
        found.append(issue("MISSING_RULE_OR_CASE", owner, "deterministic_rule без правила"))
    if evidence is not None:
        elements = {element.id: element for element in evidence.elements}
        for evidence_id in derivation.evidence_ids:
            element = elements.get(evidence_id)
            if element is None:
                found.append(issue("UNKNOWN_EVIDENCE", owner, evidence_id))
            elif element.review == ReviewStatus.REJECTED:
                found.append(issue("EVIDENCE_REJECTED", owner, f"{evidence_id} отклонён"))
    return found


def _placement(graph: MepNetworkGraph) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    sheets = {sheet.sheet_id: sheet for sheet in graph.sheets}
    levels = {level.level_id for level in graph.levels}
    scale_deferred = {
        subject
        for decision in graph.unresolved
        if decision.code == UnresolvedCode.MISSING_SCALE
        for subject in decision.subject_ids
    }

    def vertex(owner: str, point: Vertex) -> None:
        if point.sheet_id is not None and point.sheet_id not in sheets:
            found.append(issue("UNKNOWN_SHEET", owner, f"лист {point.sheet_id} не описан"))
        if point.level_id is not None and point.level_id not in levels:
            found.append(issue("UNKNOWN_LEVEL", owner, f"уровень {point.level_id} не описан"))

    for node in graph.nodes:
        vertex(node.id, node.position)
    for segment in graph.segments:
        for point in segment.path:
            vertex(segment.id, point)
        if segment.orientation == "vertical" and not _changes_height(segment):
            found.append(issue("VERTICAL_WITHOUT_ELEVATION", segment.id, "нет отметок или уровней"))
        planar_sheets = {p.sheet_id for p in segment.path if p.x is not None and p.sheet_id}
        uncalibrated = [
            sheet_id
            for sheet_id in planar_sheets
            if sheet_id in sheets and sheets[sheet_id].scale_status != ScaleStatus.CALIBRATED
        ]
        if uncalibrated and segment.id not in scale_deferred:
            found.append(
                issue("QUANTITY_BLOCKED_NO_SCALE", segment.id, "лист без калибровки", warning=True)
            )
    return found


def _changes_height(segment: NetworkSegment) -> bool:
    heights = {p.z_mm for p in segment.path if p.z_mm is not None}
    levels = {p.level_id for p in segment.path if p.level_id is not None}
    return len(heights) > 1 or len(levels) > 1


def _topology(graph: MepNetworkGraph) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    systems = {system.id for system in graph.systems}
    nodes = {node.id: node for node in graph.nodes}
    port_owner = {port.id: (node, port) for node in graph.nodes for port in node.ports}
    usage: dict[str, int] = {}
    degree: dict[str, int] = {}
    for segment in graph.segments:
        if segment.system_id not in systems:
            found.append(issue("UNKNOWN_SYSTEM", segment.id, segment.system_id))
        if segment.start == segment.end:
            found.append(issue("SEGMENT_SELF_LOOP", segment.id, "начало и конец — один порт"))
        for end in (segment.start, segment.end):
            owner = port_owner.get(end.port_id)
            if end.node_id not in nodes or owner is None or owner[0].id != end.node_id:
                found.append(issue("SEGMENT_MISSING_ENDPOINT", segment.id, end.port_id))
                continue
            usage[end.port_id] = usage.get(end.port_id, 0) + 1
            degree[end.node_id] = degree.get(end.node_id, 0) + 1
            port_system = owner[1].system_id
            if port_system is not None and port_system != segment.system_id:
                found.append(issue("CROSS_SYSTEM_CONNECTION", segment.id, end.port_id))
    for node in graph.nodes:
        found += _node(node, systems, degree, graph)
        for port in node.ports:
            if port.system_id is not None and port.system_id not in systems:
                found.append(issue("UNKNOWN_SYSTEM", port.id, port.system_id))
            if usage.get(port.id, 0) > 1:
                found.append(
                    issue("PORT_OVER_CONNECTED", port.id, "к порту подключено больше одного")
                )
            if usage.get(port.id, 0) == 0:
                found.append(issue("UNUSED_PORT", port.id, "порт не подключён", warning=True))
    known = {*nodes, *port_owner, *systems, *(s.id for s in graph.segments)}
    steps = {step.id for step in graph.inference_steps}
    for decision in graph.unresolved:
        for subject in (*decision.subject_ids, *decision.candidate_ids):
            if subject not in known:
                found.append(issue("UNKNOWN_SUBJECT", decision.id, subject))
        for step_id in decision.step_ids:
            if step_id not in steps:
                found.append(issue("UNKNOWN_STEP", decision.id, step_id))
        found += _typed_subjects(graph, decision.id, decision.subject_ids, decision.subjects)
    return found


def _typed_subjects(
    graph: MepNetworkGraph, owner: str, ids: tuple[str, ...], refs: tuple[SubjectRef, ...]
) -> list[ContractIssue]:
    if not refs:
        return []
    index = SubjectIndex(graph)
    found = [
        issue("SUBJECT_KIND_MISMATCH", owner, f"{ref.kind}:{ref.id}")
        for ref in refs
        if not index.exists(ref)
    ]
    if sorted({ref.id for ref in refs}) != sorted(set(ids)):
        found.append(issue("SUBJECT_REFS_MISMATCH", owner, "subjects не совпадают с subject_ids"))
    return found


def _node(
    node: NetworkNode, systems: set[str], degree: dict[str, int], graph: MepNetworkGraph
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for system_id in node.system_ids:
        if system_id not in systems:
            found.append(issue("UNKNOWN_SYSTEM", node.id, system_id))
    deferred = any(node.id in decision.subject_ids for decision in graph.unresolved)
    if node.role in CONNECTED_ROLES and degree.get(node.id, 0) == 0:
        found.append(issue("DISCONNECTED_NODE", node.id, "узел не подключён", warning=deferred))
    if node.role == NodeRole.JUNCTION and degree.get(node.id, 0) < 3:
        found.append(issue("JUNCTION_DEGREE", node.id, "разветвление меньше трёх", warning=True))
    if node.class_key is None and node.role != NodeRole.UNRESOLVED_ANCHOR and not deferred:
        found.append(issue("CLASS_UNRESOLVED_WITHOUT_DECISION", node.id, "класс не определён"))
    return found


def _cycles(graph: MepNetworkGraph, system_id: str) -> list[str]:
    parent = {node.id: node.id for node in graph.nodes}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    closing: list[str] = []
    for segment in graph.segments:
        if segment.system_id != system_id:
            continue
        if segment.start.node_id not in parent or segment.end.node_id not in parent:
            continue
        a, b = root(segment.start.node_id), root(segment.end.node_id)
        if a == b:
            closing.append(segment.id)
        else:
            parent[a] = b
    return closing


def _against_profile(graph: MepNetworkGraph, profile: MepSystemProfile) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    for system in graph.systems:
        definition = profile.system_def(system.system_key)
        if definition is None:
            found.append(issue("UNKNOWN_SYSTEM", system.id, system.system_key))
        elif definition.topology == "tree":
            for segment_id in _cycles(graph, system.id):
                found.append(issue("CYCLE_IN_TREE_SYSTEM", segment_id, f"цикл в {system.id}"))
    elements: list[tuple[str, str | None, str, NodeRole | None, tuple[Parameter, ...]]] = [
        (node.id, node.class_key, "node", node.role, node.parameters) for node in graph.nodes
    ]
    elements += [(s.id, s.class_key, "segment", None, s.parameters) for s in graph.segments]
    for owner, class_key, element, role, parameters in elements:
        if class_key is None:
            continue
        class_def = profile.class_def(class_key)
        if (
            class_def is None
            or class_def.layer != "network"
            or class_def.network_element != element
        ):
            found.append(issue("UNKNOWN_CLASS", owner, class_key))
            continue
        if role is not None and role not in class_def.node_roles:
            found.append(issue("ROLE_NOT_ALLOWED", owner, f"{role} для {class_key}"))
        for parameter in parameters:
            definition_attr = profile.attribute_def(parameter.key)
            if definition_attr is None or parameter.key not in class_def.attribute_keys:
                found.append(issue("UNKNOWN_ATTRIBUTE", owner, parameter.key))
            elif not value_matches(definition_attr, parameter.value):
                found.append(issue("ATTRIBUTE_TYPE_MISMATCH", owner, parameter.key))
    return found
