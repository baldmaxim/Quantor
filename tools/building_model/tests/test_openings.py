import pytest

from building_model.canonical import BuildingModel, OpeningOut
from tests.synth import build, door, gap_item, make_sheet, wall

MAIN = wall("W0", (0, 0), (5000, 0))


def _only(model: BuildingModel) -> OpeningOut:
    assert len(model.openings) == 1
    return model.openings[0]


def _codes(model: BuildingModel) -> list[str]:
    return [i.code for i in model.review.items]


def test_window_host_and_offset() -> None:
    model = build(make_sheet(walls=[MAIN], windows=[gap_item("O0", (2000, 0), (3000, 0))]))
    opening = _only(model)
    assert opening.kind == "window"
    assert opening.host == model.walls[0].key
    assert opening.offset_mm == 2500.0
    assert opening.width_mm == 1000.0


def test_offset_counts_from_canonical_wall_start_not_from_input_direction() -> None:
    reverse = wall("W0", (5000, 0), (0, 0))
    model = build(make_sheet(walls=[reverse], windows=[gap_item("O0", (3000, 0), (2000, 0))]))
    assert _only(model).offset_mm == 2500.0


def test_statuses_observed_derived_assumed() -> None:
    sheet = make_sheet(
        walls=[MAIN],
        windows=[gap_item("O0", (2000, 0), (3000, 0))],
        doors=[door("D0", (3500, 0), (4400, 0), (3500, 900), 900)],
    )
    model = build(sheet)
    window = next(o for o in model.openings if o.kind == "window")
    leaf = next(o for o in model.openings if o.kind == "door")
    assert window.status.width_mm == "observed"
    assert window.status.sill_mm == "assumed"
    assert window.status.height_mm == "assumed"
    assert window.status.offset_mm == "derived"
    assert (window.sill_mm, window.height_mm) == (900.0, 1500.0)
    assert leaf.status.width_mm == "observed"
    assert leaf.status.height_mm == "assumed"
    assert leaf.status.swing == "derived"
    assert (leaf.height_mm, leaf.sill_mm) == (2100.0, None)


def test_void_opening_uses_window_parameters() -> None:
    model = build(make_sheet(walls=[MAIN], openings=[gap_item("H0", (1000, 0), (1800, 0))]))
    opening = _only(model)
    assert opening.kind == "opening"
    assert opening.host == model.walls[0].key
    assert (opening.sill_mm, opening.height_mm) == (900.0, 1500.0)


def test_no_host_is_reported_and_host_is_null() -> None:
    model = build(make_sheet(walls=[MAIN], windows=[gap_item("O0", (0, 3000), (1000, 3000))]))
    assert _only(model).host is None
    assert "opening_no_host" in _codes(model)


def test_window_outside_wall_projection_has_no_host() -> None:
    model = build(make_sheet(walls=[MAIN], windows=[gap_item("O0", (5200, 0), (6200, 0))]))
    assert _only(model).host is None


def test_window_across_the_wall_has_no_host() -> None:
    model = build(make_sheet(walls=[MAIN], windows=[gap_item("O0", (2500, -500), (2500, 500))]))
    assert _only(model).host is None


@pytest.mark.parametrize(("offset", "hosted"), [(250, True), (251, False)])
def test_host_distance_limit_is_half_thickness_plus_tolerance(offset: float, hosted: bool) -> None:
    window = gap_item("O0", (2000, offset), (3000, offset))
    model = build(make_sheet(walls=[MAIN], windows=[window]))
    assert (_only(model).host is not None) is hosted


def test_two_equal_candidates_mean_ambiguous_not_guessed() -> None:
    walls = [wall("W0", (0, 0), (5000, 0), t=200), wall("W1", (0, 10), (5000, 10), t=300)]
    model = build(make_sheet(walls=walls, windows=[gap_item("O0", (2000, 5), (3000, 5))]))
    assert len(model.walls) == 2
    assert _only(model).host is None
    assert "opening_ambiguous_host" in _codes(model)


def test_clearly_nearer_candidate_wins() -> None:
    walls = [wall("W0", (0, 0), (5000, 0), t=200), wall("W1", (0, 80), (5000, 80), t=300)]
    model = build(make_sheet(walls=walls, windows=[gap_item("O0", (2000, 0), (3000, 0))]))
    nearest = next(w for w in model.walls if w.a[1] == 0.0)
    assert _only(model).host == nearest.key


def test_double_door_is_one_opening_with_two_leaves() -> None:
    left = door("D0", (2000, 0), (2500, 0), (2000, 500), 1000, leaves=2, width=500)
    right = door("D1", (3000, 0), (2500, 0), (3000, 500), 1000, leaves=2, width=500)
    model = build(make_sheet(walls=[MAIN], doors=[right, left]))
    opening = _only(model)
    assert opening.width_mm == 1000.0
    assert opening.source[0].plangeom_ids == ["D0", "D1"]
    assert opening.offset_mm == 2500.0
    assert opening.swing is not None
    assert [(s.hinge_at, s.opens_to) for s in opening.swing] == [("a", "left"), ("b", "left")]


def test_lone_double_leaf_is_a_single_opening_with_warning() -> None:
    left = door("D0", (2000, 0), (2500, 0), (2000, 500), 1000, leaves=2, width=500)
    model = build(make_sheet(walls=[MAIN], doors=[left]))
    assert len(model.openings) == 1
    assert "door_pair_missing" in _codes(model)


@pytest.mark.parametrize(
    ("hinge_x", "closed_x", "open_y", "expected"),
    [
        (2000, 2900, 900, ("a", "left")),
        (2000, 2900, -900, ("a", "right")),
        (2900, 2000, 900, ("b", "left")),
        (2900, 2000, -900, ("b", "right")),
    ],
)
def test_swing_side_and_hinge_end(
    hinge_x: float, closed_x: float, open_y: float, expected: tuple[str, str]
) -> None:
    leaf = door("D0", (hinge_x, 0), (closed_x, 0), (hinge_x, open_y), 900)
    model = build(make_sheet(walls=[MAIN], doors=[leaf]))
    swing = _only(model).swing
    assert swing is not None
    assert (swing[0].hinge_at, swing[0].opens_to) == expected


def test_swing_does_not_depend_on_end_a_end_b_order() -> None:
    leaf = door("D0", (2000, 0), (2000, 900), (2900, 0), 900)  # открытый конец записан первым
    swing = _only(build(make_sheet(walls=[MAIN], doors=[leaf]))).swing
    assert swing is not None
    assert (swing[0].hinge_at, swing[0].opens_to) == ("a", "left")


@pytest.mark.parametrize(
    ("gap", "warned"), [(1050, False), (1051, True), (749, True), (751, False)]
)
def test_door_leaf_vs_gap_threshold(gap: float, warned: bool) -> None:
    leaf = door("D0", (2000, 0), (2900, 0), (2000, 900), 900, gap=gap)
    model = build(make_sheet(walls=[MAIN], doors=[leaf]))
    assert ("door_leaf_vs_gap" in _codes(model)) is warned


def test_host_comparison_with_plangeom_is_counted() -> None:
    def stats(host: str | None) -> dict[str, object]:
        leaf = door("D0", (2000, 0), (2900, 0), (2000, 900), 900, host=host)
        model = build(make_sheet(walls=[MAIN], doors=[leaf]))
        opening_stats = model.stats["openings"]
        assert isinstance(opening_stats, dict)
        return dict(opening_stats)

    same = stats("W0")
    assert (same["door_host_compared_with_plangeom"], same["door_host_matches_plangeom"]) == (1, 1)
    other = stats("W9")
    assert (other["door_host_compared_with_plangeom"], other["door_host_matches_plangeom"]) == (
        1,
        0,
    )
    null = stats(None)
    assert (null["door_host_compared_with_plangeom"], null["door_host_plangeom_null"]) == (0, 1)
