"""Высоты: отметка и высота этажа из заголовков планов (синтетический PDF), допущения."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from cad_walls.heights import resolve_heights
from cad_walls.params import load_params
from tests import synth

TITLES = [
    "Корпус 9. Секция 3. План 14 этажа на отм. +47,600",
    "Корпус 9. Секция 3. План 15 этажа на отм. +50,900",
]


def test_no_pdf_is_missing() -> None:
    h = resolve_heights(None, None, load_params())
    assert h["elevation_status"] == "missing"
    assert h["height_status"] == "missing"
    assert h["floor_elevation_mm"] is None
    assert h["floor_height_mm"] is None
    assert h["message"]
    assert (h["slab_thickness_mm"], h["slab_status"]) == (200, "assumption")
    assert (h["door_height_mm"], h["door_height_status"]) == (2100, "assumption")


def test_elevation_observed_height_derived(tmp_path: Path) -> None:
    pdf = synth.make_pdf(tmp_path / "a.pdf", TITLES)
    h = resolve_heights(pdf, 0, load_params())
    assert h["floor_elevation_mm"] == 47600
    assert h["floor_height_mm"] == 3300
    assert h["elevation_status"] == "observed"
    assert h["height_status"] == "derived"
    assert "+47,600" in str(h["evidence"])
    assert h["message"] is None


def test_title_not_found_is_missing_with_message(tmp_path: Path) -> None:
    pdf = synth.make_pdf(tmp_path / "b.pdf", ["Общие данные", "Ведомость"])
    h = resolve_heights(pdf, 0, load_params())
    assert h["elevation_status"] == "missing"
    assert h["floor_elevation_mm"] is None
    assert "отметка" in str(h["message"])


def test_heights_in_walls_document(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    pdf = synth.make_pdf(tmp_path / "c.pdf", TITLES)
    out = synth.run(tmp_path, doc, pdf=pdf, page=1)
    heights = cast(dict[str, object], out["heights"])
    assert heights["floor_elevation_mm"] == 50900
