import json
from pathlib import Path

import pytest

from building_model.approval import ApprovalOut
from building_model.canonical import BuildingModel, ReviewItem
from building_model.geometry import point_in_polygon
from building_model.pipeline import dumps_model
from building_model.revit import (
    RevitRefusalError,
    build_package,
    wall_type_class,
    weakest,
)
from building_model.revit_format import (
    ADAPTER_VERSION,
    RevitPackage,
    dumps_package,
    package_json_schema,
)
from tests.revit_fixture import (
    EXAMPLE_PATH,
    example_text,
    model_sha,
    synthetic_approval,
    synthetic_model,
    synthetic_package,
)

DOCS = Path(__file__).resolve().parents[3] / "docs" / "building-model"


def _reasons(package: RevitPackage) -> dict[str, str]:
    return {f"{n.kind}:{n.key}": n.reason for n in package.not_exported}


def _approved(model: BuildingModel) -> RevitPackage:
    return build_package(model, synthetic_approval(model), model_sha(model))


def test_adapter_version_is_constant() -> None:
    assert ADAPTER_VERSION == "0.1.0"
    assert synthetic_package().manifest.adapter.version == "0.1.0"


def test_approved_package_manifest() -> None:
    package = synthetic_package()
    manifest = package.manifest
    assert manifest.scale_status == "human"
    assert manifest.approval is not None
    assert manifest.page == 0
    assert manifest.units == "mm"
    assert manifest.origin.y == "up"
    assert package.draft_format is True
    assert manifest.assumptions.params.door_height_mm == 2100.0
    assert manifest.review_summary.blocker == {"scale_needs_human": 1}


def test_unapproved_test_package_is_a_candidate() -> None:
    model = synthetic_model()
    package = build_package(model, None, model_sha(model))
    assert package.manifest.approval is None
    assert package.manifest.scale_status == "candidate"
    assert package.manifest.page == 0


def test_coverage_invariant_and_nothing_disappears() -> None:
    model = synthetic_model()
    package = _approved(model)
    totals = {
        "walls": len(model.walls),
        "openings": len(model.openings),
        "floors": len(model.slabs),
        "floor_holes": sum(len(s.holes) for s in model.slabs),
        "columns": len(model.columns),
        "stacks": len(model.stacks),
        "rooms": len(model.rooms),
    }
    for kind, cov in package.manifest.coverage.items():
        assert cov.exported + cov.not_exported == cov.total == totals[kind]
    exported = {
        "walls": len(package.walls),
        "openings": len(package.openings),
        "floors": len(package.floors),
        "columns": len(package.columns),
        "stacks": len(package.stacks),
        "rooms": len(package.rooms),
    }
    for kind, count in exported.items():
        assert package.manifest.coverage[kind].exported == count
    assert len(package.not_exported) == sum(
        c.not_exported for c in package.manifest.coverage.values()
    )


def test_opening_without_host_is_reported() -> None:
    package = synthetic_package()
    assert list(_reasons(package).values()) == ["no_host"]
    assert package.not_exported[0].kind == "opening"
    assert package.not_exported[0].at is not None


def test_levels_instances_and_no_geometry_copies() -> None:
    package = synthetic_package()
    assert [(lv.id, lv.instance_of, lv.elevation_mm) for lv in package.levels] == [
        ("L5", None, 14000.0),
        ("L6", "L5", 17300.0),
    ]
    assert {w.level for w in package.walls} == {"L5"}
    assert {w.height_mm for w in package.walls} == {3300.0}


def test_wall_types_structural_and_params() -> None:
    package = synthetic_package()
    assert [(t.id, t.thickness_mm, t.count) for t in package.wall_types] == [
        ("QTO-W-100", 100.0, 1),
        ("QTO-W-300", 300.0, 4),
    ]
    by_thickness = {w.thickness_mm: w for w in package.walls}
    assert by_thickness[300.0].structural is True
    assert by_thickness[100.0].structural is False
    for w in package.walls:
        assert w.params["QTO_Key"] == w.id
        assert w.params["QTO_Source"].startswith("p0:W")
        assert w.params["QTO_Status"] in ("observed", "derived")


def test_wall_type_rounding_to_10_mm() -> None:
    assert [wall_type_class(t) for t in (152.0, 154.9, 155.0, 205.0, 95.0)] == [
        150,
        150,
        160,
        210,
        100,
    ]


def test_opening_status_is_weakest_and_door_has_swing() -> None:
    package = synthetic_package()
    assert {o.params["QTO_Status"] for o in package.openings} == {"assumed"}
    door = next(o for o in package.openings if o.kind == "door")
    assert door.offset_mm == 1500.0
    assert door.width_mm == 1000.0
    assert door.swing is not None
    assert [(s.hinge_at, s.opens_to) for s in door.swing] == [("a", "left")]
    window = next(o for o in package.openings if o.kind == "window")
    assert window.swing is None
    assert window.sill_mm == 900.0


def test_weakest_status_order() -> None:
    assert weakest(["observed", "derived"]) == "derived"
    assert weakest(["observed", "assumed", "derived"]) == "assumed"
    assert weakest(["human", "observed"]) == "observed"
    assert weakest(["human", None]) == "human"
    with pytest.raises(ValueError):
        weakest([None])


def test_floor_status_includes_assumed_thickness_and_holes() -> None:
    package = synthetic_package()
    floor = package.floors[0]
    assert floor.params["QTO_Status"] == "assumed"
    assert floor.thickness_mm == 200.0
    assert [h.kind for h in floor.holes] == ["stair"]
    assert package.manifest.assumptions.assumed_elements["floors"] == 1
    assert package.manifest.assumptions.assumed_elements["levels"] == 1


def test_rooms_point_is_inside_even_for_concave_boundary() -> None:
    package = synthetic_package()
    assert len(package.rooms) == 2
    for room in package.rooms:
        assert point_in_polygon(room.point, room.boundary)


def test_stacks_and_columns_have_outline_only() -> None:
    package = synthetic_package()
    assert len(package.columns) == 1
    assert package.columns[0].height_mm == 3300.0
    assert package.stacks[0].kind == "stair"
    assert package.stacks[0].slab_opening is not None


def test_refuses_sha_mismatch() -> None:
    model = synthetic_model()
    with pytest.raises(RevitRefusalError, match="sha256"):
        build_package(model, synthetic_approval(model), "0" * 64)


def test_refuses_page_mismatch() -> None:
    model = synthetic_model()
    wrong = synthetic_approval(model).model_copy(update={"page": 7})
    with pytest.raises(RevitRefusalError, match="страниц"):
        build_package(model, wrong, model_sha(model))


def _with_blocker(model: BuildingModel, code: str) -> BuildingModel:
    item = ReviewItem(
        code=code, severity="blocker", element=None, source_ids=[], at=None, detail={}
    )
    review = model.review.model_copy(update={"items": [*model.review.items, item]})
    return model.model_copy(update={"review": review})


def test_other_blockers_always_refuse() -> None:
    model = _with_blocker(synthetic_model(), "no_axes_origin")
    with pytest.raises(RevitRefusalError, match="no_axes_origin"):
        _approved(model)
    with pytest.raises(RevitRefusalError, match="no_axes_origin"):
        build_package(model, None, model_sha(model))


def test_scale_blockers_are_lifted_only_by_the_approval_path() -> None:
    model = _with_blocker(synthetic_model(), "scale_not_confirmed")
    assert _approved(model).manifest.scale_status == "human"
    assert build_package(model, None, model_sha(model)).manifest.scale_status == "candidate"


def test_level_without_elevation_refuses() -> None:
    model = synthetic_model()
    levels = [model.levels[0].model_copy(update={"elevation_mm": None}), *model.levels[1:]]
    with pytest.raises(RevitRefusalError, match="без отметки"):
        _approved(model.model_copy(update={"levels": levels}))


def test_all_refusal_reasons_are_listed_together() -> None:
    model = _with_blocker(synthetic_model(), "level_unknown")
    with pytest.raises(RevitRefusalError) as info:
        build_package(model, synthetic_approval(model), "0" * 64)
    assert "sha256" in str(info.value)
    assert "level_unknown" in str(info.value)


def test_not_exported_reasons_for_modified_model() -> None:
    model = synthetic_model()
    long_wall = next(w for w in model.walls if w.thickness_mm == 100.0)
    zero = long_wall.model_copy(update={"b": long_wall.a})
    host_ops = [o for o in model.openings if o.host == long_wall.key]
    assert host_ops == []
    windows = [o for o in model.openings if o.kind == "window" and o.host is not None]
    far, wide = windows[0], windows[1]
    openings = [o for o in model.openings if o.key not in (far.key, wide.key)] + [
        far.model_copy(update={"offset_mm": 99999.0}),
        wide.model_copy(update={"width_mm": 99999.0}),
    ]
    flat_room = model.rooms[0].model_copy(update={"polygon": model.rooms[0].polygon[:2]})
    flat_column = model.columns[0].model_copy(update={"polygon": model.columns[0].polygon[:2]})
    slab = model.slabs[0]
    broken_hole = slab.holes[0].model_copy(update={"polygon": slab.holes[0].polygon[:2]})
    ambiguous_op = next(o for o in model.openings if o.host is None)
    ambiguity = ReviewItem(
        code="opening_ambiguous_host",
        severity="warning",
        element=ambiguous_op.key,
        source_ids=[],
        at=None,
        detail={},
    )
    review = model.review.model_copy(update={"items": [*model.review.items, ambiguity]})
    changed = model.model_copy(
        update={
            "walls": [zero if w.key == zero.key else w for w in model.walls],
            "openings": openings,
            "rooms": [flat_room, *model.rooms[1:]],
            "columns": [flat_column],
            "slabs": [slab.model_copy(update={"holes": [broken_hole]})],
            "review": review,
        }
    )
    package = _approved(changed)
    reasons = _reasons(package)
    assert reasons[f"wall:{zero.key}"] == "zero_length_wall"
    assert reasons[f"opening:{far.key}"] == "offset_outside_host"
    assert reasons[f"opening:{wide.key}"] == "wider_than_host"
    assert reasons[f"opening:{ambiguous_op.key}"] == "ambiguous_host"
    assert reasons[f"room:{flat_room.key}"] == "degenerate_polygon"
    assert reasons[f"column:{flat_column.key}"] == "degenerate_polygon"
    assert reasons[f"floor_hole:{slab.key}#hole0"] == "degenerate_polygon"
    for kind, cov in package.manifest.coverage.items():
        assert cov.exported + cov.not_exported == cov.total, kind


def test_opening_on_removed_host_is_not_exported() -> None:
    model = synthetic_model()
    wall = model.walls[0]
    zero = wall.model_copy(update={"b": wall.a})
    package = _approved(model.model_copy(update={"walls": [zero, *model.walls[1:]]}))
    reasons = _reasons(package)
    hosted_on_zero = [o for o in model.openings if o.host == zero.key]
    for op in hosted_on_zero:
        assert reasons[f"opening:{op.key}"] == "no_host"


def test_holes_of_degenerate_floor_are_reported() -> None:
    model = synthetic_model()
    slab = model.slabs[0].model_copy(update={"polygon": model.slabs[0].polygon[:2]})
    package = _approved(model.model_copy(update={"slabs": [slab]}))
    reasons = _reasons(package)
    assert reasons[f"floor:{slab.key}"] == "degenerate_polygon"
    assert reasons[f"floor_hole:{slab.key}#hole0"] == "no_host"
    assert package.manifest.coverage["floor_holes"].exported == 0


def test_output_is_deterministic_and_survives_model_roundtrip() -> None:
    first = dumps_package(synthetic_package())
    assert first == dumps_package(synthetic_package())
    model = synthetic_model()
    restored = BuildingModel.model_validate_json(dumps_model(model))
    assert dumps_package(_approved(restored)) == first
    assert "seconds" not in first


def test_schema_aliases_in_output() -> None:
    data = json.loads(dumps_package(synthetic_package()))
    assert data["schema"] == "quantor.revit_package.v0"
    assert data["draft_format"] is True
    assert list(data)[:3] == ["schema", "draft_format", "manifest"]


def test_schema_file_matches_model() -> None:
    assert (DOCS / "revit-package-v0.schema.json").read_text(
        encoding="utf-8"
    ) == package_json_schema()


def test_example_file_matches_fixture() -> None:
    assert EXAMPLE_PATH.read_text(encoding="utf-8") == example_text()


def test_approval_model_forbids_extra_fields() -> None:
    with pytest.raises(ValueError):
        ApprovalOut.model_validate(
            {"page": 0, "model_sha256": "x", "mm_per_pt": 1.0, "by": "a", "at": "t", "extra": 1}
        )
