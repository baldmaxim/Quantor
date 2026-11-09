"""Пакет здания: совмещение листов по осям, уровни, отказы, слияние. Только синтетика."""

import json
from dataclasses import replace

import pytest

from building_model.approval import ApprovalOut
from building_model.canonical import BuildingModel, ReviewItem
from building_model.geometry import Pt
from building_model.params import Params
from building_model.reader import AxisIn
from building_model.revit import RevitRefusalError, build_package
from building_model.revit_building import (
    AXIS_MIN_SHARED,
    SheetInput,
    align_sheets,
    build_building_package,
    duplicate_reasons,
    sheet_intersections,
    shift_package,
)
from building_model.revit_format import (
    RevitBuildingPackage,
    SkippedPage,
    building_package_json_schema,
    dumps_building_package,
)
from tests.revit_fixture import (
    BUILDING_EXAMPLE_PATH,
    DOCS_DIR,
    building_document,
    building_example_text,
    building_inputs,
    building_package,
    model_sha,
)

SHA = "0" * 64


def _build(
    sheets: list[SheetInput],
    added: list[int] | None = None,
    excluded: list[int] | None = None,
    skipped: list[SkippedPage] | None = None,
) -> RevitBuildingPackage:
    return build_building_package(sheets, 0, added or [], excluded or [], skipped or [], SHA)


def _refusal(sheets: list[SheetInput]) -> str:
    with pytest.raises(RevitRefusalError) as info:
        _build(sheets)
    return str(info.value)


def _grid(
    vertical: dict[str, float], horizontal: dict[str, float], sx: float = 0.0, sy: float = 0.0
) -> list[AxisIn]:
    axes = [
        AxisIn(label=k, normal=(1.0, 0.0), offset_mm=v + sx, bubbles=2) for k, v in vertical.items()
    ]
    axes += [
        AxisIn(label=k, normal=(0.0, 1.0), offset_mm=v + sy, bubbles=2)
        for k, v in horizontal.items()
    ]
    return axes


def _with_model(sheet: SheetInput, model: BuildingModel, approved: bool = True) -> SheetInput:
    approval = (
        ApprovalOut(page=sheet.page, model_sha256=model_sha(model), mm_per_pt=35.0, by="А", at="t")
        if approved
        else None
    )
    return replace(sheet, model=model, approval=approval, model_sha256=model_sha(model))


def _relevel(
    model: BuildingModel, mapping: dict[str, str], elevation_shift: float
) -> BuildingModel:
    """Переименовывает уровни (и ссылки на них) и сдвигает отметки; ключи элементов не меняются."""

    def lv(key: str) -> str:
        return mapping.get(key, key)

    levels = [
        x.model_copy(
            update={
                "key": lv(x.key),
                "instance_of": None if x.instance_of is None else lv(x.instance_of),
                "elevation_mm": None
                if x.elevation_mm is None
                else x.elevation_mm + elevation_shift,
            }
        )
        for x in model.levels
    ]
    return model.model_copy(
        update={
            "levels": levels,
            "walls": [w.model_copy(update={"level": lv(w.level)}) for w in model.walls],
            "openings": [o.model_copy(update={"level": lv(o.level)}) for o in model.openings],
            "slabs": [s.model_copy(update={"level": lv(s.level)}) for s in model.slabs],
            "rooms": [r.model_copy(update={"level": lv(r.level)}) for r in model.rooms],
            "stacks": [s.model_copy(update={"level": lv(s.level)}) for s in model.stacks],
            "columns": [c.model_copy(update={"level": lv(c.level)}) for c in model.columns],
        }
    )


def _points(package: RevitBuildingPackage, level: str) -> dict[str, list[Pt]]:
    walls = [p for w in package.walls if w.level == level for p in (w.start, w.end)]
    floors = [p for f in package.floors if f.level == level for p in f.boundary]
    holes = [p for f in package.floors if f.level == level for h in f.holes for p in h.boundary]
    columns = [p for c in package.columns if c.level == level for p in c.outline]
    stacks = [p for s in package.stacks if s.level == level for p in s.outline]
    openings = [
        o.at
        for o in package.openings
        if o.host in {w.id for w in package.walls if w.level == level}
    ]
    rooms = [p for r in package.rooms if r.level == level for p in (*r.boundary, r.point)]
    return {
        "walls": sorted(walls), "floors": sorted(floors), "holes": sorted(holes),
        "columns": sorted(columns), "stacks": sorted(stacks), "openings": sorted(openings),
        "rooms": sorted(rooms),
    }  # fmt: skip


def test_offset_is_applied_to_every_kind_of_coordinate() -> None:
    package = building_package()
    first, second = _points(package, "L5"), _points(package, "L7")
    assert all(first[kind] for kind in first)
    assert first == second
    # Прямая проверка арифметики: точки пакета листа 1 + смещение (6000, 5000).
    sheets = building_inputs()
    own = build_package(sheets[1].model, sheets[1].approval, sheets[1].model_sha256)
    moved = shift_package(own, (6000.0, 5000.0))
    assert moved.walls[0].start == (own.walls[0].start[0] + 6000.0, own.walls[0].start[1] + 5000.0)
    assert moved.floors[0].holes[0].boundary[0] == (
        own.floors[0].holes[0].boundary[0][0] + 6000.0,
        own.floors[0].holes[0].boundary[0][1] + 5000.0,
    )
    stack = moved.stacks[0]
    assert stack.slab_opening is not None and own.stacks[0].slab_opening is not None
    assert stack.slab_opening[0][0] == own.stacks[0].slab_opening[0][0] + 6000.0
    assert moved.rooms[0].point[1] == own.rooms[0].point[1] + 5000.0
    assert [n.at for n in moved.not_exported] != [n.at for n in own.not_exported]
    # Не меняются: отметки, ширины, id, params.
    assert moved.walls[0].id == own.walls[0].id and moved.walls[0].params == own.walls[0].params
    assert moved.levels == own.levels
    assert moved.openings[0].offset_mm == own.openings[0].offset_mm
    assert moved.openings[0].width_mm == own.openings[0].width_mm


def test_manifest_reference_offsets_and_keys() -> None:
    package = building_package()
    manifest = package.manifest
    assert manifest.building.reference_page == 0
    assert [s.page for s in manifest.sheets] == [0, 1]
    assert [s.offset_mm for s in manifest.sheets] == [(0.0, 0.0), (6000.0, 5000.0)]
    assert [s.levels for s in manifest.sheets] == [["L5", "L6"], ["L7", "L8"]]
    assert all(s.axis_match.residual_max_mm == 0.0 for s in manifest.sheets)
    assert manifest.scale_status == "human"
    assert manifest.adapter.version == "0.1.0" and manifest.units == "mm"
    # Ключи листа не меняются: те же QTO_Key, что в пакете листа.
    sheets = building_inputs()
    own = build_package(sheets[1].model, sheets[1].approval, sheets[1].model_sha256)
    assert {w.id for w in own.walls} <= {w.id for w in package.walls}
    assert {w.params["QTO_Key"] for w in package.walls} == {w.id for w in package.walls}


def test_reference_is_sheet_with_most_intersections_then_smallest_page() -> None:
    sheets = building_inputs()
    # Лист 0 теряет ось «3»: у листа 1 пересечений больше, он становится опорным.
    trimmed = replace(sheets[0], axes=[a for a in sheets[0].axes if a.label != "3"])
    package = _build([trimmed, sheets[1]])
    assert package.manifest.building.reference_page == 1
    assert [s.offset_mm for s in package.manifest.sheets] == [(-6000.0, -5000.0), (0.0, 0.0)]
    pts = {1: {("a", "b"): (0.0, 0.0)}, 0: {("a", "b"): (1.0, 1.0)}}
    assert align_sheets(pts)[0] == 0


VERTICAL = {str(i): 1000.0 * i for i in range(6)}
HORIZONTAL = {c: 700.0 * j for j, c in enumerate("ABCD")}


def test_reference_is_not_the_largest_sheet_when_its_labels_are_wrong() -> None:
    good = {("a", str(i)): (float(i) * 1000.0, 0.0) for i in range(9)}
    # У листа 7 больше всего пересечений, но четыре пары подписаны неверно: опорой ему не быть.
    broken = dict(good)
    for i in range(4):
        broken[("a", str(i))] = (float(i) * 1000.0 + 48000.0, 0.0)
    broken[("b", "extra")] = (0.0, 500.0)
    reference, alignments = align_sheets({7: broken, 8: good, 9: dict(good)})
    assert reference == 8
    assert alignments[9].match.outliers == 0
    assert alignments[7].match.outliers == 4


def _axes_of(
    sheet: SheetInput, dx: float = 0.0, dy: float = 0.0, vertical: dict[str, float] | None = None
) -> list[AxisIn]:
    """Сетка 6 x 4 осей в системе листа; в системе его модели она сдвинута на (-dx, -dy)."""
    ox, oy = sheet.model.origin.sheet_mm
    return _grid(
        {k: v + ox - dx for k, v in (vertical or VERTICAL).items()},
        {k: v + oy + dy for k, v in HORIZONTAL.items()},
    )


def _grid_pair(
    sheets: list[SheetInput], vertical: dict[str, float] | None = None
) -> list[SheetInput]:
    """Лист 1 лежит в своей системе со сдвигом (6000, 5000) относительно листа 0."""
    return [
        replace(sheets[0], axes=_axes_of(sheets[0])),
        replace(sheets[1], axes=_axes_of(sheets[1], 6000.0, 5000.0, vertical)),
    ]


def test_median_survives_a_gross_outlier_axis() -> None:
    sheets = building_inputs()
    clean = _build(_grid_pair(sheets)).manifest.sheets[1]
    assert clean.offset_mm == (6000.0, 5000.0) and clean.axis_match.shared == 24
    # Ось «2» на листе 1 с неверной меткой стоит на 48 м дальше: 4 пары из 24 — выбросы.
    entry = _build(_grid_pair(sheets, {**VERTICAL, "2": VERTICAL["2"] + 48000.0})).manifest.sheets[
        1
    ]
    assert entry.offset_mm == (6000.0, 5000.0)
    assert entry.axis_match.shared == 24
    assert entry.axis_match.outliers == 4
    assert entry.axis_match.residual_max_mm == 48000.0
    assert entry.axis_match.residual_median_mm == 0.0


def test_too_few_shared_axes_refuses() -> None:
    sheets = building_inputs()
    few = _grid({"1": 0.0, "2": 1000.0}, {"A": 0.0, "B": 500.0})
    sheets[1] = replace(sheets[1], axes=few)
    # Общих меток 1, A, B: общих пересечений (1, A) и (1, B) — всего два, меньше порога.
    sheets[0] = replace(sheets[0], axes=_grid({"1": 0.0, "9": 1000.0}, {"A": 0.0, "B": 500.0}))
    text = _refusal(sheets)
    assert "общих пересечений осей" in text and "страница" in text
    assert str(AXIS_MIN_SHARED) in text


def test_large_residual_refuses() -> None:
    sheets = building_inputs()
    # Вертикальные оси листа 1 растянуты вдвое: невязки растут от оси к оси, медиана > 50 мм.
    text = _refusal(_grid_pair(sheets, {k: 2.0 * v for k, v in VERTICAL.items()}))
    assert "медиана невязки" in text and "страница 1" in text


def test_duplicate_and_unlabelled_axes_are_ignored() -> None:
    params = Params()
    axes = [
        *_grid({"1": 0.0, "2": 1000.0}, {"A": 0.0}),
        AxisIn(label="2", normal=(0.0, 1.0), offset_mm=500.0, bubbles=1),
        AxisIn(label=None, normal=(0.0, 1.0), offset_mm=900.0),
        AxisIn(label="", normal=(0.0, 1.0), offset_mm=950.0),
        AxisIn(label="X", normal=(1.0, 0.0), offset_mm=300.0),
    ]
    found = sheet_intersections(axes, (0.0, 0.0), params)
    # «2» встречается дважды и исключена; параллельные оси (1 и X) не пересекаются.
    assert sorted(found) == [("1", "A"), ("A", "X")]
    assert found[("1", "A")] == (0.0, 0.0)
    # Перевод в систему модели: x - ox, oy - y.
    assert sheet_intersections(axes, (100.0, 50.0), params)[("1", "A")] == (-100.0, 50.0)


def test_level_conflict_same_key_with_different_elevation() -> None:
    sheets = building_inputs()
    model = _relevel(sheets[1].model, {"L7": "L5", "L8": "L9"}, 500.0)
    text = _refusal([sheets[0], _with_model(sheets[1], model)])
    assert "конфликт уровней" in text and "одинаковый ключ" in text
    assert "L5" in text and "страница 0" in text and "страница 1" in text
    assert "14000.0" in text and "21100.0" in text


def test_level_conflict_different_keys_with_equal_elevation() -> None:
    sheets = building_inputs()
    model = _relevel(sheets[1].model, {}, 0.0)
    levels = [
        lv.model_copy(update={"elevation_mm": 14000.5}) if lv.key == "L7" else lv
        for lv in model.levels
    ]
    changed = model.model_copy(update={"levels": levels})
    text = _refusal([sheets[0], _with_model(sheets[1], changed)])
    assert "разные ключи" in text and "L5" in text and "L7" in text
    # Разница больше допуска — конфликта нет.
    far = [
        lv.model_copy(update={"elevation_mm": 14001.5}) if lv.key == "L7" else lv
        for lv in model.levels
    ]
    _build([sheets[0], _with_model(sheets[1], model.model_copy(update={"levels": far}))])


def _noisy(model: BuildingModel) -> BuildingModel:
    item = ReviewItem(
        code="openings_noise", severity="blocker", element=None, source_ids=[], at=None, detail={}
    )
    review = model.review.model_copy(update={"items": [*model.review.items, item]})
    return model.model_copy(update={"review": review})


def test_noisy_sheet_refuses_and_accepted_noise_passes() -> None:
    sheets = building_inputs()
    noisy = _noisy(sheets[1].model)
    text = _refusal([sheets[0], _with_model(sheets[1], noisy)])
    assert "страница 1" in text and "openings_noise" in text
    accepted = _with_model(sheets[1], noisy)
    assert accepted.approval is not None
    accepted = replace(
        accepted,
        approval=accepted.approval.model_copy(update={"accepted_blockers": ["openings_noise"]}),
    )
    package = _build([sheets[0], accepted])
    assert package.manifest.sheets[1].approval is not None
    assert package.manifest.sheets[1].approval.accepted_blockers == ["openings_noise"]
    # Без акта (тестовый режим) шумный лист — отказ.
    assert "openings_noise" in _refusal([sheets[0], _with_model(sheets[1], noisy, approved=False)])


def test_missing_floors() -> None:
    assert building_package().manifest.building.missing_floors == []
    package = _build(building_inputs(building_document([8, 9])))
    assert package.manifest.building.missing_floors == [7]
    below = _build(building_inputs(building_document([-2, -1])))
    assert below.manifest.building.missing_floors == [1, 2, 3, 4]


def test_coverage_is_sum_of_sheets() -> None:
    package = building_package()
    manifest = package.manifest
    for kind, cov in manifest.coverage.items():
        assert cov.exported + cov.not_exported == cov.total
        assert cov.total == sum(s.coverage[kind].total for s in manifest.sheets)
        assert cov.exported == sum(s.coverage[kind].exported for s in manifest.sheets)
    assert manifest.coverage["walls"].exported == len(package.walls)
    assert manifest.coverage["openings"].exported == len(package.openings)
    assert len(package.not_exported) == sum(c.not_exported for c in manifest.coverage.values())
    own = sum(
        build_package(s.model, s.approval, s.model_sha256).manifest.assumptions.assumed_elements[
            "walls"
        ]
        for s in building_inputs()
    )
    assert manifest.assumptions.assumed_elements["walls"] == own


def test_wall_types_are_summed_by_id_and_sorted_by_thickness() -> None:
    package = building_package()
    assert [(t.id, t.count) for t in package.wall_types] == [("QTO-W-100", 2), ("QTO-W-300", 8)]
    assert sum(t.count for t in package.wall_types) == len(package.walls)


def test_lists_are_sorted_by_id() -> None:
    package = building_package()
    for items in (package.walls, package.openings, package.floors, package.rooms):
        assert [i.id for i in items] == sorted(i.id for i in items)
    assert [lv.id for lv in package.levels] == ["L5", "L6", "L7", "L8"]


def test_deterministic() -> None:
    first = dumps_building_package(building_package())
    assert first == dumps_building_package(building_package())
    assert "seconds" not in first
    data = json.loads(first)
    assert list(data)[:3] == ["schema", "draft_format", "manifest"]
    assert data["schema"] == "quantor.revit_building_package.v0"


def test_all_refusals_are_listed_together_with_pages() -> None:
    sheets = building_inputs()
    bad_sha = replace(sheets[0], model_sha256="1" * 64)
    conflicting = _with_model(sheets[1], _relevel(sheets[1].model, {"L7": "L6"}, 0.0))
    text = _refusal([bad_sha, conflicting])
    assert "страница 0" in text and "sha256" in text
    # Лист 0 отклонён сам, лист 1 один — конфликтовать не с чем, отказ только по листу 0.
    assert "конфликт" not in text


def test_refusals_of_different_kinds_accumulate() -> None:
    sheets = building_inputs()
    noisy = _with_model(sheets[0], _noisy(sheets[0].model), approved=False)
    # Лист 2 — копия листа 1 с уровнем L8 вместо L7: ключ L8 совпадает с уровнем листа 1.
    clone = replace(sheets[1], page=2)
    clone_model = _relevel(clone.model, {"L7": "L8"}, 0.0)
    stats = {**clone_model.stats, "sheet": {"page": 2}}
    two = _with_model(clone, clone_model.model_copy(update={"stats": stats}))
    text = _refusal([noisy, sheets[1], two])
    assert "страница 0" in text and "openings_noise" in text
    assert "конфликт уровней" in text and "L8" in text
    assert "страница 1" in text and "страница 2" in text


def test_different_reader_tender_or_params_refuse() -> None:
    sheets = building_inputs()
    reader = sheets[1].model.reader.model_copy(update={"normalizer": "9.9.9"})
    text = _refusal(
        [sheets[0], _with_model(sheets[1], sheets[1].model.model_copy(update={"reader": reader}))]
    )
    assert "нормализатора" in text and "9.9.9" in text
    tender = sheets[1].model.tender.model_copy(update={"version": 3})
    text = _refusal(
        [sheets[0], _with_model(sheets[1], sheets[1].model.model_copy(update={"tender": tender}))]
    )
    assert "версии тендера" in text
    params = {**sheets[1].model.params, "door_height_mm": 2000.0}
    text = _refusal(
        [sheets[0], _with_model(sheets[1], sheets[1].model.model_copy(update={"params": params}))]
    )
    assert "допущения" in text


def test_duplicate_ids_after_merge_refuse() -> None:
    sheets = building_inputs()
    # Те же элементы на другом уровне: ключи элементов совпадают, уровни нет.
    twin_model = _relevel(sheets[0].model, {"L5": "L7", "L6": "L8"}, 10000.0)
    stats = {**twin_model.stats, "sheet": {"page": 1}}
    twin = replace(_with_model(sheets[1], twin_model.model_copy(update={"stats": stats})), page=1)
    text = _refusal([sheets[0], twin])
    assert "дубликат id" in text and "страницы 0 и 1" in text
    assert duplicate_reasons([]) == []


def test_mixed_approval_gives_candidate_status() -> None:
    sheets = building_inputs()
    package = _build([sheets[0], _with_model(sheets[1], sheets[1].model, approved=False)])
    assert package.manifest.scale_status == "candidate"
    assert [s.scale_status for s in package.manifest.sheets] == ["human", "candidate"]
    test_only = _build(building_inputs(approved=False))
    assert test_only.manifest.scale_status == "candidate"
    assert all(s.approval is None for s in test_only.manifest.sheets)


def test_empty_composition_and_repeated_page_are_errors() -> None:
    with pytest.raises(ValueError, match="нет ни одного листа"):
        _build([])
    sheets = building_inputs()
    with pytest.raises(ValueError, match="повторяется"):
        _build([sheets[0], sheets[0]])


def test_manifest_records_human_decisions() -> None:
    sheets = building_inputs()
    package = _build(
        sheets, added=[9, 3, 9], excluded=[5], skipped=[SkippedPage(page=7, reason="kind:section")]
    )
    info = package.manifest.building
    assert (info.added_pages, info.excluded_pages) == ([3, 9], [5])
    assert [(s.page, s.reason) for s in info.skipped_pages] == [(7, "kind:section")]
    assert info.input_sha256 == SHA


def test_schema_file_matches_model() -> None:
    path = DOCS_DIR / "revit-building-package-v0.schema.json"
    assert path.read_text(encoding="utf-8") == building_package_json_schema()


def test_example_file_matches_fixture() -> None:
    assert BUILDING_EXAMPLE_PATH.read_text(encoding="utf-8") == building_example_text()
