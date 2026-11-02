from building_model.canonical import BuildingModel
from tests.synth import build, door, gap_item, make_sheet, sp, wall


def _walls_with_gap(gap: float) -> list[dict[str, object]]:
    return [wall("W0", (0, 0), (2000, 0)), wall("W1", (2000 + gap, 0), (5000, 0))]


def _door_in_gap(opening: float, gap: float) -> dict[str, object]:
    return door("D0", (2000, 0), (2000 + gap, 0), (2000, gap), opening)


def _stat(model: BuildingModel, section: str, name: str) -> object:
    value = model.stats[section]
    assert isinstance(value, dict)
    return value[name]


def test_collinear_pieces_merge_through_gap_with_door() -> None:
    model = build(make_sheet(walls=_walls_with_gap(1000), doors=[_door_in_gap(1000, 1000)]))
    assert len(model.walls) == 1
    assert (model.walls[0].a, model.walls[0].b) == ((0.0, 0.0), (5000.0, 0.0))
    assert model.walls[0].bridged_openings == ["D0"]
    assert model.walls[0].status == "derived"


def test_same_gap_without_opening_is_not_merged() -> None:
    model = build(make_sheet(walls=_walls_with_gap(1000)))
    assert len(model.walls) == 2


def test_gap_limit_is_opening_width_plus_slack() -> None:
    inside = build(make_sheet(walls=_walls_with_gap(950), doors=[_door_in_gap(800, 950)]))
    outside = build(make_sheet(walls=_walls_with_gap(951), doors=[_door_in_gap(800, 951)]))
    assert len(inside.walls) == 1
    assert len(outside.walls) == 2


def test_window_in_gap_bridges_too() -> None:
    sheet = make_sheet(walls=_walls_with_gap(1000), windows=[gap_item("O0", (2000, 0), (3000, 0))])
    model = build(sheet)
    assert len(model.walls) == 1
    assert model.walls[0].bridged_openings == ["O0"]


def test_join_gap_threshold_without_opening() -> None:
    assert len(build(make_sheet(walls=_walls_with_gap(50))).walls) == 1
    assert len(build(make_sheet(walls=_walls_with_gap(51))).walls) == 2


def test_opening_far_from_gap_does_not_bridge() -> None:
    far = door("D0", (20000, 0), (20900, 0), (20000, 900), 900)
    model = build(make_sheet(walls=_walls_with_gap(900), doors=[far]))
    assert len(model.walls) == 2


def test_thin_and_short_pieces_are_rejected_but_kept_in_review() -> None:
    sheet = make_sheet(
        walls=[
            wall("W0", (0, 0), (4000, 0), t=40),
            wall("W1", (0, 1000), (80, 1000), t=200),
            wall("W2", (0, 2000), (4000, 2000), t=60),
            wall("W3", (0, 3000), (100, 3000), t=200),
        ]
    )
    model = build(sheet)
    assert len(model.walls) == 2  # t=60 и длина 100 проходят: пороги строгие «меньше»
    codes = [i.code for i in model.review.items if i.code.startswith("wall_rejected")]
    assert sorted(codes) == ["wall_rejected_short", "wall_rejected_thin"]
    rejected = [i for i in model.review.items if i.code.startswith("wall_rejected")]
    assert all(i.a is not None and i.b is not None for i in rejected)
    assert _stat(model, "walls", "rejected_thin") == 1
    assert _stat(model, "walls", "rejected_short") == 1


def test_column_goes_to_columns_not_walls() -> None:
    column = wall("W0", (0, 0), (400, 0), t=400, role="column")
    model = build(make_sheet(walls=[column, wall("W1", (0, 2000), (4000, 2000))]))
    assert len(model.columns) == 1
    assert len(model.walls) == 1
    assert model.columns[0].source[0].plangeom_ids == ["W0"]


def test_different_thickness_classes_do_not_merge() -> None:
    sheet = make_sheet(
        walls=[wall("W0", (0, 0), (2000, 0), t=200), wall("W1", (2000, 0), (4000, 0), t=300)]
    )
    assert len(build(sheet).walls) == 2


def test_thickness_within_tolerance_merges() -> None:
    sheet = make_sheet(
        walls=[wall("W0", (0, 0), (2000, 0), t=200), wall("W1", (2000, 0), (4000, 0), t=209)]
    )
    model = build(sheet)
    assert len(model.walls) == 1
    assert 200.0 < model.walls[0].thickness_mm < 209.0


def test_axis_distance_tolerance() -> None:
    near = make_sheet(walls=[wall("W0", (0, 0), (2000, 0)), wall("W1", (1900, 29), (4000, 29))])
    far = make_sheet(walls=[wall("W0", (0, 0), (2000, 0)), wall("W1", (1900, 31), (4000, 31))])
    assert len(build(near).walls) == 1
    assert len(build(far).walls) == 2


def test_angle_tolerance() -> None:
    skew = make_sheet(walls=[wall("W0", (0, 0), (5000, 0)), wall("W1", (5000, 0), (10000, 175))])
    assert len(build(skew).walls) == 2


def test_overlapping_duplicates_do_not_double_length() -> None:
    sheet = make_sheet(walls=[wall("W0", (0, 0), (4000, 0)), wall("W1", (1000, 0), (3000, 0))])
    model = build(sheet)
    assert len(model.walls) == 1
    assert (model.walls[0].a, model.walls[0].b) == ((0.0, 0.0), (4000.0, 0.0))


def test_walls_are_not_extended_and_dangling_ends_are_counted() -> None:
    connected = make_sheet(
        walls=[wall("W0", (0, 0), (5000, 0)), wall("W1", (2500, 100), (2500, 3000))]
    )
    model = build(connected)
    # свободны: оба конца горизонтальной стены и верхний конец вертикальной
    assert _stat(model, "walls", "dangling_ends") == 3
    free = make_sheet(walls=[wall("W0", (0, 0), (5000, 0)), wall("W1", (2500, 400), (2500, 3000))])
    model = build(free)
    assert _stat(model, "walls", "dangling_ends") == 4
    vertical = [w for w in model.walls if w.a[0] == 2500.0 and w.b[0] == 2500.0]
    assert (vertical[0].a, vertical[0].b) == ((2500.0, 400.0), (2500.0, 3000.0))
    codes = [i.code for i in model.review.items]
    assert codes.count("wall_dangling_end") == 4


def test_dangling_gap_to_nearest_face_is_reported_in_bands() -> None:
    free = make_sheet(walls=[wall("W0", (0, 0), (5000, 0)), wall("W1", (2500, 400), (2500, 3000))])
    histogram = _stat(build(free), "walls", "dangling_gap_to_face_mm")
    assert isinstance(histogram, dict)
    # конец вертикальной стены: 400 до оси, 300 до грани; концы горизонтальной далеко
    assert histogram["200-400"] == 1
    assert sum(histogram.values()) == 4


def test_wall_without_axis_is_not_lost_silently() -> None:
    bare = wall("W0", (0, 0), (4000, 0))
    bare["segments"] = []
    bare["area_m2"] = 0.8
    bare["polygon_mm"] = [sp(0, 0), sp(1000, 0), sp(500, 700)]  # не прямоугольник
    model = build(make_sheet(walls=[bare, wall("W1", (0, 2000), (4000, 2000))]))
    assert len(model.walls) == 1
    assert _stat(model, "walls", "without_segments") == 1
    assert _stat(model, "walls", "without_segments_area_m2") == 0.8
    assert [i.code for i in model.review.items].count("wall_no_axis") == 1
