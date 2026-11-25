"""Марки осей «4/1» (корпус 4, ось 1) при постановке зданий на объект (объект 346)."""

from __future__ import annotations

from app.services import cad_building3d as b3d


def axes(vertical: dict[str, float], horizontal: dict[str, float]) -> b3d.FloorAxes:
    return b3d.FloorAxes(vertical, horizontal, None)


def info(key: str, corps: str | None, a: b3d.FloorAxes) -> b3d._GroupInfo:
    return b3d._GroupInfo(key=key, label=key, axes=a, levels=(), corps=corps)


TOWER = axes(
    {"4/1": 0.0, "4/2": 6000.0, "4/3": 12000.0, "4/4": 18000.0},
    {"4/А": 0.0, "4/Б": 7000.0, "4/В": 14000.0},
)


def test_fraction_marks_of_most_axes_of_a_corps_are_its_corps_marks() -> None:
    other = axes({"1/1": 0.0, "1": 3000.0, "2": 9000.0, "3": 15000.0}, {"А": 0.0, "Б": 6000.0})
    marks = b3d._corps_marks({"k4": info("k4", "4", TOWER), "k1": info("k1", "1", other)})
    assert marks == frozenset({"4"})
    assert b3d._is_prefixed("4/15", marks)
    assert not b3d._is_prefixed("1/1", marks)
    assert b3d._is_prefixed("15.1")


def test_corps_marks_place_a_tower_even_when_a_quarter_of_common_marks_disagree() -> None:
    # Стилобат несёт оси корпуса; одна вертикальная и одна горизонтальная марка смещены
    # (выноска кружка), согласных меньше 75 % - без номера корпуса совпадение не принималось.
    shift = 50000.0
    stylobate = axes(
        {"4/1": shift, "4/2": shift + 6000.0, "4/3": shift + 9000.0, "4/4": shift + 25000.0},
        {"4/А": 1000.0, "4/Б": 8000.0, "4/В": 30000.0},
    )
    assert b3d._site_match(stylobate, TOWER) is None
    match = b3d._site_match(stylobate, TOWER, frozenset({"4"}))
    assert match is not None and match.prefixed
    assert match.shift == (shift, 1000.0)


def test_axes_of_a_corps_sheet_with_mostly_other_corps_marks_are_the_site_scheme() -> None:
    # Объект 346, корпус 2: кружки плана (отдельные отрезки) движок до cad_walls v1.23 не находил,
    # на листе оставались только оси компоновочной схемы в углу.
    scheme = axes(
        {"1/1": 0.0, "1/10": 1.0, "2/Е": 2.0, "4/А": 3.0, "6/А": 4.0, "7/А": 5.0, "9/А": 6.0},
        {"2/1": 0.0, "3/10": 1.0, "8/1": 2.0},
    )
    assert b3d.foreign_axes(scheme, "2")
    assert not b3d.foreign_axes(TOWER, "4")
    assert not b3d.foreign_axes(scheme, None)
