"""Проёмы: двери в разрыве стены, одна сторона, разрыв без двери."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tests import synth

Doc = dict[str, object]


def _openings(doc: Doc) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], doc["openings"])


def _by_id(doc: Doc) -> dict[str, dict[str, object]]:
    return {str(c["id"]): c for c in cast(list[dict[str, object]], doc["constructions"])}


def _f(value: object) -> float:
    assert isinstance(value, int | float)
    return float(value)


def test_door_in_gap_of_two_walls(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 2900, 0, 5000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_001", 2000, -400, 2900, 500)
    out = synth.run(tmp_path, doc)
    (op,) = _openings(out)
    assert (op["kind"], op["status"], op["width_source"]) == ("door", "ok", "gap")
    assert _f(op["width_mm"]) == pytest.approx(900, abs=2)
    assert op["thickness_mm"] == 100
    assert op["block_name"] == "AR_DOOR_BLOCK_001"
    assert op["handle"]
    cons = _by_id(out)
    assert op["host_id"] in cons
    assert sorted(cast(list[str], op["adjacent_ids"])) == sorted(cons)


def test_door_host_is_thicker_wall(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 80)
    synth.add_rect(msp, synth.MASONRY, 2900, -60, 5000, 140)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_002", 2000, -400, 2900, 500)
    out = synth.run(tmp_path, doc)
    (op,) = _openings(out)
    host = _by_id(out)[str(op["host_id"])]
    assert host["thickness_nominal_mm"] == 200
    assert op["thickness_mm"] == 200
    assert len(cast(list[str], op["adjacent_ids"])) == 2


def test_door_with_one_side_uses_block_bbox(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_003", 2000, -400, 2950, 500)
    out = synth.run(tmp_path, doc)
    (op,) = _openings(out)
    assert (op["kind"], op["status"], op["width_source"]) == ("door", "estimate", "block_bbox")
    assert _f(op["width_mm"]) == pytest.approx(950, abs=1)
    assert op["host_id"] in _by_id(out)


def test_gap_without_door(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 3500, 0, 5500, 100)
    out = synth.run(tmp_path, doc)
    (op,) = _openings(out)
    assert (op["kind"], op["status"], op["width_source"]) == ("gap", "no_data", "gap")
    assert _f(op["width_mm"]) == pytest.approx(1500, abs=2)
    assert op["block_name"] is None
    assert op["handle"] is None
    assert len(cast(list[str], op["adjacent_ids"])) == 2


def test_far_gap_is_not_opening(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 6000, 0, 8000, 100)
    assert _openings(synth.run(tmp_path, doc)) == []


def test_gap_between_different_nominals_is_not_opening(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 3000, -50, 5000, 150)
    assert _openings(synth.run(tmp_path, doc)) == []
