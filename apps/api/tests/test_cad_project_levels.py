"""Отметки этажей проекта по заголовкам схем КР и их применение к этажам «Здания» (объект 346)."""

from __future__ import annotations

import dataclasses

from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from app.services import cad_project_levels as levels
from tests.test_cad_building3d import floor_of, sheet
from tests.test_cad_floor3d import raw_document, raw_extras


def scheme(title: str, first: int | None, last: int | None, page: int = 0) -> levels.SchemeTitle:
    return levels.SchemeTitle(
        building=None,
        file_name="01-04-00-12-06 ПД-4236552024-КР2.ГЧ.К7.pdf",
        code=None,
        title=title,
        floor_from=first,
        floor_to=last,
        page_index=page,
    )


def test_marks_after_the_word_otm_with_sign_comma_and_ellipsis() -> None:
    assert levels.marks_of("Лист 14. Схема ... 24-28 этажей на отм. +90.800…+107.150") == (
        [90800, 107150],
        True,
    )
    assert levels.marks_of("Схема -1 этажа на отм. -6,850, -3,550") == ([-6850, -3550], False)
    assert levels.marks_of("Схема 29 этажа на отм. +112.400, 112.700") == ([112400, 112700], False)
    assert levels.marks_of("Схема 8-15 этажей на отм. +32,600, ..., +57,800") == (
        [32600, 57800],
        True,
    )
    assert levels.marks_of("Лист 14. План 5 этажа") == ([], False)


def test_floor_marks_one_per_floor_range_by_step_or_first_only() -> None:
    assert levels.floor_marks(17, 17, [65000, 65300], False) == {17: 65000}
    assert levels.floor_marks(30, 31, [116300, 119900], False) == {30: 116300, 31: 119900}
    by_step = levels.floor_marks(5, 16, [21800, 61400], True)
    assert by_step[5] == 21800 and by_step[6] == 25400 and by_step[16] == 61400
    assert levels.floor_marks(5, 16, [21800, 61400], False) == {5: 21800}


def test_corps_from_the_code_in_the_file_name_and_specific_schemes_win() -> None:
    table = levels.collect_levels(
        [
            scheme("Схема 5-16 этажей на отм. +21.800...+61.400", 5, 16, page=14),
            scheme("Схема 16 этажа на отм. +61.450", 16, 16, page=15),
            scheme("Схема тех. пространства на отм. +110.450", None, None, page=16),
        ]
    )
    assert table[("7", 5)].z_mm == 21800
    assert table[("7", 16)].z_mm == 61450
    assert table[("7", 16)].ref.endswith("лист 16")
    assert len(table) == 12


def _loaded(floor_patch: dict[str, object], title_floors: tuple[str, ...]) -> b3d._SheetFloor:
    floor = floor_of(raw_document(), raw_extras()).model_copy(update=floor_patch)
    return b3d._SheetFloor(floor, (), b3d.NO_AXES, title_floors=title_floors)


TABLE = levels.collect_levels([scheme("Схема 5-16 этажей на отм. +21.800...+61.400", 5, 16)])


def test_typical_sheet_without_title_marks_is_spread_over_kr_levels() -> None:
    item = _loaded(
        {"corps": "7", "label": "К7 · 5–16 эт.", "base_z_mm": 21750, "elevation_known": True},
        tuple(str(n) for n in range(5, 17)),
    )
    (out,) = assembly.apply_project_levels([sheet()], [item], TABLE)
    assert out.floor is not None and out.floor.base_z_mm == 21750
    assert out.typical is not None
    assert out.typical.own.startswith("К7 · 5 эт.")
    assert [delta for _label, delta in out.typical.others][:2] == [3600, 7200]
    assert len(out.typical.others) == 11


def test_wrong_plan_mark_is_replaced_by_the_sheet_title_mark_from_the_passport() -> None:
    item = _loaded(
        {
            "corps": "5",
            "label": "К5 · выход на кровлю",
            "base_z_mm": -23260,
            "elevation_known": True,
        },
        (),
    )
    ref = dataclasses.replace(sheet(), passport_elevation_mm=112950)
    (out,) = assembly.apply_project_levels([ref], [item], {})
    assert out.floor is not None and out.floor.base_z_mm == 112950
    assert [w.code for w in out.warnings] == ["floor_elevation_project"]
    assert "-23.260" in out.warnings[0].message


def test_close_plan_mark_stays_and_unknown_elevation_takes_the_kr_level() -> None:
    near = _loaded({"corps": "7", "base_z_mm": 21900, "elevation_known": True}, ("5",))
    unknown = _loaded({"corps": "7", "base_z_mm": 0, "elevation_known": False}, ("6",))
    out = assembly.apply_project_levels([sheet(), sheet()], [near, unknown], TABLE)
    assert out[0].floor is not None and out[0].floor.base_z_mm == 21900 and not out[0].warnings
    assert out[1].floor is not None and out[1].floor.base_z_mm == 25400
    assert out[1].floor.elevation_known


def test_sheet_with_title_marks_is_left_as_is() -> None:
    item = dataclasses.replace(
        _loaded({"corps": "7", "base_z_mm": 0, "elevation_known": False}, ("6",)),
        title_marked=True,
    )
    (out,) = assembly.apply_project_levels([sheet()], [item], TABLE)
    assert out is item
