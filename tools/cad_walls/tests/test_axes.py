"""Оси по маркам-кружкам листа: синтетические PDF, без клиентских данных."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pymupdf
import pytest

from cad_walls.axes import is_axis_label, read_axes
from cad_walls.errors import WallsError
from cad_walls.params import load_params
from tests import synth

D = 17.0
Mark = tuple[float, float, str]
Circle = tuple[float, float, float, str]  # центр x, y, диаметр, текст

P = load_params(None)


def _polygon(cx: float, cy: float, d: float, n: int = 20) -> list[tuple[float, float]]:
    return [
        (cx + d / 2 * math.cos(2 * math.pi * k / n), cy + d / 2 * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ]


def make_sheet(
    path: Path, circles: Sequence[Circle], rotation: int = 0, as_polygon: bool = True
) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    for cx, cy, d, text in circles:
        if as_polygon:
            page.draw_polyline([*_polygon(cx, cy, d), _polygon(cx, cy, d)[0]], color=(0, 0, 0))
        else:
            page.draw_circle((cx, cy), d / 2, color=(0, 0, 0))
        if text:
            page.insert_text((cx - 5, cy + 3), text, fontsize=7, fontname="helv")
    if rotation:
        page.set_rotation(rotation)
    doc.save(str(path))
    doc.close()
    return path


def _items(block: dict[str, object]) -> dict[tuple[str, str], float]:
    items = cast(list[dict[str, object]], block["items"])
    return {(str(i["label"]), str(i["orient"])): cast(float, i["pos_pt"]) for i in items}


def _grid(row_y: float = 500.0, col_x: float = 40.0) -> list[Circle]:
    row: list[Circle] = [(100.0 + 80 * k, row_y, D, f"3.{k + 1}") for k in range(4)]
    col: list[Circle] = [(col_x, 100.0, D, "3.A"), (col_x, 300.0, D, "3.B")]
    return [*row, *col]


def test_row_vertical_column_horizontal(tmp_path: Path) -> None:
    block = read_axes(make_sheet(tmp_path / "a.pdf", _grid()), 0, P)
    assert block["status"] == "found"
    assert block["message"] is None
    assert block["diameter_pt"] == pytest.approx(D, abs=0.1)
    assert block["conflicts"] == []
    got = _items(block)
    assert got == {
        ("3.1", "vertical"): pytest.approx(100.0, abs=0.05),
        ("3.2", "vertical"): pytest.approx(180.0, abs=0.05),
        ("3.3", "vertical"): pytest.approx(260.0, abs=0.05),
        ("3.4", "vertical"): pytest.approx(340.0, abs=0.05),
        ("3.A", "horizontal"): pytest.approx(100.0, abs=0.05),
        ("3.B", "horizontal"): pytest.approx(300.0, abs=0.05),
    }
    orients = [i["orient"] for i in cast(list[dict[str, object]], block["items"])]
    assert orients == ["vertical"] * 4 + ["horizontal"] * 2
    first = cast(list[dict[str, object]], block["items"])[0]
    assert first["bubbles_pt"] == [[100.0, 500.0]]


def test_bezier_circles_also_work(tmp_path: Path) -> None:
    block = read_axes(make_sheet(tmp_path / "b.pdf", _grid(), as_polygon=False), 0, P)
    assert block["status"] == "found"
    assert len(_items(block)) == 6


def test_other_circles_ignored(tmp_path: Path) -> None:
    extra: list[Circle] = [(600.0, 200.0, 32.0, "12"), (650.0, 420.0, 22.5, "5")]
    block = read_axes(make_sheet(tmp_path / "c.pdf", [*_grid(), *extra]), 0, P)
    assert block["status"] == "found"
    assert ("12", "vertical") not in _items(block)
    assert len(_items(block)) == 6
    assert block["rejected"] == 2


def test_non_label_text_ignored(tmp_path: Path) -> None:
    grid = _grid()
    circles = [*grid, (500.0, 500.0, D, "Kv.1"), (580.0, 500.0, D, "")]
    block = read_axes(make_sheet(tmp_path / "d.pdf", circles), 0, P)
    assert len(_items(block)) == 6


def test_duplicate_label_on_both_sides_merged(tmp_path: Path) -> None:
    top: list[Circle] = [(100.0 + 80 * k, 60.0, D, f"3.{k + 1}") for k in range(3)]
    bottom: list[Circle] = [(100.0 + 80 * k, 500.0, D, f"3.{k + 1}") for k in range(3)]
    left: list[Circle] = [(40.0, 100.0, D, "3.A"), (40.0, 300.0, D, "3.B")]
    block = read_axes(make_sheet(tmp_path / "e.pdf", [*top, *bottom, *left]), 0, P)
    assert block["status"] == "found"
    items = cast(list[dict[str, object]], block["items"])
    first = next(i for i in items if i["label"] == "3.1")
    assert first["bubbles_pt"] == [[100.0, 60.0], [100.0, 500.0]]
    assert len(items) == 5


def test_conflicting_positions_dropped(tmp_path: Path) -> None:
    top: list[Circle] = [(100.0, 60.0, D, "3.1"), (180.0, 60.0, D, "3.2")]
    bottom: list[Circle] = [(130.0, 500.0, D, "3.1"), (180.0, 500.0, D, "3.2")]
    left: list[Circle] = [(40.0, 100.0, D, "3.A"), (40.0, 300.0, D, "3.B")]
    block = read_axes(make_sheet(tmp_path / "f.pdf", [*top, *bottom, *left]), 0, P)
    assert block["conflicts"] == ["3.1"]
    assert ("3.1", "vertical") not in _items(block)
    assert ("3.2", "vertical") in _items(block)
    assert block["status"] == "found"


def test_only_row_is_partial(tmp_path: Path) -> None:
    row: list[Circle] = [(100.0 + 80 * k, 500.0, D, f"3.{k + 1}") for k in range(3)]
    block = read_axes(make_sheet(tmp_path / "g.pdf", row), 0, P)
    assert block["status"] == "partial"
    assert "горизонтальные" in str(block["message"])
    assert len(_items(block)) == 3


def test_no_bubbles_is_missing(tmp_path: Path) -> None:
    block = read_axes(make_sheet(tmp_path / "h.pdf", []), 0, P)
    assert block["status"] == "missing"
    assert block["items"] == []
    assert block["diameter_pt"] is None
    assert block["message"]


def test_no_pdf_is_missing() -> None:
    block = read_axes(None, None, P)
    assert block["status"] == "missing"
    assert block["message"]


def test_bad_pdf_and_page(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(WallsError):
        read_axes(broken, 0, P)
    with pytest.raises(WallsError):
        read_axes(make_sheet(tmp_path / "i.pdf", _grid()), 5, P)


def test_rotated_page_uses_display_coordinates(tmp_path: Path) -> None:
    pdf = make_sheet(tmp_path / "j.pdf", _grid(), rotation=90)
    block = read_axes(pdf, 0, P)
    assert block["status"] == "found"
    # страница 800x600 после поворота на 90 градусов: x' = 600 - y, y' = x
    got = _items(block)
    assert got[("3.1", "horizontal")] == pytest.approx(100.0, abs=0.05)
    assert got[("3.4", "horizontal")] == pytest.approx(340.0, abs=0.05)
    assert got[("3.A", "vertical")] == pytest.approx(500.0, abs=0.05)
    assert got[("3.B", "vertical")] == pytest.approx(300.0, abs=0.05)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("3.1", True),
        ("3.А", True),  # кириллица
        ("Г", True),
        ("Б/2", True),
        ("12", True),
        ("3-ЯЁ", True),
        ("Кв.1", False),
        ("3.", False),
        ("1234", False),
        ("а", False),
        ("3.1 2", False),
        ("", False),
    ],
)
def test_label_regex(text: str, ok: bool) -> None:
    assert is_axis_label(text) is ok


def test_walls_json_has_axes_block(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 3000, 100)
    pdf = make_sheet(tmp_path / "plan.pdf", _grid())
    out = synth.run(tmp_path, doc, pdf, 0)
    axes = cast(dict[str, object], out["axes"])
    assert axes["status"] == "found"
    assert len(cast(list[object], axes["items"])) == 6
    without = synth.run(tmp_path, doc)
    assert cast(dict[str, object], without["axes"])["status"] == "missing"
