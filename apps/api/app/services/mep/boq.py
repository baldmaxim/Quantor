"""Детерминированный движок ВОР эксперимента: `MepNetworkGraph` → `MepBoq` (STRICT).

```text
mep.segment_length.v0   участок класса quantity=length → м, группа по quantity_group_keys
mep.node_count.v0       узел класса quantity=count     → шт, группа по quantity_group_keys
mep.path_turns.v0       промежуточные повороты посчитанных участков, та же группа
mep.branch_nodes.v0     узлы, к которым подключено три и больше участков, по степени
mep.parameter_change.v0 узлы, где подключённые участки различаются значением ключа группы
```

У каждой строки — источники с вкладом, ссылки на параметры, давшие значения группы, и участники
производных величин. Топологические строки — геометрические факты, а не фасонные изделия:
сопоставление с фитингами требует утверждённых правил (Р-MEP-7). Модель, изображение и цена в
расчёте не участвуют; одинаковый вход даёт побитово одинаковый ВОР.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Final

from app.contracts.mep.boq import (
    BlockerCode,
    BoqLine,
    BoqStatus,
    EngineRef,
    GroupValueRef,
    MepBoq,
    NetworkGraphRef,
    Participant,
    QuantityBlocker,
    RuleRef,
)
from app.contracts.mep.common import (
    IssueSeverity,
    SubjectKind,
    SubjectRef,
    canonical_sha256,
)
from app.contracts.mep.evidence import MepEvidenceGraph
from app.contracts.mep.network import (
    Derivation,
    MepNetworkGraph,
    NetworkNode,
    NetworkSegment,
    Parameter,
)
from app.contracts.mep.network_validation import validate_network_graph
from app.contracts.mep.profile import ClassDef, MepSystemProfile
from app.contracts.mep.subjects import SubjectIndex
from app.services.mep.boq_lines import (
    Group,
    LineAccumulator,
    SourceAccumulator,
    build_line,
)
from app.services.mep.network_geometry import segment_length, turn_count

ENGINE: Final = EngineRef(name="mep-quantity-engine", version="0.3.1")
RULE_LENGTH: Final = "mep.segment_length.v0"
RULE_COUNT: Final = "mep.node_count.v0"
RULE_TURNS: Final = "mep.path_turns.v0"
RULE_BRANCHES: Final = "mep.branch_nodes.v0"
RULE_CHANGES: Final = "mep.parameter_change.v0"
RULES: Final = (
    RuleRef(
        rule_id=RULE_LENGTH,
        description="Сумма длин участков: план по калибровке, высота по отметкам.",
    ),
    RuleRef(rule_id=RULE_COUNT, description="Число узлов класса с правилом count."),
    RuleRef(
        rule_id=RULE_TURNS,
        description="Промежуточные вершины посчитанных участков со сменой направления.",
    ),
    RuleRef(
        rule_id=RULE_BRANCHES, description="Узлы, к которым подключено не меньше трёх участков."
    ),
    RuleRef(
        rule_id=RULE_CHANGES,
        description="Узлы, где подключённые участки различаются значением ключа.",
    ),
)


class _Builder:
    def __init__(
        self, graph: MepNetworkGraph, profile: MepSystemProfile, index: SubjectIndex
    ) -> None:
        self.graph = graph
        self.profile = profile
        self.index = index
        self.sheets = {sheet.sheet_id: sheet for sheet in graph.sheets}
        self.levels = {level.level_id: level for level in graph.levels}
        self.systems = {system.id: system.system_key for system in graph.systems}
        self.lines: dict[str, LineAccumulator] = {}
        self.blockers: list[QuantityBlocker] = []
        self.blocked_by_decision = {
            subject
            for decision in graph.unresolved
            if decision.blocks_quantity
            for subject in decision.subject_ids
        }
        self.counted: dict[str, tuple[Group, tuple[GroupValueRef, ...]]] = {}

    def block(
        self,
        code: BlockerCode,
        subjects: Iterable[str],
        message: str,
        *,
        key: str | None = None,
        warning: bool = False,
    ) -> None:
        self.blockers.append(blocker(self.index, code, subjects, message, key, warning))

    def add(
        self,
        line: LineAccumulator,
        subject: SubjectRef,
        amount: Decimal,
        derivations: Iterable[Derivation],
        *,
        group_values: tuple[GroupValueRef, ...] = (),
        participants: tuple[Participant, ...] = (),
    ) -> None:
        existing = self.lines.setdefault(line.sort_key, line)
        source = existing.sources.setdefault(subject.id, SourceAccumulator(kind=subject.kind))
        source.amount += amount
        source.group_values = group_values
        source.participants = participants
        existing.derivations.extend(derivations)

    def group(
        self, owner: SubjectRef, class_def: ClassDef, parameters: tuple[Parameter, ...]
    ) -> tuple[Group, tuple[GroupValueRef, ...], list[Derivation]] | None:
        values: list[tuple[str, bool | int | float | str]] = []
        refs: list[GroupValueRef] = []
        derivations: list[Derivation] = []
        complete = True
        for key in class_def.quantity_group_keys:
            parameter = next((p for p in parameters if p.key == key), None)
            if parameter is None:
                self.block(
                    BlockerCode.PARAMETER_MISSING, [owner.id], f"нет параметра {key}", key=key
                )
                complete = False
            elif parameter.value is None:
                message = f"{key} не определён"
                self.block(BlockerCode.PARAMETER_UNRESOLVED, [owner.id], message, key=key)
                complete = False
            else:
                values.append((key, parameter.value))
                refs.append(GroupValueRef(key=key, subject=owner, parameter_key=key))
                derivations.append(parameter.derivation)
        if owner.id in self.blocked_by_decision:
            self.block(BlockerCode.DECISION_BLOCKS_QUANTITY, [owner.id], "решение не принято")
            complete = False
        return (tuple(values), tuple(refs), derivations) if complete else None

    def segments(self) -> None:
        for segment in sorted(self.graph.segments, key=lambda s: s.id):
            class_def = self._class(segment.id, segment.class_key)
            if class_def is None or class_def.quantity != "length":
                continue
            subject = SubjectRef(kind=SubjectKind.SEGMENT, id=segment.id)
            grouped = self.group(subject, class_def, segment.parameters)
            if grouped is None:
                continue
            group, refs, derivations = grouped
            length = segment_length(segment, self.sheets, self.levels)
            if length.millimetres is None or length.blocker is not None:
                code = length.blocker or BlockerCode.LENGTH_UNDETERMINED
                self.block(code, [segment.id], "длина участка не определяется")
                continue
            system_key = self.systems[segment.system_id]
            used = [segment.derivation, *derivations]
            self.add(
                LineAccumulator(RULE_LENGTH, "length", system_key, segment.class_key, group),
                subject,
                length.millimetres,
                used,
                group_values=refs,
            )
            self.counted[segment.id] = (group, refs)
            turns = turn_count(segment, self.sheets, self.levels)
            if turns:
                self.add(
                    LineAccumulator(RULE_TURNS, "topology", system_key, segment.class_key, group),
                    subject,
                    Decimal(turns),
                    used,
                    group_values=refs,
                )

    def nodes(self) -> None:
        for node in sorted(self.graph.nodes, key=lambda n: n.id):
            class_def = self._class(node.id, node.class_key)
            if class_def is None or class_def.quantity != "count":
                continue
            subject = SubjectRef(kind=SubjectKind.NODE, id=node.id)
            grouped = self.group(subject, class_def, node.parameters)
            system_key = self._node_system(node)
            if grouped is None or system_key is None:
                continue
            group, refs, derivations = grouped
            self.add(
                LineAccumulator(RULE_COUNT, "count", system_key, node.class_key, group),
                subject,
                Decimal(1),
                [node.derivation, *derivations],
                group_values=refs,
            )

    def topology(self) -> None:
        connected: dict[str, list[NetworkSegment]] = defaultdict(list)
        for segment in sorted(self.graph.segments, key=lambda s: s.id):
            connected[segment.start.node_id].append(segment)
            connected[segment.end.node_id].append(segment)
        for node in sorted(self.graph.nodes, key=lambda n: n.id):
            attached = connected.get(node.id, [])
            system_key = self._single_system(attached)
            if system_key is None:
                continue
            subject = SubjectRef(kind=SubjectKind.NODE, id=node.id)
            derivations = [node.derivation, *(s.derivation for s in attached)]
            if len(attached) >= 3:
                participants = (
                    Participant(subject=subject, role="anchor"),
                    *(
                        Participant(
                            subject=SubjectRef(kind=SubjectKind.SEGMENT, id=s.id), role="connected"
                        )
                        for s in attached
                    ),
                )
                self.add(
                    LineAccumulator(
                        RULE_BRANCHES,
                        "topology",
                        system_key,
                        node.class_key,
                        (("core.degree", len(attached)),),
                    ),
                    subject,
                    Decimal(1),
                    derivations,
                    participants=participants,
                )
            self._parameter_changes(node, attached, system_key, derivations)

    def _parameter_changes(
        self,
        node: NetworkNode,
        attached: list[NetworkSegment],
        system_key: str,
        derivations: list[Derivation],
    ) -> None:
        if len(attached) < 2 or any(s.id not in self.counted for s in attached):
            return
        groups = {s.id: dict(self.counted[s.id][0]) for s in attached}
        subject = SubjectRef(kind=SubjectKind.NODE, id=node.id)
        for key in sorted({key for group in groups.values() for key in group}):
            values = sorted({json.dumps(group.get(key)) for group in groups.values()})
            if len(values) < 2:
                continue
            participants = (
                Participant(subject=subject, role="anchor"),
                *(
                    Participant(
                        subject=SubjectRef(kind=SubjectKind.SEGMENT, id=segment_id),
                        role="compared",
                        parameter_key=key,
                        value=groups[segment_id].get(key),
                    )
                    for segment_id in sorted(groups)
                ),
            )
            self.add(
                LineAccumulator(
                    RULE_CHANGES,
                    "topology",
                    system_key,
                    None,
                    (("core.parameter", key), ("core.values", "|".join(values))),
                ),
                subject,
                Decimal(1),
                derivations,
                participants=participants,
            )

    def _single_system(self, attached: list[NetworkSegment]) -> str | None:
        keys = {self.systems[s.system_id] for s in attached if s.system_id in self.systems}
        return next(iter(keys)) if len(keys) == 1 else None

    def _node_system(self, node: NetworkNode) -> str | None:
        keys = sorted({self.systems[s] for s in node.system_ids if s in self.systems})
        if len(keys) != 1:
            message = "узел не отнесён к одной системе"
            self.block(BlockerCode.NODE_SYSTEM_AMBIGUOUS, [node.id], message)
            return None
        return keys[0]

    def _class(self, owner: str, class_key: str | None) -> ClassDef | None:
        if class_key is None:
            self.block(BlockerCode.CLASS_UNRESOLVED, [owner], "класс не определён")
            return None
        return self.profile.class_def(class_key)

    def result(self) -> tuple[list[BoqLine], list[QuantityBlocker]]:
        lines = [build_line(line) for _, line in sorted(self.lines.items())]
        if any(line.category == "topology" for line in lines):
            message = "топология не сопоставлена с фитингами (Р-MEP-7)"
            self.block(BlockerCode.FITTING_RULES_NOT_APPROVED, [], message, warning=True)
        return lines, _sorted_blockers(self.blockers)


def blocker(
    index: SubjectIndex,
    code: BlockerCode,
    subjects: Iterable[str],
    message: str,
    key: str | None = None,
    warning: bool = False,
) -> QuantityBlocker:
    ids = sorted(set(subjects))
    refs = [ref for ref in (index.ref(subject_id) for subject_id in ids) if ref is not None]
    return QuantityBlocker(
        code=code,
        severity="warning" if warning else "blocker",
        subject_ids=tuple(ids),
        subjects=tuple(refs),
        key=key,
        message=message,
    )


def _sorted_blockers(blockers: list[QuantityBlocker]) -> list[QuantityBlocker]:
    unique = {canonical_sha256(b): b for b in blockers}
    return sorted(unique.values(), key=lambda b: (b.code, b.subject_ids, b.key or "", b.message))


def build_boq(
    graph: MepNetworkGraph,
    profile: MepSystemProfile,
    evidence: MepEvidenceGraph | None = None,
) -> MepBoq:
    """ВОР из графа. Невалидный граф ВОР не получает: статус `refused` и коды проверки."""
    network_sha = canonical_sha256(graph)
    head = {
        "boq_id": f"boq-{network_sha[:16]}",
        "network_graph": NetworkGraphRef(graph_id=graph.graph_id, sha256=network_sha),
        "evidence_graph": graph.evidence_graph,
        "profile": graph.profile,
        "engine": ENGINE,
        "rules": RULES,
    }
    index = SubjectIndex(graph, evidence)
    issues = validate_network_graph(graph, evidence, profile)
    errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
    if errors:
        codes = ", ".join(sorted({i.code for i in errors}))
        subjects = sorted({i.subject_id for i in errors if i.subject_id})[:256]
        message = f"граф не прошёл проверку: {codes}"[:512]
        refusal = blocker(index, BlockerCode.NETWORK_INVALID, subjects, message)
        return MepBoq(status=BoqStatus.REFUSED, lines=(), blockers=(refusal,), **head)

    builder = _Builder(graph, profile, index)
    builder.segments()
    builder.nodes()
    builder.topology()
    lines, blockers = builder.result()
    blocked = any(b.severity == "blocker" for b in blockers)
    status = BoqStatus.PARTIAL if blocked else BoqStatus.COMPLETE
    return MepBoq(status=status, lines=tuple(lines), blockers=tuple(blockers), **head)
