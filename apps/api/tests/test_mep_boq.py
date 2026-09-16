"""PROMPT 09: `MepNetworkGraph` → `MepBoq` детерминированно, без модели, изображения и цены."""

from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

import pytest

from app.contracts.mep import MepNetworkGraph, canonical_sha256
from app.contracts.mep.boq import BoqLine, MepBoq
from app.contracts.mep.common import Level, SheetRef
from app.contracts.mep.network import NetworkSegment
from app.services.mep.boq import build_boq
from app.services.mep.network_geometry import segment_length, turn_count
from tests.mep_fixtures import (
    NETWORK,
    PROFILE,
    Json,
    by_id,
    evidence_model,
    load,
    profile_model,
)

RESOLVED = load("network_graph_resolved.v0.3.json")
SERVICES = Path(__file__).resolve().parents[1] / "app" / "services" / "mep"


def _boq(data: Json, *, evidence: bool = True) -> MepBoq:
    graph = MepNetworkGraph.model_validate(data)
    return build_boq(graph, profile_model(), evidence_model() if evidence else None)


def _lines(boq: MepBoq, rule: str) -> list[BoqLine]:
    return [line for line in boq.lines if line.rule_id == rule]


def _group(line: BoqLine) -> dict[str, Any]:
    return {attribute.key: attribute.value for attribute in line.group}


def _codes(boq: MepBoq) -> set[str]:
    return {blocker.code.value for blocker in boq.blockers if blocker.severity == "blocker"}


def _length(boq: MepBoq, size: int) -> BoqLine:
    return next(
        line
        for line in _lines(boq, "mep.segment_length.v0")
        if _group(line)["syn.nominal_size_mm"] == size
    )


class TestGolden:
    @pytest.mark.parametrize(
        ("network", "golden"),
        [
            ("network_graph_resolved.v0.3.json", "boq_resolved.v0.3.json"),
            ("network_graph.v0.3.json", "boq_blocked.v0.3.json"),
        ],
    )
    def test_matches_published_example(self, network: str, golden: str) -> None:
        assert _boq(load(network)).model_dump(mode="json") == load(golden)

    def test_resolved_network_is_complete(self) -> None:
        boq = _boq(RESOLVED)

        assert boq.status == "complete"
        assert str(_length(boq, 50).quantity) == "21.025"
        assert str(_length(boq, 32).quantity) == "48.990"
        assert [str(line.quantity) for line in _lines(boq, "mep.node_count.v0")] == ["2"]

    def test_unresolved_material_blocks_lengths_but_not_counts(self) -> None:
        boq = _boq(NETWORK)

        assert boq.status == "partial"
        assert not _lines(boq, "mep.segment_length.v0")
        assert {"PARAMETER_UNRESOLVED", "DECISION_BLOCKS_QUANTITY"} <= _codes(boq)
        assert _lines(boq, "mep.node_count.v0")[0].source_ids == ("n-t1", "n-t2")


class TestDeterminism:
    def test_repeatable(self) -> None:
        first, second = _boq(RESOLVED), _boq(RESOLVED)

        assert canonical_sha256(first) == canonical_sha256(second)

    def test_input_order_does_not_matter(self) -> None:
        shuffled = copy.deepcopy(RESOLVED)
        for key in ("nodes", "segments", "systems"):
            shuffled[key] = list(reversed(shuffled[key]))

        a, b = _boq(RESOLVED), _boq(shuffled)

        assert (a.lines, a.blockers) == (b.lines, b.blockers)

    def test_engine_uses_no_model_image_or_price_code(self) -> None:
        forbidden = ("torch", "openai", "anthropic", "cv2", "PIL", "transformers", "httpx")
        sources = "\n".join(p.read_text(encoding="utf-8") for p in SERVICES.glob("*.py"))

        assert not [name for name in forbidden if f"import {name}" in sources]

    def test_boq_has_no_price_fields(self) -> None:
        schema = json.dumps(MepBoq.model_json_schema()).lower()

        assert not [w for w in ("price", "cost", "rate", "amount", "currency") if w in schema]


class TestQuantities:
    def test_length_matches_independent_formula(self) -> None:
        snapshot = RESOLVED["sheets"][0]["calibration"]
        width, height = float(snapshot["display_width_pt"]), float(snapshot["display_height_pt"])
        factor = float(snapshot["mm_per_pt"])
        expected = 0.0
        for segment_id in ("seg-b1", "seg-b2"):
            path = by_id(RESOLVED["segments"], segment_id)["path"]
            for a, b in pairwise(path):
                expected += math.hypot((b["x"] - a["x"]) * width, (b["y"] - a["y"]) * height)

        actual = float(_length(_boq(RESOLVED), 32).canonical_quantity)

        assert actual == pytest.approx(expected * factor, abs=0.001)

    def test_diameter_split_keeps_sources(self) -> None:
        boq = _boq(RESOLVED)

        assert _length(boq, 50).source_ids == ("seg-main",)
        assert _length(boq, 32).source_ids == ("seg-b1", "seg-b2")

    def test_no_element_is_counted_twice(self) -> None:
        boq = _boq(RESOLVED)
        for rule in ("mep.segment_length.v0", "mep.node_count.v0"):
            sources = [s for line in _lines(boq, rule) for s in line.source_ids]
            assert len(sources) == len(set(sources))

    def test_turns_branches_and_parameter_changes(self) -> None:
        boq = _boq(RESOLVED)
        turns = _lines(boq, "mep.path_turns.v0")
        (branch,) = _lines(boq, "mep.branch_nodes.v0")
        (change,) = _lines(boq, "mep.parameter_change.v0")

        assert [(str(t.quantity), _group(t)["syn.nominal_size_mm"]) for t in turns] == [("2", 32)]
        assert (_group(branch), branch.source_ids) == ({"core.degree": 3}, ("n-j1",))
        assert _group(change) == {"core.parameter": "syn.nominal_size_mm", "core.values": "32|50"}

    def test_collinear_vertex_is_not_a_turn(self) -> None:
        data = copy.deepcopy(RESOLVED)
        path = by_id(data["segments"], "seg-main")["path"]
        path.insert(1, path[0] | {"x": 0.3})

        boq = _boq(data)

        assert _length(boq, 50).quantity == _length(_boq(RESOLVED), 50).quantity
        assert [_group(t)["syn.nominal_size_mm"] for t in _lines(boq, "mep.path_turns.v0")] == [32]

    def test_class_without_quantity_rule_is_not_counted(self) -> None:
        counted = {
            s for line in _boq(RESOLVED).lines if line.category == "count" for s in line.source_ids
        }

        assert "n-j1" not in counted and "n-src" not in counted

    def test_provenance_reaches_the_line(self) -> None:
        boq = _boq(RESOLVED)
        inferred = {p.provenance.value for p in _length(boq, 32).provenance}
        (terminals,) = _lines(boq, "mep.node_count.v0")

        assert {"deterministic_rule", "rd_prior_inferred"} <= inferred
        assert _length(boq, 32).review_required
        assert not terminals.review_required
        assert terminals.min_confidence == 0.41


class TestBlockers:
    def test_no_metric_quantity_without_scale(self) -> None:
        data = copy.deepcopy(RESOLVED)
        sheet = data["sheets"][0]
        sheet.update(scale_status="uncalibrated", scale_calibration_id=None)
        sheet.pop("calibration")

        boq = _boq(data, evidence=False)

        assert not _lines(boq, "mep.segment_length.v0")
        assert "NO_SCALE" in _codes(boq)
        assert _lines(boq, "mep.node_count.v0")

    def test_missing_parameter_is_not_inferred(self) -> None:
        data = copy.deepcopy(RESOLVED)
        segment = by_id(data["segments"], "seg-b2")
        segment["parameters"] = [
            p for p in segment["parameters"] if p["key"] != "syn.nominal_size_mm"
        ]

        boq = _boq(data)

        assert "PARAMETER_MISSING" in _codes(boq)
        assert _length(boq, 32).source_ids == ("seg-b1",)

    def test_invalid_network_is_refused(self) -> None:
        data = copy.deepcopy(RESOLVED)
        by_id(data["segments"], "seg-b2")["start"]["port_id"] = "p-j1-o1"

        boq = _boq(data)

        assert (boq.status, boq.lines, _codes(boq)) == ("refused", (), {"NETWORK_INVALID"})

    def test_edited_profile_is_refused(self) -> None:
        edited = copy.deepcopy(PROFILE)
        edited["title"] = "Правка без новой версии"
        graph = MepNetworkGraph.model_validate(RESOLVED)

        assert build_boq(graph, profile_model(edited)).status == "refused"

    def test_topology_is_not_mapped_to_fittings(self) -> None:
        warnings = {b.code.value for b in _boq(RESOLVED).blockers if b.severity == "warning"}

        assert "FITTING_RULES_NOT_APPROVED" in warnings


class TestGraphDelta:
    def test_longer_branch_changes_only_its_line(self) -> None:
        data = copy.deepcopy(RESOLVED)
        by_id(data["nodes"], "n-t1")["position"]["x"] = 0.7
        by_id(data["segments"], "seg-b1")["path"][-1]["x"] = 0.7
        snapshot = RESOLVED["sheets"][0]["calibration"]
        delta_mm = Decimal(repr(0.1 * float(snapshot["display_width_pt"]))) * Decimal(
            snapshot["mm_per_pt"]
        )
        before, after = _boq(RESOLVED), _boq(data)

        grown = after.lines and _length(after, 32).canonical_quantity
        assert float(grown) - float(_length(before, 32).canonical_quantity) == pytest.approx(
            float(delta_mm), abs=0.002
        )
        assert _length(after, 50) == _length(before, 50)

    def test_extra_terminal_adds_count_and_branch_degree(self) -> None:
        data = copy.deepcopy(RESOLVED)
        junction = by_id(data["nodes"], "n-j1")
        junction["ports"].append({"id": "p-j1-o3", "direction": "out", "system_id": "sys-1"})
        terminal = copy.deepcopy(by_id(data["nodes"], "n-t2"))
        terminal.update(id="n-t3")
        terminal["position"] = terminal["position"] | {"x": 0.3, "y": 0.7}
        terminal["ports"] = [{"id": "p-t3-in", "direction": "in", "system_id": "sys-1"}]
        data["nodes"].append(terminal)
        branch = copy.deepcopy(by_id(data["segments"], "seg-b2"))
        branch.update(id="seg-b3")
        branch["start"] = {"node_id": "n-j1", "port_id": "p-j1-o3"}
        branch["end"] = {"node_id": "n-t3", "port_id": "p-t3-in"}
        branch["path"] = [
            branch["path"][0],
            branch["path"][1] | {"x": 0.3, "y": 0.5},
            terminal["position"],
        ]
        data["segments"].append(branch)

        boq = _boq(data)

        assert [str(line.quantity) for line in _lines(boq, "mep.node_count.v0")] == ["3"]
        assert _group(_lines(boq, "mep.branch_nodes.v0")[0]) == {"core.degree": 4}


def _segment(path: list[Json]) -> NetworkSegment:
    return NetworkSegment.model_validate(
        {
            "id": "seg-x",
            "class_key": "syn.net.segment",
            "system_id": "sys-1",
            "start": {"node_id": "a", "port_id": "pa"},
            "end": {"node_id": "b", "port_id": "pb"},
            "path": path,
            "derivation": {"provenance": "rd_prior_inferred", "step_ids": ["st-3"]},
        }
    )


class TestVerticalGeometry:
    SHEETS: ClassVar[dict[str, SheetRef]] = {
        "sheet-p3": SheetRef.model_validate(RESOLVED["sheets"][0])
    }
    LEVELS: ClassVar[dict[str, Level]] = {
        "L01": Level(level_id="L01", name="1", elevation_mm=0),
        "L02": Level(level_id="L02", name="2", elevation_mm=3000),
        "LX": Level(level_id="LX", name="?"),
    }

    def test_vertical_run_between_levels(self) -> None:
        segment = _segment([{"level_id": "L02"}, {"level_id": "L01"}])

        assert segment_length(segment, self.SHEETS, self.LEVELS).millimetres == Decimal("3000")

    def test_inclined_run_combines_plan_and_rise(self) -> None:
        plan = [
            {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5},
            {"sheet_id": "sheet-p3", "x": 0.3, "y": 0.5},
        ]
        flat = segment_length(_segment(plan), self.SHEETS, self.LEVELS).millimetres
        rising = _segment([plan[0] | {"z_mm": 0}, plan[1] | {"z_mm": 500}])
        length = segment_length(rising, self.SHEETS, self.LEVELS).millimetres

        assert flat is not None and length is not None
        assert float(length) == pytest.approx(math.hypot(float(flat), 500), abs=1e-6)

    def test_riser_then_horizontal_is_one_turn(self) -> None:
        path = [
            {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5, "z_mm": 3000},
            {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5, "z_mm": 0},
            {"sheet_id": "sheet-p3", "x": 0.3, "y": 0.5, "z_mm": 0},
        ]

        assert turn_count(_segment(path), self.SHEETS, self.LEVELS) == 1

    @pytest.mark.parametrize(
        ("path", "code"),
        [
            ([{"level_id": "L01"}, {"level_id": "LX"}], "ELEVATION_INCOMPLETE"),
            ([{"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5}, {"z_mm": 100}], "LENGTH_UNDETERMINED"),
            (
                [
                    {"sheet_id": "sheet-p3", "x": 0.2, "y": 0.5},
                    {"sheet_id": "sheet-p9", "x": 0.2, "y": 0.6},
                ],
                "CROSS_SHEET_PLANAR",
            ),
        ],
    )
    def test_undetermined_length_is_a_blocker(self, path: list[Json], code: str) -> None:
        result = segment_length(_segment(path), self.SHEETS, self.LEVELS)

        assert (result.millimetres, result.blocker) == (None, code)
