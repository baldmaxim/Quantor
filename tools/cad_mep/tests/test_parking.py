"""Тесты поиска машиномест на синтетическом листе: PDF рисуется PyMuPDF (серые рельсы и глифы)."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from cad_mep.errors import MepError
from cad_mep.parking import find_parking
from cad_mep.parking_legend import parking_type
from cad_mep.zones import ZoneArgs, extract_zones
from tests import synth

SCALE = 70.0  # мм на пункт: место 2,5 x 5,3 м = 35,7 x 75,7 пт
LEN, WID = 5300.0 / SCALE, 2500.0 / SCALE
GRAY = (0.667, 0.668, 0.668)
HATCH = (0.753, 0.753, 0.753)
ZONE = (0.0, 0.0, 600.0, 500.0)  # рамка плана; легенда правее
PAGE = (900.0, 500.0)

Pt = tuple[float, float]
Xf = Callable[[float, float], Pt]


def _xf(cx: float, cy: float, deg: float) -> Xf:
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return lambda u, v: (cx + u * ca - v * sa, cy + u * sa + v * ca)


def _line(page: pymupdf.Page, a: Pt, b: Pt, color: tuple[float, ...]) -> None:
    page.draw_line(pymupdf.Point(*a), pymupdf.Point(*b), color=color, width=0.24)


def _glyph(page: pymupdf.Page, xf: Xf, kind: str) -> None:
    """Глиф машины из коротких серых штрихов (по одному пути): рамка кузова или крест."""
    dashes: list[tuple[Pt, Pt]] = []
    if kind == "a":
        for k in range(-28, 28, 8):
            dashes += [((k, -12), (k + 6, -12)), ((k, 12), (k + 6, 12))]
        for k in range(-12, 12, 8):
            dashes += [((-28, k), (-28, k + 6)), ((28, k), (28, k + 6))]
    else:
        for k in range(-28, 28, 7):
            dashes += [((k, k * 12 / 28), (k + 5, (k + 5) * 12 / 28))]
            dashes += [((k, -k * 12 / 28), (k + 5, -(k + 5) * 12 / 28))]
    for p, q in dashes:
        _line(page, xf(*p), xf(*q), GRAY)


def _hatch(page: pymupdf.Page, xf: Xf) -> None:
    """Серая штриховка под 45 градусов внутри места."""
    for k in range(-30, 31, 10):
        _line(page, xf(k - 12, -12), xf(k + 12, 12), HATCH)


def _stall(page: pymupdf.Page, xf: Xf, glyph: str | None, hatch: bool = False) -> None:
    for sign in (-1, 1):
        _line(page, xf(-LEN / 2, sign * WID / 2), xf(LEN / 2, sign * WID / 2), GRAY)
    if glyph:
        _glyph(page, xf, glyph)
    if hatch:
        _hatch(page, xf)


def _symbol(page: pymupdf.Page, cx: float, cy: float, glyph: str, hatch: bool, label: str) -> None:
    """Символ легенды: рамка (четвёртая сторона с разрывом, как в чертеже) и подпись справа."""
    xf = _xf(cx, cy, 0.0)
    a, b = xf(-LEN / 2, -WID / 2), xf(LEN / 2, -WID / 2)
    c, d = xf(LEN / 2, WID / 2), xf(-LEN / 2, WID / 2)
    shape = page.new_shape()
    shape.draw_polyline([pymupdf.Point(*p) for p in (b, a, d, c)])
    shape.draw_line(pymupdf.Point(*c), pymupdf.Point(c[0], c[1] - 5.0))
    shape.finish(color=GRAY, width=0.24, closePath=False)
    shape.commit()
    _glyph(page, xf, glyph)
    if hatch:
        _hatch(page, xf)
    tw = pymupdf.TextWriter(page.rect)
    tw.append((cx + LEN / 2 + 8.0, cy + 2.0), label, font=synth.FONT, fontsize=7)
    tw.write_text(page)


def _row(
    page: pymupdf.Page, cx: float, cy: float, deg: float, items: list[tuple[str | None, bool]]
) -> None:
    """Ряд мест вплотную по ширине: центр первого — (cx, cy), длинная сторона — под углом deg."""
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    for n, (glyph, hatch) in enumerate(items):
        _stall(page, _xf(cx - n * WID * sa, cy + n * WID * ca, deg), glyph, hatch)


def _pdf(path: Path, draw: Callable[[pymupdf.Page], None], rotation: int = 0) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    draw(page)
    if rotation:
        page.set_rotation(rotation)
    doc.save(str(path))
    doc.close()
    return path


def _spaces(result: dict[str, object]) -> list[dict[str, object]]:
    raw = result["parking_spaces"]
    assert isinstance(raw, list)
    return raw


def _points(space: dict[str, object]) -> list[list[float]]:
    pts = space["points"]
    assert isinstance(pts, list)
    return pts


def _find(path: Path) -> dict[str, object]:
    return find_parking(path, 0, ZONE, SCALE)


def test_row_of_three(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "a.pdf", lambda p: _row(p, 100, 200, 90, [("a", False)] * 3))
    spaces = _spaces(_find(pdf))
    assert len(spaces) == 3
    for s in spaces:
        assert s["width_m"] == pytest.approx(2.5, abs=0.02)
        assert s["length_m"] == pytest.approx(5.3, abs=0.02)
        assert s["area_m2"] == pytest.approx(13.25, abs=0.1)
        assert len(_points(s)) == 4
        assert s["parking_type"] == "unknown"
        assert s["label"] is None
        assert s["type_margin"] is None
        assert s["notes"] == ["легенда машиномест не найдена"]
    xs = [sum(q[0] for q in _points(s)) / 4 for s in spaces]
    assert xs == sorted(xs)  # в ряду — слева направо


def test_row_under_angle(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "b.pdf", lambda p: _row(p, 200, 250, 108, [("a", False)] * 3))
    spaces = _spaces(_find(pdf))
    assert len(spaces) == 3
    assert all(s["width_m"] == pytest.approx(2.5, abs=0.02) for s in spaces)


def test_rail_without_pair_or_glyph_is_not_a_stall(tmp_path: Path) -> None:
    def draw(page: pymupdf.Page) -> None:
        _line(page, (50, 50), (50, 50 + LEN), GRAY)  # одинокая рельса
        _stall(page, _xf(200, 100, 90), None)  # пара без глифа
        for k in range(4):  # и с недостаточным глифом
            _line(page, (300 + 8 * k, 100), (300 + 8 * k + 5, 100), GRAY)
        _stall(page, _xf(310, 100, 90), None)
        _stall(page, _xf(100, 300, 90), "a")  # одно настоящее место
        _line(page, (400, 50), (400, 50 + LEN), GRAY)  # ширина 1,5 м - не место
        _line(page, (400 + 1500 / SCALE, 50), (400 + 1500 / SCALE, 50 + LEN), GRAY)

    assert len(_spaces(_find(_pdf(tmp_path / "c.pdf", draw)))) == 1


def test_outside_plan_frame_is_ignored(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "d.pdf", lambda p: _stall(p, _xf(700, 250, 90), "a"))
    assert _spaces(_find(pdf)) == []


def _legend_sheet(page: pymupdf.Page) -> None:
    _row(page, 100, 200, 90, [("a", False), ("b", True), ("a", False)])
    _symbol(page, 680, 100, "a", False, "Места постоянное хранение")
    _symbol(page, 680, 160, "b", True, 'Машино-места - "Medium"')
    _symbol(page, 680, 220, "a", False, "Прочие места")  # подпись не распознана: пропуск


def test_types_by_legend(tmp_path: Path) -> None:
    result = _find(_pdf(tmp_path / "e.pdf", _legend_sheet))
    spaces = _spaces(result)
    assert [s["parking_type"] for s in spaces] == ["permanent", "medium", "permanent"]
    assert spaces[1]["label"] == 'Машино-места - "Medium"'
    assert spaces[0]["label"] == "Места постоянное хранение"
    assert all(s["notes"] == [] for s in spaces)
    assert all(float(str(s["type_margin"])) >= 0.08 for s in spaces)
    assert result["parking_legend"] == [
        {"parking_type": "permanent", "label": "Места постоянное хранение"},
        {"parking_type": "medium", "label": 'Машино-места - "Medium"'},
    ]
    assert result["parking_summary"] == [
        {"parking_type": "permanent", "label": "Места постоянное хранение", "count": 2},
        {"parking_type": "medium", "label": 'Машино-места - "Medium"', "count": 1},
    ]


def test_points_are_screen_normalized_on_rotated_page(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "f.pdf", lambda p: _stall(p, _xf(100, 300, 90), "a"), rotation=90)
    spaces = _spaces(find_parking(pdf, 0, ZONE, SCALE))
    assert len(spaces) == 1
    doc = pymupdf.open(str(pdf))
    page = doc[0]
    expected = pymupdf.Point(100, 300) * page.rotation_matrix  # центр места на экранной странице
    pts = _points(spaces[0])
    cx = sum(q[0] for q in pts) / 4 * page.rect.width
    cy = sum(q[1] for q in pts) / 4 * page.rect.height
    doc.close()
    assert (cx, cy) == pytest.approx((expected.x, expected.y), abs=0.5)
    assert all(0.0 <= v <= 1.0 for q in pts for v in q)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Места постоянное хранение", "permanent"),
        ("Места временного хранения", "temporary"),
        ("Гостевые м/м", "guest"),
        ('Машино-места - "Medium"', "medium"),
        ('Машино-места - "Medium" гостевые', "medium_guest"),
        ('Машино-места - "Large"', "large"),
        ('Машино-места - Large" гостевые', "large_guest"),
        ("Машино-места для МГН М1-3", "mgn_m1_3"),
        ("Машино-места для МГН М4", "mgn_m4"),
        ("Парковка", None),
    ],
)
def test_parking_type_from_label(label: str, expected: str | None) -> None:
    assert parking_type(label) == expected


def _zone_inputs(folder: Path, with_stalls: bool) -> ZoneArgs:
    """Этаж без экспликации квартир; места (если нужны) — в свободной части рамки плана."""
    floor, _ = synth.build_zones_floor()
    floor.expl = []
    files = synth.write_inputs(floor, folder)
    if with_stalls:
        doc = pymupdf.open(str(files["pdf"]))
        px, py = synth._pt(14500.0, 3500.0)
        _row(doc[0], px, py, 90, [("a", False)] * 3)
        doc.saveIncr()
        doc.close()
    out = folder / "zones.json"
    return ZoneArgs(files["pdf"], 0, files["dxf"], files["scale"], files["preview"], None, out)


def test_extract_zones_without_apartments_returns_parking(tmp_path: Path) -> None:
    result = extract_zones(_zone_inputs(tmp_path / "with", True))
    assert result["zones"] == []
    assert len(_spaces(result)) == 3
    assert result["parking_summary"] == [{"parking_type": "unknown", "label": None, "count": 3}]


def test_extract_zones_without_apartments_and_stalls_fails(tmp_path: Path) -> None:
    with pytest.raises(MepError) as exc:
        extract_zones(_zone_inputs(tmp_path / "none", False))
    assert exc.value.code == "no_explication"
