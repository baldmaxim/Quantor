"""Привязка листа к сетке осей модели (чертёж наложением): подобие по подписям осей."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.services.model_sheets import (
    ModelAxis,
    SheetAxis,
    building_number,
    fit_sheet,
    match_sheets,
    model_axes,
    normalize_label,
    sheet_axes,
    storey_floor,
    title_floors,
)

MM_PER_PT = 100 * 25.4 / 72  # 1:100


def _truth(theta_deg: float, scale: float, tx: float, ty: float):
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))

    def to_model(x: float, y: float) -> tuple[float, float]:
        return (scale * (c * x + s * y) + tx, scale * (s * x - c * y) + ty)

    def to_sheet(px: float, py: float) -> tuple[float, float]:
        dx, dy = (px - tx) / scale, (py - ty) / scale
        # обратное к R·diag(1, −1): q = diag(1, −1)·Rᵀ·d
        return (c * dx + s * dy, -(-s * dx + c * dy))

    return to_model, to_sheet


def _building(
    theta_model: float, origin: tuple[float, float], xs: list[float], ys: list[float], prefix: str
) -> tuple[list[ModelAxis], dict[str, tuple[tuple[float, float], tuple[float, float]]]]:
    """Сетка корпуса под углом theta_model: «prefix/1…» вдоль локальной Y, «prefix/А…» вдоль X."""
    c, s = math.cos(math.radians(theta_model)), math.sin(math.radians(theta_model))

    def rot(x: float, y: float) -> tuple[float, float]:
        return (origin[0] + c * x - s * y, origin[1] + s * x + c * y)

    axes, lines = [], {}
    for i, x in enumerate(xs, 1):
        p0, p1 = rot(x, -5000), rot(x, max(ys) + 5000)
        axes.append(ModelAxis(f"{prefix}/{i}", p0, p1))
        lines[f"{prefix}/{i}"] = (p0, p1)
    for j, y in enumerate(ys):
        tag = f"{prefix}/{'АБВГДЕЖ'[j]}"
        p0, p1 = rot(-5000, y), rot(max(xs) + 5000, y)
        axes.append(ModelAxis(tag, p0, p1))
        lines[tag] = (p0, p1)
    return axes, lines


def _sheet_from(lines, to_sheet, labels=None) -> list[SheetAxis]:
    """Оси на листе по известному подобию: вертикаль листа - постоянный x, горизонталь - y."""
    out = []
    for tag, (p0, p1) in lines.items():
        if labels is not None and tag not in labels:
            continue
        a, b = to_sheet(*p0), to_sheet(*p1)
        if abs(a[0] - b[0]) < 1e-6 * max(1.0, abs(a[1] - b[1])) or abs(a[0] - b[0]) < 0.01:
            out.append(SheetAxis(tag, "vertical", (a[0] + b[0]) / 2))
        elif abs(a[1] - b[1]) < 0.01:
            out.append(SheetAxis(tag, "horizontal", (a[1] + b[1]) / 2))
    return out


XS = [0, 6000, 12000, 18600, 24000]
YS = [0, 5400, 12000, 18000]


def _check(fit, to_model, corners=((0, 0), (2384, 0), (2384, 1684), (0, 1684))):
    assert fit is not None
    for x, y in corners:
        got, want = fit.apply(x, y), to_model(x, y)
        assert math.dist(got, want) < 2.0


def test_axis_aligned_building() -> None:
    to_model, to_sheet = _truth(0.0, MM_PER_PT, -12000.0, 70000.0)
    model, lines = _building(0.0, (5000.0, 9000.0), XS, YS, "1")
    fit, reason = fit_sheet(_sheet_from(lines, to_sheet), model, MM_PER_PT)
    assert reason is None
    assert fit.rotation_deg % 360 == pytest.approx(0.0, abs=1e-6)
    assert fit.n_vertical == 5 and fit.n_horizontal == 4
    _check(fit, to_model)


def test_rotated_building_minus_7_degrees() -> None:
    # Корпус 7 стоит на площадке под −7°, его лист нарисован по осям корпуса
    to_model, to_sheet = _truth(-7.0, MM_PER_PT, 80000.0, 120000.0)
    model, lines = _building(-7.0, (70000.0, 60000.0), XS, YS, "7")
    fit, reason = fit_sheet(_sheet_from(lines, to_sheet), model, MM_PER_PT)
    assert reason is None
    assert fit.rotation_deg == pytest.approx(353.0, abs=1e-3)
    assert fit.rms_mm < 1.0
    _check(fit, to_model)


def test_sheet_drawn_rotated_90() -> None:
    # Корпус 2 на листе повёрнут: его «2/1…» на листе горизонтальные
    to_model, to_sheet = _truth(90.0, MM_PER_PT, 30000.0, -5000.0)
    model, lines = _building(0.0, (0.0, 70000.0), XS, YS, "2")
    fit, reason = fit_sheet(_sheet_from(lines, to_sheet), model, MM_PER_PT)
    assert reason is None
    assert fit.rotation_deg == pytest.approx(90.0, abs=1e-3)
    _check(fit, to_model)


def test_latin_letters_on_sheet_match_cyrillic_tags() -> None:
    to_model, to_sheet = _truth(0.0, MM_PER_PT, 0.0, 0.0)
    model, lines = _building(0.0, (0.0, 0.0), XS, YS, "3")
    sheet = [
        SheetAxis(a.label.replace("А", "A").replace("В", "B"), a.orient, a.pos_pt)
        for a in _sheet_from(lines, to_sheet)
    ]
    fit, reason = fit_sheet(sheet, model, MM_PER_PT)
    assert reason is None
    assert normalize_label("3/A") == normalize_label("3/А")
    _check(fit, to_model)


def test_one_wrong_label_is_dropped() -> None:
    to_model, to_sheet = _truth(0.0, MM_PER_PT, 1000.0, 2000.0)
    model, lines = _building(0.0, (0.0, 0.0), XS, YS, "4")
    sheet = _sheet_from(lines, to_sheet)
    bad = next(i for i, a in enumerate(sheet) if a.label == "4/3")
    sheet[bad] = SheetAxis("4/3", "vertical", sheet[bad].pos_pt + 60.0)  # 60 pt ≈ 2 м мимо
    fit, reason = fit_sheet(sheet, model, MM_PER_PT)
    assert reason is None
    assert "4/3" not in fit.used
    _check(fit, to_model)


def test_one_direction_only_is_rejected() -> None:
    _, to_sheet = _truth(0.0, MM_PER_PT, 0.0, 0.0)
    model, lines = _building(0.0, (0.0, 0.0), XS, YS, "5")
    sheet = [a for a in _sheet_from(lines, to_sheet) if a.orient == "vertical"]
    fit, reason = fit_sheet(sheet, model, MM_PER_PT)
    assert fit is None
    assert reason is not None


def test_scale_disagreeing_with_frame_is_rejected() -> None:
    _, to_sheet = _truth(0.0, MM_PER_PT, 0.0, 0.0)
    model, lines = _building(0.0, (0.0, 0.0), XS, YS, "6")
    fit, reason = fit_sheet(
        _sheet_from(lines, to_sheet), model, MM_PER_PT * 2
    )  # лист 1:200 по кадру
    assert fit is None
    assert "масштаб" in (reason or "")


def test_no_common_labels() -> None:
    _, to_sheet = _truth(0.0, MM_PER_PT, 0.0, 0.0)
    _model, lines = _building(0.0, (0.0, 0.0), XS, YS, "8")
    other, _ = _building(0.0, (0.0, 0.0), XS, YS, "9")
    fit, reason = fit_sheet(_sheet_from(lines, to_sheet), other, MM_PER_PT)
    assert fit is None and reason is not None


def test_same_tag_in_two_buildings_picks_consistent_one() -> None:
    to_model, to_sheet = _truth(0.0, MM_PER_PT, 0.0, 0.0)
    model, lines = _building(0.0, (0.0, 0.0), XS, YS, "1")
    # в другом корпусе ось с той же маркой «1/2» далеко
    model.append(ModelAxis("1/2", (90000.0, -5000.0), (90000.0, 25000.0)))
    fit, reason = fit_sheet(_sheet_from(lines, to_sheet), model, MM_PER_PT)
    assert reason is None
    _check(fit, to_model)


def test_parsers_skip_bad_items() -> None:
    raw = {
        "axes": {
            "items": [
                {"label": "1/1", "orient": "vertical", "pos_pt": 100.5},
                {"label": " ", "orient": "vertical", "pos_pt": 1},
                {"label": "1/А", "orient": "diagonal", "pos_pt": 1},
                {"label": "1/Б", "orient": "horizontal", "pos_pt": True},
                {"label": "1/В", "orient": "horizontal", "pos_pt": 200},
            ]
        }
    }
    assert [(a.label, a.orient) for a in sheet_axes(raw)] == [
        ("1/1", "vertical"),
        ("1/В", "horizontal"),
    ]
    grids = {
        "axes": [
            {"tag": "1", "dir": "U", "p0": [0, 0], "p1": [0, 10000]},
            {"tag": "2", "dir": "U", "p0": [0, 0], "p1": [0, 0]},
            {"tag": "А", "p0": "x"},
        ]
    }
    assert [a.tag for a in model_axes(grids)] == ["1"]
    assert sheet_axes(None) == [] and model_axes([]) == []


def _sheet(title, building, elevation, floors=(None, None), walls="k", page=1):
    return SimpleNamespace(
        walls_key=walls,
        scale_key="s",
        checks_key="c",
        passport_building=building,
        passport_elevation_mm=elevation,
        passport_floor_from=floors[0],
        passport_floor_to=floors[1],
        stamp_title=title,
        page_index=page,
        view=1,
    )


def test_title_floors() -> None:
    assert title_floors("Корпус 5. План 5, 9, 13, 16 этажей") == {5, 9, 13, 16}
    assert title_floors("Корпус 1. План 5-12 этажей") == set(range(5, 13))
    assert title_floors("План -2 этажа") == {-2}
    assert title_floors("Корпус 5. План 25, 27 этажей") == {25, 27}
    assert title_floors("Корпус 7. План техпространства на отм. +105,200") == set()
    assert title_floors(None) == set()


def test_storey_and_building_numbers() -> None:
    assert storey_floor("17 этаж") == 17
    assert storey_floor("-2 этаж") == -2
    assert storey_floor("Кровля +54.000") is None
    assert building_number("Корпус 5") == "5"
    assert building_number("Корп. 12") == "12"
    assert building_number("Подземная часть") is None
    assert building_number(None) is None


def test_storey_matches_its_own_building_and_floor() -> None:
    own = _sheet("Корпус 5. План 17 этажа", "5", 65000, page=95)
    other = _sheet("Корпус 3. План 17 этажа", "3", 65600, page=72)
    typical = _sheet("Корпус 5. План 5, 9, 13, 16 этажей", "5", 21900, (5, 16), page=90)
    no_walls = _sheet("Корпус 5. План 17 этажа", "5", 65000, walls=None, page=94)
    found = match_sheets(
        [other, typical, no_walls, own],
        building_name="Корпус 5",
        storey_name="17 этаж",
        elevation_mm=65850,
    )
    assert [(m.sheet.page_index, m.rank) for m in found] == [(95, 0)]


def test_typical_floor_from_passport_range_without_title_floors() -> None:
    sheet = _sheet("Корпус 1. План типовых этажей", "1", 21900, (5, 12), page=38)
    found = match_sheets(
        [sheet], building_name="Корпус 1", storey_name="7 этаж", elevation_mm=29100
    )
    assert [m.rank for m in found] == [1]


def test_technical_floor_by_elevation() -> None:
    tech = _sheet("Корпус 5. План техпространства на отм. +110,700", "5", 110700, page=105)
    floor = _sheet("Корпус 5. План 28 этажа", "5", 106350, page=104)
    found = match_sheets(
        [floor, tech],
        building_name="Корпус 5",
        storey_name="Техпространство +110.700",
        elevation_mm=110700,
    )
    assert [m.sheet.page_index for m in found] == [105]


def test_stylobate_takes_sheets_without_building_number() -> None:
    stylobate = _sheet("Стилобат. План 2 этажа. М 1:200", None, 7200, page=9)
    tower = _sheet("Корпус 1. План 2 этажа", "1", 7200, page=12)
    found = match_sheets(
        [tower, stylobate], building_name="Стилобат", storey_name="2 этаж", elevation_mm=7200
    )
    assert [m.sheet.page_index for m in found] == [9]
