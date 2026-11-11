"""Подпись этажа по заголовку плана (зеркало formatFloorTitle веб-клиента) и разбор title."""

from __future__ import annotations

from app.contracts.cad_constructions import CadSheetFloorTitle, WallsHeights
from app.services.cad_floor_title import format_floor_title

FALLBACK = "лист 82"


def title(**fields: object) -> CadSheetFloorTitle:
    return CadSheetFloorTitle.model_validate(fields)


def test_full_title() -> None:
    assert format_floor_title(title(corps="9", section="3", floors=[14]), FALLBACK) == (
        "К9 · С3 · 14 эт."
    )


def test_range_and_list_of_floors() -> None:
    assert format_floor_title(title(corps="9", floors=[2, 3, 4, 5]), FALLBACK) == "К9 · 2–5 эт."
    assert format_floor_title(title(floors=[2, 4]), FALLBACK) == "2, 4 эт."


def test_only_floor_and_empty_title() -> None:
    assert format_floor_title(title(floors=[14]), FALLBACK) == "14 эт."
    assert format_floor_title(title(), FALLBACK) == FALLBACK
    assert format_floor_title(None, FALLBACK) == FALLBACK


def test_floors_from_walls_json_are_numbers_and_become_text() -> None:
    assert title(floors=[15]).floors == ["15"]


def test_walls_heights_title_is_optional() -> None:
    base = {
        "floor_elevation_mm": None,
        "floor_height_mm": None,
        "elevation_status": "missing",
        "height_status": "missing",
        "evidence": None,
        "message": None,
        "slab_thickness_mm": 200,
        "slab_status": "assumption",
        "door_height_mm": 2100,
        "door_height_status": "assumption",
    }
    assert WallsHeights.model_validate(base).title is None
    with_title = WallsHeights.model_validate({**base, "title": {"corps": "9", "floors": [15]}})
    assert with_title.title is not None and with_title.title.floors == ["15"]
