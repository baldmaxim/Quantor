from building_model.canonical import BuildingModel
from tests.synth import build, document, make_sheet, sp, wall

SQUARE = [sp(0, 0), sp(10000, 0), sp(10000, 8000), sp(0, 8000)]


def _codes(model: BuildingModel, severity: str | None = None) -> list[str]:
    return [i.code for i in model.review.items if severity in (None, i.severity)]


def test_single_level_observed_elevation_and_assumed_height() -> None:
    model = build(make_sheet())
    assert len(model.levels) == 1
    level = model.levels[0]
    assert (level.key, level.floor, level.elevation_mm) == ("L3", 3, 9900.0)
    assert level.height_mm == 3300.0
    assert level.status.elevation_mm == "observed"
    assert level.status.height_mm == "assumed"
    assert level.instance_of is None


def test_height_from_neighbour_level_is_derived() -> None:
    lower = make_sheet(page=0)
    upper = make_sheet(
        page=1, title={"floors": [4], "level_m": 13.2}, floor_level={"level_m": 13.2}
    )
    doc = document(lower, upper, buildings=[{"sheets": [0, 1]}])
    from building_model.pipeline import TenderArgs, build_model

    level = build_model(doc, 0, TenderArgs()).levels[0]
    assert level.height_mm == 3300.0
    assert level.status.height_mm == "derived"
    top = build_model(doc, 1, TenderArgs()).levels[0]
    assert top.status.height_mm == "assumed"


def test_implausible_neighbour_difference_falls_back_to_parameter() -> None:
    lower = make_sheet(page=0)
    upper = make_sheet(
        page=1, title={"floors": [9], "level_m": 20.0}, floor_level={"level_m": 20.0}
    )
    doc = document(lower, upper, buildings=[{"sheets": [0, 1]}])
    from building_model.pipeline import TenderArgs, build_model

    model = build_model(doc, 0, TenderArgs())
    assert model.levels[0].status.height_mm == "assumed"
    assert "level_height_implausible" in _codes(model, "warning")


def test_typical_sheet_gives_instances_without_copying_geometry() -> None:
    sheet = make_sheet(
        title={"floors": [5, 6], "level_m": 14.0, "levels_m": [14.0, 17.3]},
        walls=[wall("W0", (0, 0), (4000, 0))],
    )
    model = build(sheet)
    assert [(lv.key, lv.instance_of, lv.elevation_mm) for lv in model.levels] == [
        ("L5", None, 14000.0),
        ("L6", "L5", 17300.0),
    ]
    assert model.levels[0].status.height_mm == "derived"
    assert model.levels[0].height_mm == 3300.0
    assert [w.level for w in model.walls] == ["L5"]
    assert len(model.walls) == 1


def test_typical_sheet_without_second_elevation_is_assumed() -> None:
    sheet = make_sheet(title={"floors": [5, 6], "level_m": 14.0})
    model = build(sheet)
    upper = model.levels[1]
    assert upper.elevation_mm == 17300.0
    assert upper.status.elevation_mm == "assumed"
    assert model.levels[0].status.elevation_mm == "observed"


def test_missing_elevation_is_blocker() -> None:
    model = build(make_sheet(title=None, floor_level=None))
    assert "level_unknown" in _codes(model, "blocker")
    assert model.levels[0].elevation_mm is None


def test_scale_always_needs_human_in_m1() -> None:
    model = build(make_sheet())
    assert _codes(model, "blocker") == ["scale_needs_human"]


def test_unconfirmed_scale_adds_blocker() -> None:
    weak = build(make_sheet(scale={"mm_per_pt": 35.0, "method": "none", "confident": False}))
    assert _codes(weak, "blocker") == ["scale_needs_human", "scale_not_confirmed"]
    disagree = build(
        make_sheet(
            scale={
                "mm_per_pt": 35.0,
                "method": "axes",
                "confident": True,
                "disagrees_with_printed": True,
            }
        )
    )
    assert "scale_not_confirmed" in _codes(disagree, "blocker")
    assert disagree.review.blockers == 2


def test_slab_has_holes_from_stairs_and_shafts_and_assumed_thickness() -> None:
    sheet = make_sheet(
        slab_outlines_mm=[SQUARE],
        stairs=[
            {
                "id": "T0",
                "polygon_mm": [sp(1000, 1000), sp(3000, 1000), sp(3000, 4000), sp(1000, 4000)],
                "slab_opening_mm": [sp(1000, 1000), sp(3000, 1000), sp(3000, 4000), sp(1000, 4000)],
            },
            {
                "id": "T1",
                "polygon_mm": [sp(20000, 0), sp(21000, 0), sp(21000, 1000)],
                "slab_opening_mm": [sp(20000, 0), sp(21000, 0), sp(21000, 1000)],
            },
        ],
        rooms=[
            {
                "id": "R0",
                "type": "shaft",
                "area_m2": 1.0,
                "polygon_mm": [sp(6000, 6000), sp(7000, 6000), sp(7000, 7000), sp(6000, 7000)],
            }
        ],
    )
    model = build(sheet)
    assert len(model.slabs) == 1
    slab = model.slabs[0]
    assert slab.thickness_mm == 200.0
    assert (slab.status.outline, slab.status.thickness_mm) == ("observed", "assumed")
    assert sorted(h.kind for h in slab.holes) == ["shaft", "stair"]
    assert all(h.status == "derived" for h in slab.holes)
    assert "slab_hole_outside" in _codes(model, "warning")
    assert [s.kind for s in model.stacks] == ["stair", "stair"]


def test_rooms_skip_facade_cavity_and_compare_with_schedule() -> None:
    def room(rid: str, kind: str, area: float, schedule: float | None) -> dict[str, object]:
        return {
            "id": rid,
            "type": kind,
            "type_source": "name",
            "area_m2": area,
            "schedule_area_m2": schedule,
            "tag": rid,
            "polygon_mm": [sp(0, 0), sp(1000, 0), sp(1000, 1000), sp(0, 1000)],
        }

    sheet = make_sheet(
        rooms=[
            room("R0", "living", 10.0, 12.0),
            room("R1", "living", 10.0, 10.5),
            room("R2", "facade cavity", 5.0, None),
            room("R3", "lift", 3.0, None),
        ]
    )
    model = build(sheet)
    assert sorted(r.tag or "" for r in model.rooms) == ["R0", "R1", "R3"]
    assert _codes(model).count("room_area_vs_schedule") == 1
    assert model.rooms[0].status.type == "observed"
    assert [s.kind for s in model.stacks] == ["lift"]
    rooms_stats = model.stats["rooms"]
    assert isinstance(rooms_stats, dict)
    assert rooms_stats["compared_with_schedule"] == 2
