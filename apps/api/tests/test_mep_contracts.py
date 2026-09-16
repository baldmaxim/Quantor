"""Контракты MEP v0.3: разбор, смысловые проверки, разделение observed и generated."""

from __future__ import annotations

import copy
import json
from enum import StrEnum

import pytest
from pydantic import ValidationError

from app.contracts.mep import (
    MepSystemProfile,
    canonical_sha256,
    common,
    evidence,
    network,
    profile,
    validate_evidence_graph,
    validate_network_graph,
    validate_profile,
)
from app.contracts.mep.schemas import SCHEMA_FILES
from tests.mep_fixtures import DOCS, EVIDENCE, NETWORK, PROFILE
from tests.mep_fixtures import by_id as _by_id
from tests.mep_fixtures import element as _element
from tests.mep_fixtures import errors as _errors
from tests.mep_fixtures import evidence_model as _evidence
from tests.mep_fixtures import network_model as _network
from tests.mep_fixtures import profile_model as _profile
from tests.mep_fixtures import rehash as _rehash
from tests.mep_fixtures import warnings as _warnings


class TestExamples:
    def test_examples_are_valid(self) -> None:
        profile_model, evidence_model = _profile(), _evidence()
        network_model = _network(NETWORK)

        assert validate_profile(profile_model) == []
        assert validate_evidence_graph(evidence_model, profile_model) == []
        assert validate_network_graph(network_model, evidence_model, profile_model) == []

    @pytest.mark.parametrize("name", sorted(SCHEMA_FILES))
    def test_published_schema_matches_models(self, name: str) -> None:
        """JSON Schema генерируется из моделей: `python -m app.contracts.mep.schemas`."""
        published = json.loads((DOCS / "schemas" / name).read_text(encoding="utf-8"))
        published.pop("$schema")

        assert published == SCHEMA_FILES[name].model_json_schema()

    def test_hash_does_not_depend_on_key_order(self) -> None:
        reordered = dict(reversed(list(EVIDENCE.items())))

        assert canonical_sha256(_evidence(reordered)) == canonical_sha256(_evidence())


class TestCoreIsDisciplineAgnostic:
    FORBIDDEN = ("sink", "toilet", "riser", "radiator", "diffuser", "valve", "pipe", "duct")

    def test_core_enums_carry_no_discipline_classes(self) -> None:
        values = [
            member.value.lower()
            for module in (common, evidence, network, profile)
            for item in vars(module).values()
            if isinstance(item, type) and issubclass(item, StrEnum) and item is not StrEnum
            for member in item
        ]

        assert not [v for v in values if any(word in v for word in self.FORBIDDEN)]


class TestEvidenceStructure:
    @pytest.mark.parametrize("field", ["provenance", "status"])
    def test_generator_origin_cannot_enter_evidence(self, field: str) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-src-1")[field] = "rd_prior_inferred"

        with pytest.raises(ValidationError):
            _evidence(data)

    def test_unknown_field_is_rejected(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-src-1")["generated_by"] = "gen"

        with pytest.raises(ValidationError):
            _evidence(data)

    def test_coordinates_stay_on_the_page(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-src-1")["geometry"]["point"] = [1.2, 0.5]

        with pytest.raises(ValidationError):
            _evidence(data)

    def test_inverted_box_is_rejected(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-sym-3")["geometry"] = {
            "kind": "bbox",
            "min": [0.9, 0.5],
            "max": [0.8, 0.6],
        }

        with pytest.raises(ValidationError):
            _evidence(data)

    def test_element_needs_a_source(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-src-1")["sources"] = []

        with pytest.raises(ValidationError):
            _evidence(data)


class TestEvidenceSemantics:
    def test_model_extracted_graph_has_no_human_ground_truth(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        element = _element(data, "ev-term-1")
        element.update(
            provenance="human_ground_truth", status="human_confirmed", review="confirmed"
        )
        element["sources"] = [{"source_type": "human_annotation", "ref_id": "ann-1"}]

        assert "INPUT_MODE_CONFLICT" in _errors(validate_evidence_graph(_evidence(data)))

    def test_human_gt_graph_contains_only_human_markup(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["input_mode"] = "HUMAN_GT"

        assert "INPUT_MODE_CONFLICT" in _errors(validate_evidence_graph(_evidence(data)))

    def test_human_confirmation_requires_review(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["input_mode"] = "HYBRID_REVIEWED"
        _element(data, "ev-term-1")["status"] = "human_confirmed"

        assert "HUMAN_CONFIRMED_NOT_REVIEWED" in _errors(validate_evidence_graph(_evidence(data)))

    def test_relation_to_missing_element(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["relations"][0]["to_id"] = "ev-missing"

        assert "RELATION_MISSING_ENDPOINT" in _errors(validate_evidence_graph(_evidence(data)))

    def test_measured_attribute_requires_calibration(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["sheets"][0]["scale_status"] = "uncalibrated"
        _element(data, "ev-route-1")["attributes"][0]["derivation"] = "measured"

        assert "METRIC_WITHOUT_SCALE" in _errors(validate_evidence_graph(_evidence(data)))

    def test_unavailable_text_layer_is_not_a_source(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["source_availability"][1]["availability"] = "unavailable"

        assert "SOURCE_UNAVAILABLE" in _errors(validate_evidence_graph(_evidence(data)))

    def test_unavailable_text_layer_alone_is_not_an_error(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["source_availability"][1]["availability"] = "unavailable"
        data["elements"] = [e for e in data["elements"] if e["kind"] != "text"]
        data["relations"] = [r for r in data["relations"] if r["id"] == "rel-3"]
        for element in data["elements"]:
            element["attributes"] = []

        assert validate_evidence_graph(_evidence(data), _profile()) == []

    def test_attribute_is_read_from_text(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-src-1")["attributes"][0]["source_element_ids"] = ["ev-term-1"]

        assert "ATTRIBUTE_SOURCE_NOT_TEXT" in _errors(validate_evidence_graph(_evidence(data)))

    def test_unresolved_class_needs_a_reason(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-sym-3")["unresolved"] = []

        assert "CLASS_UNRESOLVED_WITHOUT_REASON" in _errors(
            validate_evidence_graph(_evidence(data))
        )

    def test_model_element_names_its_tool(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-term-1")["sources"][0].pop("tool_id")

        assert "MISSING_TOOL" in _errors(validate_evidence_graph(_evidence(data)))

    def test_profile_governs_classes_and_geometry(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-term-1")["class_key"] = "syn.ev.unknown"
        _element(data, "ev-term-2")["geometry"] = {
            "kind": "polyline",
            "points": [[0.6, 0.7], [0.62, 0.7]],
        }

        found = _errors(validate_evidence_graph(_evidence(data), _profile()))

        assert {"UNKNOWN_CLASS", "GEOMETRY_NOT_ALLOWED"} <= found


class TestNetworkProvenance:
    def test_observed_element_points_to_evidence(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["nodes"], "n-t1")["derivation"]["evidence_ids"] = []

        found = _errors(validate_network_graph(_network(data), _evidence(), _profile()))

        assert "OBSERVED_WITHOUT_EVIDENCE" in found

    def test_inferred_element_points_to_a_step(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["nodes"], "n-j1")["derivation"]["step_ids"] = []

        assert "INFERRED_WITHOUT_STEP" in _errors(validate_network_graph(_network(data)))

    def test_retrieved_pattern_names_the_train_case(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["inference_steps"], "st-2")["retrieved_case_ids"] = []

        assert "MISSING_RULE_OR_CASE" in _errors(validate_network_graph(_network(data)))

    def test_changed_evidence_breaks_the_link(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        _element(data, "ev-term-2")["confidence"] = 0.99

        found = _errors(validate_network_graph(_network(NETWORK), _evidence(data)))

        assert "EVIDENCE_GRAPH_MISMATCH" in found

    def test_unknown_evidence_reference(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["nodes"], "n-t1")["derivation"]["evidence_ids"] = ["ev-invented"]

        found = _errors(validate_network_graph(_network(data), _evidence()))

        assert "UNKNOWN_EVIDENCE" in found

    def test_rejected_evidence_is_not_adopted(self) -> None:
        evidence_data = copy.deepcopy(EVIDENCE)
        _element(evidence_data, "ev-term-2")["review"] = "rejected"
        evidence_model = _evidence(evidence_data)
        data = _rehash(copy.deepcopy(NETWORK), evidence_model)

        found = _errors(validate_network_graph(_network(data), evidence_model))

        assert "EVIDENCE_REJECTED" in found

    def test_steps_only_use_earlier_steps(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["inference_steps"], "st-1")["input_step_ids"] = ["st-3"]

        assert "STEP_ORDER" in _errors(validate_network_graph(_network(data)))

    def test_value_is_absent_only_when_unresolved(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["segments"], "seg-main")["parameters"][1]["value"] = "steel"

        with pytest.raises(ValidationError):
            _network(data)


class TestNetworkTopology:
    def test_cross_system_connection(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["systems"].append(copy.deepcopy(data["systems"][0]) | {"id": "sys-2"})
        _by_id(data["nodes"], "n-t1")["ports"][0]["system_id"] = "sys-2"

        assert "CROSS_SYSTEM_CONNECTION" in _errors(validate_network_graph(_network(data)))

    def test_disconnected_terminal(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["segments"] = [s for s in data["segments"] if s["id"] != "seg-b2"]

        assert "DISCONNECTED_NODE" in _errors(validate_network_graph(_network(data)))

    def test_disconnected_terminal_under_decision_is_a_warning(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["segments"] = [s for s in data["segments"] if s["id"] != "seg-b2"]
        data["unresolved"].append(
            {"id": "ud-2", "code": "ambiguous_connection", "subject_ids": ["n-t2"]}
        )

        found = validate_network_graph(_network(data))

        assert "DISCONNECTED_NODE" in _warnings(found)
        assert "DISCONNECTED_NODE" not in _errors(found)

    def test_port_takes_one_connection(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["segments"], "seg-b2")["start"]["port_id"] = "p-j1-o1"

        assert "PORT_OVER_CONNECTED" in _errors(validate_network_graph(_network(data)))

    def test_tree_system_rejects_cycle(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["nodes"], "n-t1")["ports"].append({"id": "p-t1-out", "system_id": "sys-1"})
        _by_id(data["nodes"], "n-src")["ports"].append({"id": "p-src-2", "system_id": "sys-1"})
        loop = copy.deepcopy(_by_id(data["segments"], "seg-main")) | {"id": "seg-loop"}
        loop["start"] = {"node_id": "n-t1", "port_id": "p-t1-out"}
        loop["end"] = {"node_id": "n-src", "port_id": "p-src-2"}
        data["segments"].append(loop)

        found = _errors(validate_network_graph(_network(data), profile=_profile()))

        assert "CYCLE_IN_TREE_SYSTEM" in found

    def test_uncalibrated_sheet_blocks_quantity(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["sheets"][0]["scale_status"] = "uncalibrated"

        assert "QUANTITY_BLOCKED_NO_SCALE" in _warnings(validate_network_graph(_network(data)))


class TestDimensions:
    def test_planar_point_needs_a_sheet(self) -> None:
        with pytest.raises(ValidationError):
            network.Vertex(x=0.5, y=0.5)

    def test_vertical_transition_between_levels(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["levels"].append({"level_id": "L02", "name": "Этаж 2", "elevation_mm": 3000})
        node = _by_id(data["nodes"], "n-src")
        node["ports"].append({"id": "p-src-up", "direction": "in", "system_id": "sys-1"})
        upper = {
            "id": "n-up",
            "role": "transition",
            "class_key": None,
            "system_ids": ["sys-1"],
            "position": {"z_mm": 3000, "level_id": "L02"},
            "ports": [{"id": "p-up-down", "direction": "out", "system_id": "sys-1"}],
            "derivation": {"provenance": "rd_prior_inferred", "step_ids": ["st-3"]},
        }
        data["nodes"].append(upper)
        data["segments"].append(
            {
                "id": "seg-vertical",
                "class_key": "syn.net.segment",
                "system_id": "sys-1",
                "start": {"node_id": "n-up", "port_id": "p-up-down"},
                "end": {"node_id": "n-src", "port_id": "p-src-up"},
                "path": [
                    {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5, "z_mm": 3000, "level_id": "L02"},
                    {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5, "z_mm": 0, "level_id": "L01"},
                ],
                "orientation": "vertical",
                "derivation": {"provenance": "rd_prior_inferred", "step_ids": ["st-3"]},
            }
        )
        data["unresolved"].append(
            {"id": "ud-3", "code": "missing_evidence", "subject_ids": ["n-up"]}
        )

        found = validate_network_graph(_network(data), profile=_profile())

        assert _errors(found) == set()

    def test_vertical_segment_needs_elevation(self) -> None:
        data = copy.deepcopy(NETWORK)
        _by_id(data["segments"], "seg-main")["orientation"] = "vertical"

        assert "VERTICAL_WITHOUT_ELEVATION" in _errors(validate_network_graph(_network(data)))


class TestProfile:
    def test_evidence_class_declares_kind_and_geometry(self) -> None:
        with pytest.raises(ValidationError):
            profile.ClassDef(key="syn.bad", label="bad", layer="evidence")

    def test_node_class_declares_roles(self) -> None:
        with pytest.raises(ValidationError):
            profile.ClassDef(key="syn.bad", label="bad", layer="network", network_element="node")

    def test_class_attributes_are_described(self) -> None:
        data = copy.deepcopy(PROFILE)
        data["classes"][0]["attribute_keys"] = ["syn.undescribed"]

        found = _errors(validate_profile(MepSystemProfile.model_validate(data)))

        assert "UNKNOWN_ATTRIBUTE" in found
