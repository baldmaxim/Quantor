"""Привязка листа PDF по подписям осей: точность, повороты, ложные цифры, register-all."""

from __future__ import annotations

from pathlib import Path

import pytest
from synth_pdf import A_100, U_TAGS, grids_dict, make_sheet

from model_package.register_sheet import register_all, register_sheet

EXPECTED_SIGNS = {0: (1, -1), 90: (-1, -1), 180: (-1, 1), 270: (1, 1)}


@pytest.mark.parametrize("orientation", [0, 90, 180, 270])
def test_fit_accuracy_and_orientation(tmp_path: Path, orientation: int) -> None:
    pdf = tmp_path / "sheet.pdf"
    truth = make_sheet(pdf, orientation=orientation)
    p = register_sheet(grids_dict(), pdf, 0)
    assert p["ok"], p["reasons"]
    assert p["orientation"] == orientation
    su, sv = EXPECTED_SIGNS[orientation]
    assert p["sx"][0] == pytest.approx(su * A_100, rel=1e-5)
    assert p["sy"][0] == pytest.approx(sv * A_100, rel=1e-5)
    assert p["sx"][1] == pytest.approx(truth.bu, abs=0.05)
    assert p["sy"][1] == pytest.approx(truth.bv, abs=0.05)
    assert p["scale_ratio"] == 100.0
    assert p["resid_mm_max"] < 1.0
    assert len(p["matched_u"]) == 9 and len(p["matched_v"]) == 6
    assert p["matched_v"][0] == "А"


def test_decoy_digits_do_not_win(tmp_path: Path) -> None:
    """Ложный ряд цифр 1-9 в масштабе 1:200 не перебивает настоящую сетку 1:100."""
    pdf = tmp_path / "sheet.pdf"
    make_sheet(pdf, decoys=True)
    p = register_sheet(grids_dict(), pdf, 0)
    assert p["ok"] and p["scale_ratio"] == 100.0


def test_no_labels(tmp_path: Path) -> None:
    pdf = tmp_path / "sheet.pdf"
    make_sheet(pdf, labels=False, decoys=False)
    p = register_sheet(grids_dict(), pdf, 0)
    assert not p["ok"] and p["reasons"]


def test_decoys_without_axes_are_rejected(tmp_path: Path) -> None:
    """Без марок осей остаются только ложные цифры - подгонка не принимается."""
    pdf = tmp_path / "sheet.pdf"
    make_sheet(pdf, labels=False, decoys=True)
    p = register_sheet(grids_dict(), pdf, 0)
    assert not p["ok"]


def test_too_few_axes(tmp_path: Path) -> None:
    few = {t: x for t, x in U_TAGS.items() if t in ("1", "2", "3")}
    pdf = tmp_path / "sheet.pdf"
    make_sheet(pdf, grids=grids_dict(few), decoys=False)
    p = register_sheet(grids_dict(few), pdf, 0)
    assert not p["ok"]
    assert any("оси U" in r for r in p["reasons"])


def test_register_all(tmp_path: Path) -> None:
    pdf = tmp_path / "set.pdf"
    make_sheet(pdf, title="План 1 этажа, на отм.+3,010", extra_pages=["Разрез 1-1"])
    storeys = [
        {"storey_key": "S1", "name": "Этаж 1", "elevation_mm": 0.0},
        {"storey_key": "S2", "name": "Этаж 2", "elevation_mm": 3000.0},
    ]
    rows = register_all(grids_dict(), storeys, pdf)
    assert [r["plan"] for r in rows] == [True, False]
    plan = rows[0]
    assert plan["storeys"][0]["storey_key"] == "S2"
    assert plan["storeys"][0]["delta_mm"] == -10.0
    assert not plan["warnings"]
    assert plan["placement"]["ok"]


def test_overlay_png(tmp_path: Path) -> None:
    from model_package.overlay import draw_overlay

    pdf = tmp_path / "sheet.pdf"
    make_sheet(pdf, orientation=90)
    placement = register_sheet(grids_dict(), pdf, 0)
    footprint = {"polygons": {"columns": [[[0.0, 0.0], [400.0, 0.0], [400.0, 400.0]]]}}
    png = draw_overlay(pdf, placement, grids_dict(), tmp_path / "o.png", footprint)
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
