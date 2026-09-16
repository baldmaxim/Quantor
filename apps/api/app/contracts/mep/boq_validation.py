"""Проверка `MepBoq` против сети: ссылки разрешаются, значения группы берутся из параметров."""

from __future__ import annotations

from app.contracts.mep.boq import BoqLine, MepBoq
from app.contracts.mep.common import (
    ContractIssue,
    SubjectKind,
    SubjectRef,
    canonical_sha256,
    issue,
)
from app.contracts.mep.evidence import MepEvidenceGraph
from app.contracts.mep.network import MepNetworkGraph, Parameter
from app.contracts.mep.subjects import SubjectIndex


def validate_boq(
    boq: MepBoq, network: MepNetworkGraph, evidence: MepEvidenceGraph | None = None
) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    if boq.network_graph.sha256 != canonical_sha256(network):
        found.append(issue("BOQ_NETWORK_MISMATCH", boq.boq_id, "ВОР построен по другой сети"))
    index = SubjectIndex(network, evidence)
    for line in boq.lines:
        found += _line(line, network, index)
    for blocker in boq.blockers:
        found += _refs(index, blocker.code.value, blocker.subjects)
        if not {ref.id for ref in blocker.subjects} <= set(blocker.subject_ids):
            found.append(
                issue("SUBJECT_REFS_MISMATCH", blocker.code.value, "subjects вне subject_ids")
            )
    return found


def _refs(index: SubjectIndex, owner: str, refs: tuple[SubjectRef, ...]) -> list[ContractIssue]:
    return [_ref(index, owner, ref) for ref in refs if not index.exists(ref)]


def _ref(index: SubjectIndex, owner: str, ref: SubjectRef) -> ContractIssue:
    code = "SUBJECT_KIND_MISMATCH" if index.known(ref.id) else "UNKNOWN_SUBJECT"
    return issue(code, owner, f"{ref.kind}:{ref.id}")


def _parameters(network: MepNetworkGraph, ref: SubjectRef) -> tuple[Parameter, ...] | None:
    if ref.kind == SubjectKind.SEGMENT:
        return next((s.parameters for s in network.segments if s.id == ref.id), None)
    if ref.kind == SubjectKind.NODE:
        return next((n.parameters for n in network.nodes if n.id == ref.id), None)
    return None


def _line(line: BoqLine, network: MepNetworkGraph, index: SubjectIndex) -> list[ContractIssue]:
    found: list[ContractIssue] = []
    group = {attribute.key: attribute.value for attribute in line.group}
    for source in line.sources:
        found += _refs(index, line.line_id, (source.subject,))
        found += _refs(index, line.line_id, tuple(p.subject for p in source.participants))
        for ref in source.group_values:
            found += _refs(index, line.line_id, (ref.subject,))
            parameters = _parameters(network, ref.subject) or ()
            parameter = next((p for p in parameters if p.key == ref.parameter_key), None)
            if parameter is None or parameter.value != group.get(ref.key):
                found.append(
                    issue("GROUP_VALUE_MISMATCH", line.line_id, f"{ref.key}@{ref.subject.id}")
                )
        covered = {ref.key for ref in source.group_values}
        profile_keys = {key for key in group if not key.startswith("core.")}
        if covered and covered != profile_keys:
            found.append(issue("GROUP_VALUE_UNREFERENCED", line.line_id, source.subject.id))
    return found
