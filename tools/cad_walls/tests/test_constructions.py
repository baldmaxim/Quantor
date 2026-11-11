"""Разбиение заливки на конструкции: толщины, номиналы, виды, площади."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tests import synth

Doc = dict[str, object]


def _cons(doc: Doc) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], doc["constructions"])


def _totals(doc: Doc) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], doc["totals"])


def _checks(doc: Doc) -> dict[str, object]:
    return cast(dict[str, object], doc["checks"])


def _f(value: object) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _assert_area_matches(doc: Doc, expected: float) -> None:
    checks = _checks(doc)
    assert _f(checks["area_union_mm2"]) == pytest.approx(expected, rel=1e-3)
    assert _f(checks["area_constructions_mm2"]) == pytest.approx(expected, rel=1e-3)
    assert _f(checks["residue_ratio"]) <= 1e-3
    assert checks["warnings"] == []


def test_straight_wall_100(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 3000, 100)
    out = synth.run(tmp_path, doc)
    (c,) = _cons(out)
    assert c["kind"] == "masonry"
    assert c["thickness_nominal_mm"] == 100
    assert c["thickness_status"] == "matched"
    assert _f(c["thickness_measured_mm"]) == pytest.approx(100, abs=0.5)
    assert _f(c["area_plan_mm2"]) == pytest.approx(300_000, abs=1)
    assert _f(c["length_axis_mm"]) == pytest.approx(3000, abs=5)
    assert c["source_layers"] == [synth.MASONRY]
    assert c["bbox"] == [0.0, 0.0, 3000.0, 100.0]
    _assert_area_matches(out, 300_000)


def test_l_shaped_wall_80(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    poly = synth.add_union(msp, synth.MASONRY, (0, 0, 2000, 80), (0, 0, 80, 1500))
    out = synth.run(tmp_path, doc)
    cons = _cons(out)
    (c,) = cons
    assert c["thickness_nominal_mm"] == 80
    assert _f(c["length_axis_mm"]) == pytest.approx(poly.area / 80, rel=0.01)
    _assert_area_matches(out, poly.area)


def test_t_junction_200_and_100(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    poly = synth.add_union(msp, synth.MASONRY, (0, 0, 3000, 200), (1400, 200, 1500, 1800))
    out = synth.run(tmp_path, doc)
    _assert_area_matches(out, poly.area)
    by_nominal = {t["thickness_nominal_mm"]: t for t in _totals(out)}
    assert set(by_nominal) == {100, 200}
    # ножка 100 x 1600 целиком, остальное — стена 200 (узел отдан более толстой)
    assert _f(by_nominal[100]["area_plan_mm2"]) == pytest.approx(160_000, rel=0.02)
    assert _f(by_nominal[200]["area_plan_mm2"]) == pytest.approx(600_000, rel=0.02)
    # стена 200 проходит через Т насквозь — одна конструкция
    assert [c["thickness_nominal_mm"] for c in _cons(out)].count(200) == 1


def test_t_and_cross_junction_same_thickness_is_one_construction(tmp_path: Path) -> None:
    for name, boxes in (
        ("t", [(0, 0, 3000, 100), (1450, 100, 1550, 1900)]),
        ("cross", [(0, 900, 3000, 1000), (1450, 0, 1550, 1900)]),
    ):
        doc, msp = synth.new_doc()
        poly = synth.add_union(msp, synth.MASONRY, *boxes)
        (tmp_path / name).mkdir()
        out = synth.run(tmp_path / name, doc)
        (c,) = _cons(out)
        assert c["thickness_nominal_mm"] == 100
        _assert_area_matches(out, poly.area)


def test_u_shaped_monolith_shaft_wall_200_is_one_wall(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    poly = synth.add_union(
        msp, synth.MONOLITH, (0, 0, 1500, 200), (0, 0, 200, 1200), (1300, 0, 1500, 1200)
    )
    out = synth.run(tmp_path, doc)
    (c,) = _cons(out)
    assert c["kind"] == "monolith_wall"
    assert c["thickness_nominal_mm"] == 200
    assert _f(c["area_plan_mm2"]) == pytest.approx(poly.area, rel=1e-3)
    _assert_area_matches(out, poly.area)


def test_coaxial_step_80_to_200(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    poly = synth.add_union(msp, synth.MASONRY, (0, 0, 2000, 80), (2000, -60, 4000, 140))
    out = synth.run(tmp_path, doc)
    cons = _cons(out)
    assert sorted(_f(c["thickness_nominal_mm"]) for c in cons) == [80, 200]
    _assert_area_matches(out, poly.area)


def test_thickness_137_is_check(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 137)
    out = synth.run(tmp_path, doc)
    (c,) = _cons(out)
    assert c["thickness_nominal_mm"] is None
    assert c["thickness_status"] == "check"
    assert _f(c["thickness_measured_mm"]) == pytest.approx(137, abs=0.5)
    assert _totals(out)[0]["thickness_nominal_mm"] is None


def test_hatch_with_hole(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    outer = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
    hole = [(200, 200), (800, 200), (800, 800), (200, 800)]
    synth.add_hatch(msp, synth.MASONRY, outer, [hole])
    out = synth.run(tmp_path, doc)
    expected = 1_000_000 - 360_000
    _assert_area_matches(out, expected)
    assert all(c["thickness_nominal_mm"] == 200 for c in _cons(out))
    assert sum(_f(c["area_plan_mm2"]) for c in _cons(out)) == pytest.approx(expected, rel=1e-3)


def test_ring_wall_100_closed_chain(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    outer = [(0, 0), (3000, 0), (3000, 2000), (0, 2000)]
    hole = [(100, 100), (2900, 100), (2900, 1900), (100, 1900)]
    synth.add_hatch(msp, synth.MASONRY, outer, [hole])
    out = synth.run(tmp_path, doc)
    _assert_area_matches(out, 3000 * 2000 - 2800 * 1800)
    (c,) = _cons(out)
    assert c["thickness_nominal_mm"] == 100


def test_round_end_edge_path_with_arc(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_round_end_wall(msp, synth.MASONRY, 1000, 200)
    out = synth.run(tmp_path, doc)
    checks = _checks(out)
    assert _f(checks["area_union_mm2"]) == pytest.approx(synth.arc_area(1000, 200), rel=0.005)
    assert all(c["thickness_nominal_mm"] == 200 for c in _cons(out))


def test_monolith_shapes(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MONOLITH, 0, 0, 400, 400)
    synth.add_rect(msp, synth.MONOLITH, 2000, 0, 2250, 900)
    synth.add_rect(msp, synth.MONOLITH, 4000, 0, 8000, 200)
    out = synth.run(tmp_path, doc)
    kinds = {(c["kind"], c["thickness_nominal_mm"]) for c in _cons(out)}
    assert kinds == {
        ("monolith_column", 400),
        ("monolith_pylon", 250),
        ("monolith_wall", 200),
    }
    assert {t["kind"] for t in _totals(out)} == {
        "monolith_column",
        "monolith_pylon",
        "monolith_wall",
    }


def test_masonry_monolith_overlap_goes_to_monolith(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 200)
    synth.add_rect(msp, synth.MONOLITH, 1500, 0, 2500, 200)
    out = synth.run(tmp_path, doc)
    codes = [w["code"] for w in cast(list[dict[str, str]], _checks(out)["warnings"])]
    assert "masonry_monolith_overlap" in codes
    total = {t["kind"]: _f(t["area_plan_mm2"]) for t in _totals(out)}
    assert total["masonry"] == pytest.approx(1500 * 200, abs=1)
    assert total["monolith_wall"] == pytest.approx(1000 * 200, abs=1)


def test_ids_are_stable_and_unique(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 0, 1000, 2000, 1100)
    first = [c["id"] for c in _cons(synth.run(tmp_path, doc))]
    second = [c["id"] for c in _cons(synth.run(tmp_path, doc))]
    assert first == second
    assert len(set(first)) == 2


def test_empty_dxf_warns(tmp_path: Path) -> None:
    doc, _ = synth.new_doc()
    out = synth.run(tmp_path, doc)
    assert _cons(out) == []
    codes = [w["code"] for w in cast(list[dict[str, str]], _checks(out)["warnings"])]
    assert codes == ["no_fill", "slab_missing"]
