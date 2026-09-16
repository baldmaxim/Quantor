"""PROMPT 11.1: вклад источников, происхождение группы, участники, типизированные ссылки."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts.mep import MepNetworkGraph, SubjectRef, validate_network_graph
from app.contracts.mep.boq import BoqLine, MepBoq
from app.contracts.mep.boq_validation import validate_boq
from app.contracts.mep.common import Level
from app.services.mep import scenarios as scenarios_service
from app.services.mep.boq import build_boq
from app.services.mep.boq_lines import allocate
from app.services.mep.network_geometry import segment_length
from tests.mep_fixtures import NETWORK, Json, by_id, errors, evidence_model, load, profile_model

RESOLVED = load("network_graph_resolved.v0.3.json")


def _boq(data: Json) -> MepBoq:
    return build_boq(MepNetworkGraph.model_validate(data), profile_model(), evidence_model())


def _line(boq: MepBoq, rule: str, **group: object) -> BoqLine:
    return next(
        line
        for line in boq.lines
        if line.rule_id == rule
        and all(any(a.key == k and a.value == v for a in line.group) for k, v in group.items())
    )


class TestContributions:
    @pytest.mark.parametrize("scenario", scenarios_service.SCENARIOS, ids=lambda s: s.scenario_id)
    def test_additive_sources_sum_to_the_line(self, scenario: scenarios_service.Scenario) -> None:
        for line in scenarios_service.run(scenario).boq.lines:
            assert line.additive
            assert sum(s.quantity or Decimal(0) for s in line.sources) == line.quantity
            assert (
                sum(s.canonical_quantity or Decimal(0) for s in line.sources)
                == line.canonical_quantity
            )

    def test_contribution_is_the_segment_length(self) -> None:
        graph = MepNetworkGraph.model_validate(RESOLVED)
        sheets = {s.sheet_id: s for s in graph.sheets}
        levels: dict[str, Level] = {}
        line = _line(_boq(RESOLVED), "mep.segment_length.v0", **{"syn.nominal_size_mm": 32})

        for source in line.sources:
            segment = next(s for s in graph.segments if s.id == source.subject.id)
            length = segment_length(segment, sheets, levels).millimetres
            assert length is not None
            assert source.canonical_quantity == length.quantize(Decimal("0.001"))

    def test_source_order_does_not_change_contributions(self) -> None:
        shuffled = copy.deepcopy(RESOLVED)
        for key in ("segments", "nodes"):
            shuffled[key] = list(reversed(shuffled[key]))

        assert [line.sources for line in _boq(RESOLVED).lines] == [
            line.sources for line in _boq(shuffled).lines
        ]

    def test_remainder_goes_to_largest_fraction_then_id(self) -> None:
        raw = {"b": Decimal("0.3334"), "a": Decimal("0.3333"), "c": Decimal("0.3333")}

        parts = allocate(raw, Decimal("1.000"), Decimal("0.001"))

        assert parts == {"a": Decimal("0.333"), "b": Decimal("0.334"), "c": Decimal("0.333")}
        assert sum(parts.values()) == Decimal("1.000")

    def test_line_rejects_contributions_that_do_not_sum(self) -> None:
        line = _line(_boq(RESOLVED), "mep.segment_length.v0", **{"syn.nominal_size_mm": 32})
        data = line.model_dump(mode="json")
        data["sources"][0]["quantity"] = "9.999"

        with pytest.raises(ValidationError, match="не складываются"):
            BoqLine.model_validate(data)


class TestGroupValueProvenance:
    @pytest.mark.parametrize("scenario", scenarios_service.SCENARIOS, ids=lambda s: s.scenario_id)
    def test_group_values_resolve_to_network_parameters(
        self, scenario: scenarios_service.Scenario
    ) -> None:
        result = scenarios_service.run(scenario)
        segments = {s.id: s for s in result.network.segments}

        assert validate_boq(result.boq, result.network, result.evidence) == []
        for line in result.boq.lines:
            if line.rule_id != "mep.segment_length.v0":
                continue
            group = {a.key: a.value for a in line.group}
            for source in line.sources:
                assert {ref.key for ref in source.group_values} == set(group)
                for ref in source.group_values:
                    parameter = next(
                        p for p in segments[ref.subject.id].parameters if p.key == ref.parameter_key
                    )
                    assert parameter.value == group[ref.key]
                    assert parameter.derivation.provenance

    def test_tampered_group_value_is_detected(self) -> None:
        boq = _boq(RESOLVED)
        graph = MepNetworkGraph.model_validate(RESOLVED)
        data = boq.model_dump(mode="json")
        line = next(item for item in data["lines"] if item["rule_id"] == "mep.segment_length.v0")
        line["sources"][0]["group_values"][0]["parameter_key"] = "syn.material"

        found = errors(validate_boq(MepBoq.model_validate(data), graph))

        assert "GROUP_VALUE_MISMATCH" in found


class TestParticipants:
    def test_branch_lists_the_node_and_every_connected_segment(self) -> None:
        (source,) = _line(_boq(RESOLVED), "mep.branch_nodes.v0").sources
        roles = {(p.role, p.subject.kind, p.subject.id) for p in source.participants}

        assert roles == {
            ("anchor", "node", "n-j1"),
            ("connected", "segment", "seg-main"),
            ("connected", "segment", "seg-b1"),
            ("connected", "segment", "seg-b2"),
        }

    def test_parameter_change_names_compared_parameters_and_values(self) -> None:
        (source,) = _line(_boq(RESOLVED), "mep.parameter_change.v0").sources
        compared = {
            (p.subject.id, p.parameter_key, p.value)
            for p in source.participants
            if p.role == "compared"
        }

        assert compared == {
            ("seg-main", "syn.nominal_size_mm", 50),
            ("seg-b1", "syn.nominal_size_mm", 32),
            ("seg-b2", "syn.nominal_size_mm", 32),
        }


class TestTypedReferences:
    @pytest.mark.parametrize(
        "value", [{"kind": "pipe", "id": "seg-b1"}, {"kind": "segment", "id": "seg b1!"}]
    )
    def test_invalid_kind_or_id_is_rejected(self, value: Json) -> None:
        with pytest.raises(ValidationError):
            SubjectRef.model_validate(value)

    def test_wrong_kind_for_an_existing_id(self) -> None:
        boq = _boq(RESOLVED)
        data = boq.model_dump(mode="json")
        data["lines"][0]["sources"][0]["participants"][0]["subject"]["kind"] = "segment"

        found = errors(
            validate_boq(MepBoq.model_validate(data), MepNetworkGraph.model_validate(RESOLVED))
        )

        assert "SUBJECT_KIND_MISMATCH" in found

    def test_blockers_carry_typed_subjects(self) -> None:
        boq = _boq(NETWORK)
        unresolved = [b for b in boq.blockers if b.code == "PARAMETER_UNRESOLVED"]

        assert {(ref.kind, ref.id) for b in unresolved for ref in b.subjects} == {
            ("segment", "seg-main"),
            ("segment", "seg-b1"),
            ("segment", "seg-b2"),
        }

    def test_refusal_types_only_unambiguous_subjects(self) -> None:
        result = scenarios_service.run(
            scenarios_service.find("refused") or scenarios_service.SCENARIOS[0]
        )
        (refusal,) = result.boq.blockers

        assert [(ref.kind, ref.id) for ref in refusal.subjects] == [("sheet", "sheet-p3")]

    def test_unresolved_decision_refs_must_match_ids(self) -> None:
        data = copy.deepcopy(NETWORK)
        decision = by_id(data["unresolved"], "ud-1")
        decision["subjects"][0] = {"kind": "node", "id": "seg-main"}
        graph = MepNetworkGraph.model_validate(data)

        assert "SUBJECT_KIND_MISMATCH" in errors(validate_network_graph(graph))


class TestHybridScenario:
    def test_reviewed_evidence_keeps_prediction_and_correction(self) -> None:
        result = scenarios_service.run(
            scenarios_service.find("hybrid") or scenarios_service.SCENARIOS[0]
        )
        evidence = result.evidence
        route = next(e for e in evidence.elements if e.id == "ev-route-1")
        moved = next(e for e in evidence.elements if e.id == "ev-term-2")

        assert evidence.input_mode == "HYBRID_REVIEWED"
        assert result.evidence_issues == []
        assert route.original is not None and route.original.attributes[0].value == "d63"
        assert route.attributes[0].value == "d50"
        assert moved.original is not None and moved.original.geometry != moved.geometry
        (event,) = moved.review_history
        assert (event.action, event.reviewer_id) == ("correct_geometry", "user-engineer-01")
        assert event.reviewed_at.isoformat() == "2026-09-15T09:42:00+00:00"

    def test_network_and_boq_derive_from_reviewed_evidence(self) -> None:
        result = scenarios_service.run(
            scenarios_service.find("hybrid") or scenarios_service.SCENARIOS[0]
        )
        terminal = next(n for n in result.network.nodes if n.id == "n-t2")
        reviewed = {e.id for e in result.evidence.elements if e.review_history}

        assert result.network.evidence_graph.input_mode == "HYBRID_REVIEWED"
        assert result.network_issues == []
        assert set(terminal.derivation.evidence_ids) <= reviewed
        assert result.boq.status == "complete"
        assert any("n-t2" in line.source_ids for line in result.boq.lines)
