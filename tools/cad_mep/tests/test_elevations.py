"""Отметка пола и высота этажа из заголовков планов (синтетический PDF, без клиентских данных)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from cad_mep import elevations
from cad_mep.errors import MepError
from cad_mep.params import load_params

FONT = pymupdf.Font("helv")
Page = list[tuple[str, float, float]]  # (строка, x, y)


def _pdf(path: Path, pages: list[Page]) -> Path:
    doc = pymupdf.open()
    for texts in pages:
        page = doc.new_page(width=900, height=500)
        tw = pymupdf.TextWriter(page.rect)
        for text, x, y in texts:
            tw.append((x, y), text, font=FONT, fontsize=8)
        tw.write_text(page)
    doc.save(str(path))
    doc.close()
    return path


def _title(text: str) -> Page:
    return [(text, 100.0, 450.0)]


def _resolve(
    path: Path,
    page: int,
    elevation: int | None = None,
    height: int | None = None,
    at: tuple[float, float] = (450.0, 250.0),
) -> elevations.Resolved:
    return elevations.resolve(path, page, at, load_params(None), elevation, height)


def _code(path: Path, page: int) -> str:
    with pytest.raises(MepError) as info:
        _resolve(path, page)
    assert "вручную" in info.value.message
    return info.value.code


def test_elevation_observed_and_height_from_floor_above(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +50,900"),
            _title("Корпус 9. Секция 3. План 13 этажа на отм. +44,300"),
        ],
    )
    r = _resolve(pdf, 0)
    assert (r.elevation.value_mm, r.elevation.source) == (47600, "observed")
    assert r.elevation.evidence == 'стр. 1: "Корпус 9. Секция 3. План 14 этажа на отм. +47,600"'
    assert (r.height.value_mm, r.height.source) == (3300, "derived")
    assert r.height.evidence == "стр. 1 +47,600 → стр. 2 +50,900"
    assert r.issues == ()


def test_top_floor_uses_floor_below(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +50,900"),
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
        ],
    )
    r = _resolve(pdf, 0)
    assert r.height.value_mm == 3300
    assert r.height.evidence == "стр. 2 +47,600 → стр. 1 +50,900"


def test_other_building_is_ignored(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
            _title("Корпус 1. Секция 1. План 15 этажа на отм. +99,999"),
        ],
    )
    assert _code(pdf, 0) == "floor_height_not_found"


def test_sign_and_decimal_variants(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("План -2 этажа подземной автостоянки на отм.-5.250. Этап 1"),
            _title("План 1 этажа на отм. 0,000"),
            _title("План 3 этажа на отм. + 90,410 (1 : 200)"),
        ],
    )
    assert _resolve(pdf, 0, height=3300).elevation.value_mm == -5250
    assert _resolve(pdf, 1, height=3300).elevation.value_mm == 0
    assert _resolve(pdf, 2, height=3300).elevation.value_mm == 90410


def test_floor_zero_is_skipped_between_minus_one_and_one(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("План -1 этажа на отм.-3,300"),
            _title("План 1 этажа на отм. 0,000"),
        ],
    )
    assert _resolve(pdf, 0).height.value_mm == 3300


def test_typical_plan_for_several_floors_is_ambiguous(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title(
                "Секция 2. Корпус 8. План типовых 3, 4, 5 этажей на отм. +12,300, +15,600, +18,900"
            )
        ],
    )
    assert _code(pdf, 0) == "elevation_not_found"
    # отметку ввели: этаж находится по ней, высота - по соседям из того же заголовка
    r = _resolve(pdf, 0, elevation=15600)
    assert r.height.value_mm == 3300


def test_title_continued_on_next_line_is_merged(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [[("Корпус 9. Секция 3. План 14 этажа на", 100.0, 440.0), ("отм. +47,600", 100.0, 452.0)]],
    )
    assert _resolve(pdf, 0, height=3300).elevation.value_mm == 47600


def test_nearest_title_to_view_zone_is_taken(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            [
                ("Корпус 9. Секция 3. План 14 этажа на отм. +47,600", 50.0, 450.0),
                ("Корпус 9. Секция 3. План 15 этажа на отм. +50,900", 600.0, 50.0),
            ]
        ],
    )
    assert _resolve(pdf, 0, height=3300, at=(100.0, 440.0)).elevation.value_mm == 47600
    assert _resolve(pdf, 0, height=3300, at=(650.0, 60.0)).elevation.value_mm == 50900


def test_conflicting_marks_make_floor_unknown(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +50,900"),
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +51,000"),
        ],
    )
    assert _code(pdf, 0) == "floor_height_not_found"


def test_intermediate_level_blocks_derivation(tmp_path: Path) -> None:
    """Между этажами есть техпространство - разность номеров соседних этажей не высота."""
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 26 этажа на отм. +87,200"),
            _title("Корпус 9. Секция 3. План тех. пространства на отм. +90,410"),
            _title("Корпус 9. Секция 3. План 27 этажа на отм. +91,550"),
        ],
    )
    assert _code(pdf, 0) == "floor_height_not_found"


def test_absurd_height_is_not_used(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +60,000"),
        ],
    )
    assert _code(pdf, 0) == "floor_height_not_found"


def test_manual_values_override_and_report_mismatch(tmp_path: Path) -> None:
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            _title("Корпус 9. Секция 3. План 14 этажа на отм. +47,600"),
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +50,900"),
        ],
    )
    r = _resolve(pdf, 0, elevation=40000, height=3000)
    assert (r.elevation.value_mm, r.elevation.source) == (40000, "operator")
    assert (r.height.value_mm, r.height.source) == (3000, "operator")
    assert [code for code, _ in r.issues] == ["elevation_mismatch", "floor_height_mismatch"]
    assert "+40,000" in r.issues[0][1] and "+47,600" in r.issues[0][1]
    assert "3000" in r.issues[1][1] and "3300" in r.issues[1][1]


def test_no_title_and_manual_values_is_fine(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "a.pdf", [[("Кв 1011", 100.0, 100.0)]])
    assert _code(pdf, 0) == "elevation_not_found"
    r = _resolve(pdf, 0, elevation=47600, height=3300)
    assert r.issues == ()


def test_page_inherits_building_from_stamp(tmp_path: Path) -> None:
    """Подпись чертежа без корпуса берёт корпус/секцию штампа этой же страницы."""
    pdf = _pdf(
        tmp_path / "a.pdf",
        [
            [
                ("Корпус 9. Секция 3. План 14 этажа на отм.", 600.0, 480.0),
                (" План 14 этажа на отм. +47,600 ( 1 : 200)", 50.0, 20.0),
            ],
            _title("Корпус 9. Секция 3. План 15 этажа на отм. +50,900"),
        ],
    )
    r = _resolve(pdf, 0, at=(60.0, 20.0))
    assert (r.elevation.value_mm, r.height.value_mm) == (47600, 3300)
