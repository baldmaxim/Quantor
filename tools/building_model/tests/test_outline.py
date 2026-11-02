from building_model.canonical import BuildingModel
from tests.synth import JsonObj, build, make_sheet, sp, wall
from tests.test_determinism import _shuffled


def bare(
    wid: str,
    a: tuple[float, float],
    b: tuple[float, float],
    t: float = 200.0,
    role: str = "bearing wall",
) -> JsonObj:
    """Стена plangeom без осевых линий: есть только контур."""
    result = wall(wid, a, b, t, role)
    result["segments"] = []
    result["area_m2"] = 1.0
    return result


def _outline_stat(model: BuildingModel, outcome: str) -> dict[str, object]:
    walls = model.stats["walls"]
    assert isinstance(walls, dict)
    outline = walls["outline_axis"]
    assert isinstance(outline, dict)
    value = outline[outcome]
    assert isinstance(value, dict)
    return dict(value)


def _codes(model: BuildingModel) -> list[str]:
    return [i.code for i in model.review.items]


def test_rectangle_without_segments_gets_axis_and_derived_thickness() -> None:
    model = build(make_sheet(walls=[bare("W0", (0, 0), (4000, 0), t=300)]))
    assert len(model.walls) == 1
    w = model.walls[0]
    assert (w.a, w.b, w.thickness_mm) == ((0.0, 0.0), (4000.0, 0.0), 300.0)
    assert (w.axis_source, w.status, w.thickness_status) == ("outline", "derived", "derived")
    assert w.source[0].plangeom_ids == ["W0"]
    assert _outline_stat(model, "used")["walls"] == 1
    assert model.columns == []


def test_vertical_rectangle_axis_follows_the_long_side() -> None:
    vertical = bare("W0", (0, 0), (0, 3000), t=250)
    vertical["polygon_mm"] = [sp(-125, 0), sp(125, 0), sp(125, 3000), sp(-125, 3000)]
    w = build(make_sheet(walls=[vertical])).walls[0]
    assert (w.a, w.b, w.thickness_mm) == ((0.0, 0.0), (0.0, 3000.0), 250.0)


def test_segments_walls_keep_axis_source_segments_and_observed_thickness() -> None:
    w = build(make_sheet(walls=[wall("W0", (0, 0), (4000, 0))])).walls[0]
    assert (w.axis_source, w.status, w.thickness_status) == ("segments", "observed", "observed")


def test_compact_outline_is_not_a_wall_and_not_a_column() -> None:
    model = build(make_sheet(walls=[bare("W0", (0, 0), (300, 0), t=250)]))
    assert model.walls == []
    assert model.columns == []
    assert "wall_no_axis_compact" in _codes(model)
    assert _outline_stat(model, "compact")["walls"] == 1


def test_aspect_limit_is_inclusive() -> None:
    at_limit = build(make_sheet(walls=[bare("W0", (0, 0), (375, 0), t=250)]))
    below = build(make_sheet(walls=[bare("W0", (0, 0), (374, 0), t=250)]))
    assert len(at_limit.walls) == 1
    assert below.walls == []


def test_not_a_rectangle_gets_no_axis() -> None:
    trapezoid = bare("W0", (0, 0), (4000, 0))
    trapezoid["polygon_mm"] = [sp(0, 0), sp(4000, 0), sp(3500, 300), sp(500, 300)]
    triangle = bare("W1", (0, 1000), (4000, 1000))
    triangle["polygon_mm"] = [sp(0, 1000), sp(4000, 1000), sp(2000, 1500)]
    model = build(make_sheet(walls=[trapezoid, triangle]))
    assert model.walls == []
    assert _codes(model).count("wall_no_axis") == 2
    assert _outline_stat(model, "not_rectangle")["walls"] == 2


def test_corner_tolerance_five_degrees() -> None:
    def skewed(shift: float) -> JsonObj:
        w = bare("W0", (0, 0), (4000, 0))
        # сдвиг верхней грани: угол при вершине отличается от 90° на atan(shift / 200)
        w["polygon_mm"] = [sp(0, -100), sp(4000, -100), sp(4000 + shift, 100), sp(shift, 100)]
        return w

    assert len(build(make_sheet(walls=[skewed(15)])).walls) == 1  # около 4,3°
    assert build(make_sheet(walls=[skewed(25)])).walls == []  # около 7,1°


def test_thin_outline_is_filtered_like_ordinary_pieces() -> None:
    model = build(make_sheet(walls=[bare("W0", (0, 0), (4000, 0), t=40)]))
    assert model.walls == []
    item = next(i for i in model.review.items if i.code == "wall_rejected_thin")
    assert item.detail["outline"] == 1
    assert _outline_stat(model, "filtered")["walls"] == 1


def test_duplicate_of_real_axis_is_dropped() -> None:
    walls = [wall("W1", (0, 0), (4000, 0)), bare("W0", (0, 50), (4000, 50))]
    model = build(make_sheet(walls=walls))
    assert len(model.walls) == 1
    assert model.walls[0].axis_source == "segments"
    assert "wall_axis_duplicate" in _codes(model)
    assert _outline_stat(model, "duplicate")["walls"] == 1


def test_offset_beyond_half_thickness_is_not_a_duplicate() -> None:
    walls = [wall("W1", (0, 0), (4000, 0), t=200), bare("W0", (0, 101), (4000, 101), t=100)]
    model = build(make_sheet(walls=walls))
    assert len(model.walls) == 2


def test_duplicate_share_threshold_is_half_of_the_axis_length() -> None:
    def walls_for(real_end: float) -> JsonObj:
        return make_sheet(walls=[wall("W1", (0, 0), (real_end, 0)), bare("W0", (0, 0), (4000, 0))])

    assert "wall_axis_duplicate" in _codes(build(walls_for(2000)))
    assert "wall_axis_duplicate" not in _codes(build(walls_for(1999)))


def test_duplicate_is_checked_only_against_real_axes() -> None:
    model = build(make_sheet(walls=[bare("W0", (0, 0), (4000, 0)), bare("W1", (0, 0), (4000, 0))]))
    assert len(model.walls) == 1  # наложение склеено, дублем не помечено
    assert "wall_axis_duplicate" not in _codes(model)


def test_outline_joins_real_pieces_into_mixed_wall() -> None:
    model = build(
        make_sheet(walls=[wall("W0", (0, 0), (2000, 0)), bare("W1", (2000, 0), (4000, 0))])
    )
    assert len(model.walls) == 1
    w = model.walls[0]
    assert (w.a, w.b) == ((0.0, 0.0), (4000.0, 0.0))
    assert (w.axis_source, w.status, w.thickness_status) == ("mixed", "derived", "derived")
    assert w.source[0].plangeom_ids == ["W0", "W1"]


def test_outline_wall_is_found_as_host() -> None:
    from tests.synth import gap_item

    sheet = make_sheet(
        walls=[bare("W0", (0, 0), (5000, 0))], windows=[gap_item("O0", (2000, 0), (3000, 0))]
    )
    model = build(sheet)
    assert model.openings[0].host == model.walls[0].key


def test_key_does_not_depend_on_polygon_direction() -> None:
    forward = bare("W0", (0, 0), (4000, 0))
    backward = bare("W0", (0, 0), (4000, 0))
    polygon = backward["polygon_mm"]
    assert isinstance(polygon, list)
    backward["polygon_mm"] = list(reversed(polygon))
    assert build(make_sheet(walls=[forward])).walls[0].key == (
        build(make_sheet(walls=[backward])).walls[0].key
    )


def test_shuffled_input_with_outline_walls_is_byte_identical() -> None:
    from building_model.pipeline import dumps_model

    sheet = make_sheet(
        walls=[
            wall("W0", (0, 0), (2000, 0)),
            bare("W1", (2000, 0), (4000, 0)),
            bare("W2", (0, 30), (4000, 30)),
            bare("W3", (0, 3000), (300, 3000), t=250),
            bare("W4", (0, 5000), (1500, 5000)),
            wall("W5", (0, 5030), (800, 5030)),
        ]
    )
    reference = dumps_model(build(sheet))
    for seed in range(5):
        assert dumps_model(build(_shuffled(sheet, seed))) == reference
