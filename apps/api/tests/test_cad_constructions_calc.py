"""Расчёт величин конструкций (ADR-0038 п. 3): чистые функции без базы.

Независимый пересчёт: ожидаемые числа выписаны руками из формул модуля `cad_constructions`.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadSheetLevelsRead,
    WallsConstruction,
    WallsDocument,
    WallsOpening,
)
from app.services import cad_construction_store as store
from app.services import cad_constructions as calc

NO_LEVELS = CadSheetLevelsRead(floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None)


def construction(
    key: str = "c1",
    *,
    kind: str = "masonry",
    nominal: float | None = 200.0,
    area: float = 1_000_000.0,
    axis: float = 5000.0,
) -> dict[str, Any]:
    return {
        "id": key,
        "kind": kind,
        "source_layers": ["01_КЛАДКА_И_ПЕРЕГОРОДКИ"],
        "polygon": {
            "shell": [[0.0, 0.0], [5000.0, 0.0], [5000.0, 200.0], [0.0, 200.0]],
            "holes": [],
        },
        "area_plan_mm2": area,
        "thickness_measured_mm": nominal or 137.0,
        "thickness_nominal_mm": nominal,
        "thickness_status": "matched" if nominal is not None else "check",
        "length_axis_mm": axis,
        "centroid": [2500.0, 100.0],
        "bbox": [0.0, 0.0, 5000.0, 200.0],
    }


def opening(
    key: str, host: str | None, *, kind: str = "door", status: str = "ok", width: float = 1000.0
) -> dict[str, Any]:
    return {
        "id": key,
        "kind": kind,
        "status": status,
        "host_id": host,
        "adjacent_ids": [] if host is None else [host],
        "width_mm": width,
        "width_source": "gap",
        "thickness_mm": 200.0,
        "block_name": None,
        "handle": None,
        "center": [0.0, 0.0],
    }


def document(
    constructions: list[dict[str, Any]],
    openings: list[dict[str, Any]] | None = None,
    *,
    floor_height: int | None = 3000,
    heights_patch: dict[str, Any] | None = None,
) -> WallsDocument:
    return WallsDocument.model_validate(
        {
            "schema": "quantor.cad_walls.v1",
            "generator": "cad_walls.v1",
            "params_version": "v1",
            "params_sha256": "0" * 64,
            "dxf_sha256": "1" * 64,
            "units": "mm",
            "heights": {
                "floor_elevation_mm": None,
                "floor_height_mm": floor_height,
                "elevation_status": "missing",
                "height_status": "derived" if floor_height is not None else "missing",
                "evidence": None,
                "message": None,
                "slab_thickness_mm": 200,
                "slab_status": "assumption",
                "door_height_mm": 2100,
                "door_height_status": "assumption",
                **(heights_patch or {}),
            },
            "constructions": constructions,
            "openings": openings or [],
            "checks": {"warnings": []},
        }
    )


def only(doc: WallsDocument, props: CadConstructionProps | None = None) -> Any:
    entries = {} if props is None else {c.id: (props, False) for c in doc.constructions}
    result = calc.compute_sheet(doc, entries, NO_LEVELS)
    return result.constructions[0].computed


def test_plain_wall_volume_and_length_from_plan_area() -> None:
    computed = only(document([construction()]))
    # H = 3000 - 200 = 2800; площадь 1 м2 в плане, толщина 200 -> длина 5 м.
    assert computed.status == "ok"
    assert computed.height_mm == 2800 and computed.thickness_mm == 200.0
    assert computed.length_m == pytest.approx(5.0)
    assert computed.volume_m3 == pytest.approx(1_000_000 * 2800 / 1e9)
    assert computed.wall_area_m2 == pytest.approx(5.0 * 2.8)
    assert computed.sources.thickness == "derived" and computed.sources.height == "derived"
    assert computed.warnings == []


def test_door_adds_the_part_above_the_opening() -> None:
    doc = document([construction()], [opening("d1", "c1", width=900.0)])
    computed = only(doc)
    above = 2800 - 2100
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 900 * 200 * above) / 1e9)
    assert computed.wall_area_m2 == pytest.approx(5.0 * 2.8 + 900 * above / 1e6)
    assert computed.sources.door_height == "assumption"


def test_count_openings_false_ignores_doors() -> None:
    doc = document([construction()], [opening("d1", "c1")])
    computed = only(doc, CadConstructionProps(count_openings=False))
    assert computed.volume_m3 == pytest.approx(2.8)
    assert computed.sources.door_height is None


def test_door_estimate_is_counted_with_a_warning_and_gap_is_not_counted() -> None:
    doc = document(
        [construction()],
        [
            opening("d1", "c1", status="estimate"),
            opening("g1", "c1", kind="gap", status="no_data", width=1200.0),
        ],
    )
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    computed = result.constructions[0].computed
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 700) / 1e9)
    assert computed.warnings == ["opening_no_data", "opening_estimate"]
    assert result.summary.unaccounted_gap_openings == 1


def test_door_without_host_is_reported_not_silently_dropped() -> None:
    doc = document([construction()], [opening("d1", None, status="estimate")])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert result.summary.door_openings_without_host == 1
    assert result.constructions[0].computed.volume_m3 == pytest.approx(2.8)


def test_thickness_override_uses_axis_length() -> None:
    doc = document([construction(nominal=None, area=900_000.0, axis=4000.0)])
    assert only(doc).status == "thickness_check"
    computed = only(doc, CadConstructionProps(thickness_override_mm=250))
    assert computed.status == "ok" and computed.sources.thickness == "manual"
    assert computed.length_m == pytest.approx(4.0)
    assert computed.volume_m3 == pytest.approx(4000 * 250 * 2800 / 1e9)


def test_thickness_override_replaces_a_matched_nominal() -> None:
    doc = document([construction(nominal=100.0, area=500_000.0, axis=5000.0)])
    computed = only(doc, CadConstructionProps(thickness_override_mm=120))
    assert computed.thickness_mm == 120.0
    assert computed.volume_m3 == pytest.approx(5000 * 120 * 2800 / 1e9)


def test_thickness_check_gives_null_not_zero_and_stays_out_of_totals() -> None:
    doc = document([construction("a", nominal=None), construction("b")])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    first = result.constructions[0].computed
    assert first.status == "thickness_check" and first.warnings == ["thickness_check"]
    assert first.volume_m3 is None and first.length_m is None and first.wall_area_m2 is None
    assert result.summary.thickness_check_count == 1
    assert [(g.kind, g.thickness_mm, g.count) for g in result.totals] == [("masonry", 200.0, 1)]


def test_height_missing_without_floor_height_and_height_override_fixes_it() -> None:
    doc = document([construction()], floor_height=None)
    computed = only(doc)
    assert computed.status == "height_missing" and computed.height_mm is None
    assert computed.volume_m3 is None and computed.wall_area_m2 is None
    assert computed.length_m == pytest.approx(5.0)
    fixed = only(doc, CadConstructionProps(height_override_mm=2700))
    assert fixed.status == "ok" and fixed.sources.height == "manual"
    assert fixed.volume_m3 == pytest.approx(1_000_000 * 2700 / 1e9)
    assert calc.compute_sheet(doc, {}, NO_LEVELS).summary.height_missing_count == 1


def test_sheet_levels_override_documents_and_report_sources() -> None:
    doc = document([construction()], floor_height=None)
    levels = CadSheetLevelsRead(floor_height_mm=3100, slab_thickness_mm=250, door_height_mm=2000)
    result = calc.compute_sheet(doc, {}, levels)
    assert result.heights.wall_height_mm == 2850
    assert result.heights.wall_height_source == "manual"
    assert result.heights.floor_height.source == "manual"
    assert result.heights.floor_height.default_mm is None
    assert result.heights.slab_thickness.default_mm == 200
    assert result.constructions[0].computed.volume_m3 == pytest.approx(2.85)


def test_default_heights_keep_their_sources() -> None:
    result = calc.compute_sheet(document([construction()]), {}, NO_LEVELS)
    heights = result.heights
    assert heights.floor_height.source == "derived"
    assert heights.slab_thickness.source == "assumption"
    assert heights.door_height.source == "assumption"
    assert heights.wall_height_mm == 2800 and heights.wall_height_source == "derived"


def test_groups_split_by_kind_thickness_and_material() -> None:
    doc = document(
        [
            construction("a"),
            construction("b"),
            construction("c", nominal=100.0, area=500_000.0),
            construction("d", kind="monolith_column", nominal=400.0, area=160_000.0, axis=400.0),
        ]
    )
    props = {
        "a": (CadConstructionProps(material="aerated_concrete"), True),
        "b": (CadConstructionProps(material="brick_solid"), False),
    }
    result = calc.compute_sheet(doc, props, NO_LEVELS)
    assert [(g.kind, g.thickness_mm, g.material, g.count) for g in result.totals] == [
        ("masonry", 100.0, None, 1),
        ("masonry", 200.0, "aerated_concrete", 1),
        ("masonry", 200.0, "brick_solid", 1),
        ("monolith_column", 400.0, None, 1),
    ]
    assert result.totals[1].volume_m3 == pytest.approx(2.8)
    assert result.constructions[0].accepted is True and result.constructions[2].accepted is False


def test_totals_sum_unrounded_values() -> None:
    items = [construction(f"k{i}", area=333_333.0, axis=1666.0) for i in range(3)]
    result = calc.compute_sheet(document(items), {}, NO_LEVELS)
    (group,) = result.totals
    assert group.count == 3
    assert group.volume_m3 == pytest.approx(3 * 1666 * 200 * 2800 / 1e9, abs=1e-4)


def test_volume_uses_nominal_not_wider_hatch() -> None:
    # Штриховка 88 мм при номинале 80: площадь в плане завышена, объём — по оси и номиналу.
    item = construction("c1", nominal=80.0, area=88.0 * 5000, axis=5000.0)
    result = calc.compute_sheet(document([item]), {}, NO_LEVELS)
    assert result.constructions[0].computed.volume_m3 == pytest.approx(5000 * 80 * 2800 / 1e9)


def test_merge_props_applies_only_sent_fields_and_null_clears() -> None:
    current = CadConstructionProps(material="ceramic_block", joint_mm=10, note="было")
    patch = CadConstructionProps.model_validate({"joint_mm": 12, "note": None})
    merged = store.merge_props(current, patch)
    assert merged.material == "ceramic_block" and merged.joint_mm == 12 and merged.note is None
    assert merged.count_openings is True


def test_props_schema_rejects_unknown_fields_and_bad_ranges() -> None:
    for bad in ({"colour": "red"}, {"joint_mm": 0}, {"material": "wood"}, {"sound_rw_db": 91}):
        with pytest.raises(ValueError, match=r"validation|Extra|Input"):
            CadConstructionProps.model_validate(bad)


def test_walls_models_accept_extra_fields_of_the_file() -> None:
    raw = construction()
    raw["axis"] = [[[0.0, 100.0], [5000.0, 100.0]]]
    assert WallsConstruction.model_validate(raw).id == "c1"
    assert WallsOpening.model_validate(opening("d", None)).host_id is None


# --------------------------------------------------------------------------- монолитные перемычки

# Контур перемычки 1000 x 200 мм в плане: площадь 200 000 мм2.
LINTEL_RING = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 200.0], [0.0, 200.0]]


def with_lintel(
    item: dict[str, Any], material: str | None = "monolith", ring: list[list[float]] | None = None
) -> dict[str, Any]:
    return {**item, "lintel": LINTEL_RING if ring is None else ring, "lintel_material": material}


def lintel_group(result: calc.SheetResult) -> Any:
    found = [g for g in result.totals if g.element == "lintel"]
    return found[0] if found else None


def test_monolith_lintel_over_masonry_door_leaves_the_host_volume() -> None:
    doc = document([construction()], [with_lintel(opening("d1", "c1"))])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    host = result.constructions[0].computed
    # Надпроёмной части в объёме кладки нет; поверхность под отделку остаётся.
    assert host.volume_m3 == pytest.approx(2.8)
    assert host.wall_area_m2 == pytest.approx(5.0 * 2.8 + 1000 * 700 / 1e6)
    group = lintel_group(result)
    # H = 2800, высота двери 2100: 200 000 мм2 x 700 мм = 0,14 м3.
    assert (group.kind, group.element, group.thickness_mm) == ("monolith_wall", "lintel", 200.0)
    assert group.material == "monolith_concrete" and group.count == 1
    assert group.length_m == pytest.approx(1.0) and group.volume_m3 == pytest.approx(0.14)
    assert group.wall_area_m2 == 0.0
    assert result.summary.lintels_without_volume == 0
    assert result.totals[-1] is group  # после групп кладки; монолита в листе нет


def test_lintel_group_goes_right_after_monolith_groups() -> None:
    doc = document(
        [
            construction("a"),
            construction("m", kind="monolith_column", nominal=400.0, area=160_000.0, axis=400.0),
        ],
        [with_lintel(opening("d1", "a"))],
    )
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert [(g.kind, g.element) for g in result.totals] == [
        ("masonry", "construction"),
        ("monolith_column", "construction"),
        ("monolith_wall", "lintel"),
    ]


def test_monolith_lintel_over_monolith_host_is_not_duplicated() -> None:
    doc = document(
        [construction(kind="monolith_wall")], [with_lintel(opening("d1", "c1"), "monolith")]
    )
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert lintel_group(result) is None
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * 700) / 1e9
    )


def test_non_monolith_lintel_stays_in_the_host() -> None:
    for material in ("masonry", "frame_partition", None):
        doc = document([construction()], [with_lintel(opening("d1", "c1"), material)])
        result = calc.compute_sheet(doc, {}, NO_LEVELS)
        assert lintel_group(result) is None
        assert result.constructions[0].computed.volume_m3 == pytest.approx(
            (1_000_000 * 2800 + 1000 * 200 * 700) / 1e9
        )


def test_door_without_a_gap_gives_no_above_opening_part() -> None:
    doc = document([construction()], [opening("d1", "c1", status="no_data")])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    computed = result.constructions[0].computed
    assert computed.volume_m3 == pytest.approx(2.8)
    assert computed.wall_area_m2 == pytest.approx(5.0 * 2.8)
    assert lintel_group(result) is None and result.summary.lintels_without_volume == 0


def test_gap_with_a_monolith_lintel_is_in_the_group() -> None:
    gap = with_lintel(opening("g1", "c1", kind="gap", status="no_data", width=1000.0))
    result = calc.compute_sheet(document([construction()], [gap]), {}, NO_LEVELS)
    group = lintel_group(result)
    assert group.count == 1 and group.volume_m3 == pytest.approx(0.14)
    # Разрыв по-прежнему не входит в объём стены и даёт предупреждение.
    assert result.constructions[0].computed.volume_m3 == pytest.approx(2.8)
    assert "opening_no_data" in result.constructions[0].computed.warnings


def test_lintels_are_grouped_by_host_thickness_and_summed() -> None:
    doc = document(
        [construction("a"), construction("b", nominal=100.0, area=500_000.0)],
        [
            with_lintel(opening("d1", "a", width=900.0)),
            with_lintel(opening("d2", "a", width=1000.0)),
            with_lintel(opening("d3", "b", width=800.0)),
        ],
    )
    groups = [g for g in calc.compute_sheet(doc, {}, NO_LEVELS).totals if g.element == "lintel"]
    assert [(g.thickness_mm, g.count) for g in groups] == [(100.0, 1), (200.0, 2)]
    assert groups[1].length_m == pytest.approx(1.9)
    assert groups[1].volume_m3 == pytest.approx(2 * 0.14)


def test_lintel_without_height_or_host_is_counted_as_without_volume() -> None:
    no_height = calc.compute_sheet(
        document([construction()], [with_lintel(opening("d1", "c1"))], floor_height=None),
        {},
        NO_LEVELS,
    )
    assert lintel_group(no_height) is None and no_height.summary.lintels_without_volume == 1
    no_host = calc.compute_sheet(
        document([construction()], [with_lintel(opening("d1", None))]), {}, NO_LEVELS
    )
    assert lintel_group(no_host) is None and no_host.summary.lintels_without_volume == 1


def test_lintel_height_override_of_the_host_is_used() -> None:
    doc = document([construction()], [with_lintel(opening("d1", "c1"))])
    props = {"c1": (CadConstructionProps(height_override_mm=2500), False)}
    group = lintel_group(calc.compute_sheet(doc, props, NO_LEVELS))
    assert group.volume_m3 == pytest.approx(200_000 * 400 / 1e9)


def test_lintel_group_key_and_coverage_do_not_merge_with_monolith_walls() -> None:
    from app.services import cad_vor

    key = cad_vor.group_key("monolith_wall", 200.0, "monolith_concrete", "lintel")
    assert key == "monolith_wall|200|monolith_concrete|lintel"
    assert key != cad_vor.group_key("monolith_wall", 200.0, "monolith_concrete")
    parts = cad_vor.parse_group_key(key)
    assert parts is not None and parts.element == "lintel" and parts.thickness_mm == 200.0
    plain = cad_vor.parse_group_key("monolith_wall|200|monolith_concrete")
    assert plain is not None and plain.element == "construction"

    doc = document(
        [construction("a"), construction("w", kind="monolith_wall")],
        [with_lintel(opening("d1", "a"))],
    )
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    coverage = cad_vor.build_coverage(
        totals=result.totals,
        constructions=result.constructions,
        linked={},
        thicknesses=[200],
        has_vor=True,
    )
    by_key = {g.group_key: g for g in coverage.groups}
    assert by_key[key].element == "lintel"
    assert by_key["monolith_wall|200|"].element == "construction"
    assert set(by_key) == {"masonry|200|", "monolith_wall|200|", key}


# ------------------------------------------------------------------ разрывы с высотой (v1.9)


def gap(
    key: str,
    host: str | None,
    *,
    width: float = 1000.0,
    height: int | None = 2100,
    status: str | None = "assumption",
) -> dict[str, Any]:
    item = opening(key, host, kind="gap", status="no_data", width=width)
    if height is not None:
        item["opening_height_mm"] = height
        item["opening_height_status"] = status
    return item


def test_gap_with_height_adds_the_part_above_like_a_door() -> None:
    doc = document([construction()], [gap("g1", "c1", width=1200.0)])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    computed = result.constructions[0].computed
    above = 2800 - 2100
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1200 * 200 * above) / 1e9)
    assert computed.wall_area_m2 == pytest.approx(5.0 * 2.8 + 1200 * above / 1e6)
    assert computed.sources.gap_opening_height == "assumption"
    assert computed.sources.door_height is None
    # Высота известна: предупреждения и счётчика неучтённых разрывов нет.
    assert "opening_no_data" not in computed.warnings
    assert result.summary.unaccounted_gap_openings == 0


def test_gap_uses_its_own_height_not_the_door_height() -> None:
    doc = document([construction()], [gap("g1", "c1", height=2400)])
    computed = calc.compute_sheet(doc, {}, NO_LEVELS).constructions[0].computed
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 400) / 1e9)


def test_gap_height_equal_or_above_wall_adds_nothing() -> None:
    doc = document([construction()], [gap("g1", "c1", height=2800)])
    computed = calc.compute_sheet(doc, {}, NO_LEVELS).constructions[0].computed
    assert computed.volume_m3 == pytest.approx(2.8)


def test_gap_without_height_is_as_before() -> None:
    doc = document([construction()], [gap("g1", "c1", height=None)])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    computed = result.constructions[0].computed
    assert computed.volume_m3 == pytest.approx(2.8)
    assert computed.warnings == ["opening_no_data"]
    assert computed.sources.gap_opening_height is None
    assert result.summary.unaccounted_gap_openings == 1


def test_only_gaps_without_height_stay_unaccounted_and_warn() -> None:
    doc = document([construction()], [gap("g1", "c1"), gap("g2", "c1", height=None)])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert result.summary.unaccounted_gap_openings == 1
    assert result.constructions[0].computed.warnings == ["opening_no_data"]


def test_count_openings_false_ignores_gap_height() -> None:
    doc = document([construction()], [gap("g1", "c1")])
    computed = (
        calc.compute_sheet(
            doc, {"c1": (CadConstructionProps(count_openings=False), False)}, NO_LEVELS
        )
        .constructions[0]
        .computed
    )
    assert computed.volume_m3 == pytest.approx(2.8)
    assert computed.sources.gap_opening_height is None


def test_gap_height_source_is_the_least_reliable_of_the_gaps() -> None:
    doc = document(
        [construction()],
        [gap("g1", "c1", status="observed"), gap("g2", "c1", status="assumption")],
    )
    computed = calc.compute_sheet(doc, {}, NO_LEVELS).constructions[0].computed
    assert computed.sources.gap_opening_height == "assumption"


def test_monolith_lintel_over_a_gap_with_height_leaves_the_host_volume_and_uses_gap_height() -> (
    None
):
    item = with_lintel(gap("g1", "c1", height=2000))
    result = calc.compute_sheet(document([construction()], [item]), {}, NO_LEVELS)
    host = result.constructions[0].computed
    # Объём кладки без надпроёмной части; поверхность под отделку - с ней (2800 - 2000 = 800).
    assert host.volume_m3 == pytest.approx(2.8)
    assert host.wall_area_m2 == pytest.approx(5.0 * 2.8 + 1000 * 800 / 1e6)
    group = lintel_group(result)
    # 200 000 мм2 x 800 мм = 0,16 м3.
    assert group.count == 1 and group.volume_m3 == pytest.approx(0.16)
    assert result.summary.lintels_without_volume == 0


def test_monolith_lintel_over_a_gap_with_height_stays_in_a_monolith_host() -> None:
    item = with_lintel(gap("g1", "c1", height=2000), "monolith")
    result = calc.compute_sheet(
        document([construction(kind="monolith_wall")], [item]), {}, NO_LEVELS
    )
    assert lintel_group(result) is None
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * 800) / 1e9
    )


def test_gap_lintel_without_door_height_uses_gap_height() -> None:
    doc = document(
        [construction()],
        [with_lintel(gap("g1", "c1", height=2000))],
        heights_patch={"door_height_mm": None, "door_height_status": "missing"},
    )
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert lintel_group(result).volume_m3 == pytest.approx(0.16)
    assert result.summary.lintels_without_volume == 0


# ------------------------------------------------------------------ верх плиты (cad_walls v1.9)


def test_effective_levels_base_from_slab_top_then_sheet_elevation_then_zero() -> None:
    new = document(
        [construction()],
        heights_patch={
            "floor_elevation_mm": 50900,
            "elevation_status": "observed",
            "slab_top_elevation_mm": 50800,
            "floor_finish_mm": 100,
        },
    ).heights
    levels = calc.effective_levels(new, NO_LEVELS)
    assert (levels.base_z_mm, levels.opening_floor_z_mm, levels.elevation_mm) == (
        50800,
        50900,
        50900,
    )
    # Ручная отметка этажа - без вычета пирога, проёмы от неё же.
    manual = CadSheetLevelsRead(
        floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=9000
    )
    levels = calc.effective_levels(new, manual)
    assert (levels.base_z_mm, levels.opening_floor_z_mm, levels.slab_top_mm) == (9000, 9000, None)
    # Старый файл: отметка листа = база.
    old = document(
        [construction()],
        heights_patch={"floor_elevation_mm": 47600, "elevation_status": "observed"},
    ).heights
    levels = calc.effective_levels(old, NO_LEVELS)
    assert (levels.base_z_mm, levels.opening_floor_z_mm) == (47600, 47600)
    assert calc.effective_levels(document([construction()]).heights, NO_LEVELS).base_z_mm == 0
