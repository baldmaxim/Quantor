"""Разрешение типизированных ссылок `SubjectRef` по графам MEP."""

from __future__ import annotations

from collections import defaultdict

from app.contracts.mep.common import SubjectKind, SubjectRef
from app.contracts.mep.evidence import MepEvidenceGraph
from app.contracts.mep.network import MepNetworkGraph


class SubjectIndex:
    """Какие объекты какого вида есть в графах. Один id может встречаться у разных видов."""

    def __init__(self, network: MepNetworkGraph, evidence: MepEvidenceGraph | None = None) -> None:
        self._kinds: dict[str, set[SubjectKind]] = defaultdict(set)
        entries: list[tuple[SubjectKind, str]] = [
            *((SubjectKind.NODE, node.id) for node in network.nodes),
            *((SubjectKind.PORT, port.id) for node in network.nodes for port in node.ports),
            *((SubjectKind.SEGMENT, segment.id) for segment in network.segments),
            *((SubjectKind.SYSTEM, system.id) for system in network.systems),
            *((SubjectKind.INFERENCE_STEP, step.id) for step in network.inference_steps),
            *((SubjectKind.UNRESOLVED_DECISION, item.id) for item in network.unresolved),
            *((SubjectKind.SHEET, sheet.sheet_id) for sheet in network.sheets),
            *((SubjectKind.LEVEL, level.level_id) for level in network.levels),
            *((SubjectKind.TOOL, tool.tool_id) for tool in network.tools),
            *((SubjectKind.CORPUS, corpus.corpus_id) for corpus in network.corpora),
        ]
        if evidence is not None:
            entries += [(SubjectKind.EVIDENCE_ELEMENT, e.id) for e in evidence.elements]
            entries += [(SubjectKind.EVIDENCE_RELATION, r.id) for r in evidence.relations]
            entries += [(SubjectKind.SHEET, s.sheet_id) for s in evidence.sheets]
        for kind, subject_id in entries:
            self._kinds[subject_id].add(kind)

    def exists(self, ref: SubjectRef) -> bool:
        return ref.kind in self._kinds.get(ref.id, set())

    def known(self, subject_id: str) -> bool:
        return subject_id in self._kinds

    def ref(self, subject_id: str) -> SubjectRef | None:
        """Типизирует id, только если вид однозначен; иначе ссылка не выдумывается."""
        kinds = self._kinds.get(subject_id, set())
        if len(kinds) != 1:
            return None
        return SubjectRef(kind=next(iter(kinds)), id=subject_id)
