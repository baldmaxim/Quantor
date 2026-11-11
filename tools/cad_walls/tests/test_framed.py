"""Каркасные перегородки C112: слои 07_C112_*, склейка штриховок, id."""

from __future__ import annotations

from pathlib import Path

import pytest
from ezdxf.document import Drawing
from ezdxf.layouts.layout import Modelspace

from cad_walls.constructions import Construction
from cad_walls.framed import KIND, extract_frame_partitions
from cad_walls.params import load_params
from tests import synth

SHEATHING = "07_C112_ОБШИВКИ_ГКЛВ"
FRAME = "07_C112_КАРКАСНАЯ_ЗОНА_50"
OTHER = "08_ПРОЧЕЕ"


def _partition(msp: Modelspace, y0: float, length: float = 3000.0) -> None:
    """Перегородка 100 мм: обшивка 25 + каркасная зона 50 + обшивка 25 (три штриховки)."""
    synth.add_rect(msp, SHEATHING, 0, y0, length, y0 + 25)
    synth.add_rect(msp, FRAME, 0, y0 + 25, length, y0 + 75)
    synth.add_rect(msp, SHEATHING, 0, y0 + 75, length, y0 + 100)


def _doc() -> Drawing:
    doc, msp = synth.new_doc()
    for layer in (SHEATHING, FRAME, OTHER):
        doc.layers.add(layer)
    _partition(msp, 0)
    _partition(msp, 5000, 2000)
    synth.add_rect(msp, OTHER, 0, 9000, 4000, 9100)
    synth.add_rect(msp, synth.MASONRY, 0, 12000, 4000, 12100)
    return doc


def test_pieces_merge_into_partitions() -> None:
    cons = extract_frame_partitions(_doc(), load_params())
    assert len(cons) == 2
    assert {c.kind for c in cons} == {KIND}
    for c in cons:
        assert c.thickness_nominal == 100
        assert c.thickness_measured == pytest.approx(100, abs=0.5)
        assert c.source_layers == sorted([SHEATHING, FRAME])
    assert sorted(round(c.length_axis) for c in cons) == [2000, 3000]
    assert all(len(c.axis) == 1 for c in cons)


def test_reads_dxf_file(tmp_path: Path) -> None:
    path = tmp_path / "plan.dxf"
    _doc().saveas(str(path))
    assert len(extract_frame_partitions(path, load_params())) == 2


def test_other_layers_ignored() -> None:
    doc, msp = synth.new_doc()
    doc.layers.add(OTHER)
    synth.add_rect(msp, OTHER, 0, 0, 3000, 100)
    synth.add_rect(msp, synth.MASONRY, 0, 500, 3000, 600)
    assert extract_frame_partitions(doc, load_params()) == []


def test_layer_patterns_parameter() -> None:
    cons = extract_frame_partitions(_doc(), load_params(), layer_patterns=("08_*",))
    assert len(cons) == 1
    assert cons[0].source_layers == [OTHER]


def test_no_nominal_gives_check() -> None:
    cons = extract_frame_partitions(_doc(), load_params(), nominals_mm=(75.0,), tolerance_mm=5.0)
    assert all(c.thickness_nominal is None for c in cons)
    assert all(c.thickness == pytest.approx(100, abs=0.5) for c in cons)


def test_ids_stable_and_distinct_from_masonry(tmp_path: Path) -> None:
    first = extract_frame_partitions(_doc(), load_params())
    second = extract_frame_partitions(_doc(), load_params())
    assert [c.id for c in first] == [c.id for c in second]
    assert len({c.id for c in first}) == len(first)
    # Кладка той же геометрии получает другой id: вид входит в ключ.
    mdoc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 3000, 100)
    synth.add_rect(msp, synth.MASONRY, 0, 5000, 2000, 5100)
    built = synth.run(tmp_path, mdoc)
    raw = built["constructions"]
    assert isinstance(raw, list)
    masonry_ids = {str(c["id"]) for c in raw}
    assert len(masonry_ids) == 2
    assert masonry_ids.isdisjoint(c.id for c in first)


def test_same_fields_as_masonry() -> None:
    (a, _) = extract_frame_partitions(_doc(), load_params())
    assert isinstance(a, Construction)
    assert a.family == KIND
    assert a.polygon.area == pytest.approx(a.thickness_measured * a.length_axis, rel=1e-6)
