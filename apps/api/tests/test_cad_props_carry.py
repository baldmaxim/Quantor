"""Перенос осиротевших параметров конструкций по геометрии (чистое сопоставление, без базы)."""

from __future__ import annotations

from app.contracts.cad_constructions import (
    CadConstructionKind,
    CadConstructionProps,
    WallsConstruction,
    WallsPolygon,
)
from app.services.cad_constructions import is_same_construction, match_orphan_props

Rect = tuple[float, float, float, float]


def wall(
    key: str,
    rect: Rect = (0.0, 0.0, 5000.0, 200.0),
    *,
    kind: CadConstructionKind = "masonry",
    nominal: float | None = 200.0,
    holes: list[list[list[float]]] | None = None,
) -> WallsConstruction:
    x0, y0, x1, y1 = rect
    return WallsConstruction(
        id=key,
        kind=kind,
        source_layers=[],
        polygon=WallsPolygon.model_validate(
            {"shell": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "holes": holes or []}
        ),
        area_plan_mm2=(x1 - x0) * (y1 - y0),
        thickness_measured_mm=nominal or 137.0,
        thickness_nominal_mm=nominal,
        thickness_status="matched" if nominal else "check",
        length_axis_mm=x1 - x0,
        centroid=[(x0 + x1) / 2, (y0 + y1) / 2],
        bbox=[x0, y0, x1, y1],
    )


def entry(
    purpose: str | None = "external", accepted: bool = False
) -> tuple[CadConstructionProps, bool]:
    return CadConstructionProps.model_validate({"purpose": purpose}), accepted


def test_moved_centroid_inside_new_shell_matches() -> None:
    old = wall("old", (0, 0, 5000, 200))
    new = wall("new", (500, 0, 5500, 200))
    assert is_same_construction(old, new)
    assert match_orphan_props({"old": old}, {"old": entry()}, [new], set()) == {"old": "new"}


def test_new_centroid_inside_old_shell_matches_when_old_centroid_is_outside() -> None:
    # Г-образная старая стена: её центроид в углу вне контура, центроид новой - внутри старой.
    old = wall("old", (0, 0, 4000, 200))
    old = old.model_copy(update={"centroid": [9000.0, 9000.0]})
    new = wall("new", (1000, 0, 3000, 200))
    assert is_same_construction(old, new)


def test_centroid_in_hole_does_not_count() -> None:
    hole = [[2000.0, 50.0], [3000.0, 50.0], [3000.0, 150.0], [2000.0, 150.0]]
    old = wall("old", holes=[hole])
    new = wall("new", holes=[hole])
    # Оба центроида (2500, 100) лежат в отверстиях контуров: внутри кольца их нет.
    assert not is_same_construction(old, new)
    assert is_same_construction(wall("old"), new)


def test_split_wall_is_unresolved() -> None:
    old = wall("old", (0, 0, 5000, 200))
    halves = [wall("a", (0, 0, 2600, 200)), wall("b", (2400, 0, 5000, 200))]
    assert match_orphan_props({"old": old}, {"old": entry()}, halves, set()) == {}


def test_merge_with_equal_props_is_carried_for_all_orphans() -> None:
    first = wall("a", (0, 0, 3000, 200))
    second = wall("b", (3000, 0, 6000, 200))
    merged = wall("m", (0, 0, 6000, 200))
    moves = match_orphan_props(
        {"a": first, "b": second}, {"a": entry(), "b": entry()}, [merged], set()
    )
    assert moves == {"a": "m", "b": "m"}


def test_merge_with_different_props_is_unresolved() -> None:
    first = wall("a", (0, 0, 3000, 200))
    second = wall("b", (3000, 0, 6000, 200))
    merged = wall("m", (0, 0, 6000, 200))
    for other in (entry("interior"), entry(accepted=True)):
        moves = match_orphan_props(
            {"a": first, "b": second}, {"a": entry(), "b": other}, [merged], set()
        )
        assert moves == {}


def test_target_with_its_own_props_is_unresolved() -> None:
    old = wall("old")
    new = wall("new")
    assert match_orphan_props({"old": old}, {"old": entry()}, [new], {"new"}) == {}


def test_thickness_kind_and_missing_nominal_must_agree() -> None:
    old = wall("old", nominal=200.0)
    assert not is_same_construction(old, wall("new", nominal=100.0))
    assert not is_same_construction(old, wall("new", nominal=None))
    assert not is_same_construction(old, wall("new", kind="monolith_wall"))
    assert is_same_construction(wall("o", nominal=None), wall("n", nominal=None))


def test_area_ratio_must_stay_within_half_and_double() -> None:
    old = wall("old", (0, 0, 5000, 200))
    assert is_same_construction(old, wall("new", (0, 0, 2500, 200)))
    assert is_same_construction(old, wall("new", (0, 0, 10000, 200)))
    assert not is_same_construction(old, wall("new", (0, 0, 2400, 200)))
    assert not is_same_construction(old, wall("new", (0, 0, 10100, 200)))


def test_one_orphan_with_two_candidates_is_unresolved() -> None:
    old = wall("old")
    twins = [wall("a"), wall("b")]
    assert match_orphan_props({"old": old}, {"old": entry()}, twins, set()) == {}
