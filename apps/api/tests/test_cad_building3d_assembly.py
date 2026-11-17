"""Сборка здания для 3D: что попадает в стопку этажей и как она собрана (чистые функции)."""

from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_building3d import CadBuilding3dGroupRead, CadBuilding3dPlacement
from app.contracts.cad_constructions import WallsDocument
from app.domain import JobStatus, JobType
from app.models import Job
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from app.services import cad_site_pins
from tests.conftest import FakeObjectStorage
from tests.test_cad_building3d import axes_block, built, sheet, with_cores
from tests.test_cad_floor3d import BASE, heights, raw_document, raw_extras
from tests.test_cad_site_cores import CORE, wall

# Сетка одной секции: оси с номером секции, пролёты от 6 м (по ним оценивается наклон шкалы).
GRID_X = {"1.1": 0.0, "1.2": 6000.0, "1.3": 12000.0, "1.4": 18000.0, "1.5": 24000.0}
GRID_Y = {"1.А": 0.0, "1.Б": 7000.0, "1.В": 14000.0, "1.Г": 21000.0}


async def _no_pins(_session: AsyncSession, **_kwargs: object) -> list[object]:
    return []


def scaled(axes: dict[str, float], factor: float, shift: float = 0.0) -> dict[str, float]:
    return {label: value * factor + shift for label, value in axes.items()}


def patched(item: b3d.BuiltFloor, **update: Any) -> b3d.BuiltFloor:
    return dataclasses.replace(item, floor=item.floor.model_copy(update=update))


def document(title: dict[str, Any] | None, generator: str = "cad_walls.v1.15") -> WallsDocument:
    raw = raw_document(title=title)
    raw["generator"] = generator
    return WallsDocument.model_validate(raw)


# ------------------------------------------------------------------ планы и служебные листы


def test_sheet_with_plan_title_or_floor_plan_passport_is_a_floor() -> None:
    plan = document({"corps": "9", "section": "3", "floors": [2], "text": None, "kind": "floor"})
    assert b3d.plan_problem(plan, None) is None
    # Паспорт паркинга - «таблица» (экспликация на том же листе), но заголовок плана есть.
    assert b3d.plan_problem(plan, "table") is None
    assert b3d.plan_problem(document(None), "floor_plan") is None


def test_section_sheet_and_untitled_sheet_of_a_new_file_are_service_sheets() -> None:
    by_passport = b3d.plan_problem(document(None), "section")
    assert by_passport is not None and "разрез" in by_passport
    untitled = b3d.plan_problem(document(None), None)
    assert untitled is not None and "заголовок плана" in untitled


def test_old_walls_file_without_passport_stays_a_floor() -> None:
    """Файл до v1.15 вида плана не пишет: без паспорта отсеять лист нечем."""
    assert b3d.plan_problem(document(None, generator="cad_walls.v1.14"), None) is None
    assert b3d.plan_problem(document(None, generator="cad_walls.v1.14"), "facade") is not None


# ------------------------------------------------------------------ масштаб и качество


def test_floor_built_in_wrong_scale_is_refused_with_scale_reason() -> None:
    """Лист построен в масштабе ×0,72 (калибровка оператора): причина - масштаб, а не оси."""
    reference = built(axes=axes_block(GRID_X, GRID_Y))
    small = built(
        order=1,
        axes=axes_block(scaled(GRID_X, 0.72, 500.0), scaled(GRID_Y, 0.72, 300.0)),
    )
    _ref, floor = b3d.align_floors([reference, small])
    assert floor.alignment == "none"
    assert floor.alignment_message is not None
    assert floor.alignment_message.startswith("масштаб листа")
    assert "оси расходятся" not in floor.alignment_message
    assert floor.alignment_scale_permille == pytest.approx(388.89, abs=0.1)


def test_other_axis_grid_is_still_reported_as_diverging_axes() -> None:
    reference = built(axes=axes_block(GRID_X, GRID_Y))
    other_x = {"1.1": 0.0, "1.2": 9000.0, "1.3": 11000.0, "1.4": 30000.0, "1.5": 31000.0}
    other = built(order=1, axes=axes_block(other_x, GRID_Y))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "none"
    assert floor.alignment_message is not None and "оси расходятся" in floor.alignment_message


def test_small_scale_drift_keeps_alignment_and_is_reported() -> None:
    reference = built(axes=axes_block(GRID_X, GRID_Y))
    drifted = built(order=1, axes=axes_block(scaled(GRID_X, 1 / 1.002), scaled(GRID_Y, 1 / 1.002)))
    _ref, floor = b3d.align_floors([reference, drifted])
    assert floor.alignment == "axes"
    assert floor.alignment_scale_permille == pytest.approx(2.0, abs=0.01)
    assert floor.alignment_axes_common == 9 and len(floor.alignment_axes) == 9
    assert floor.alignment_rms_mm is not None and 5 < floor.alignment_rms_mm < 25


def test_scale_drift_over_the_limit_refuses_alignment_even_within_axis_tolerance() -> None:
    reference = built(axes=axes_block(GRID_X, GRID_Y))
    drifted = built(order=1, axes=axes_block(scaled(GRID_X, 1 / 1.008), scaled(GRID_Y, 1 / 1.008)))
    _ref, floor = b3d.align_floors([reference, drifted])
    assert floor.alignment == "none"
    assert floor.alignment_message is not None and "масштаб листа" in floor.alignment_message


def test_alignment_quality_counts_agreed_and_common_axes() -> None:
    """Кружок на выноске сдвинут на метры: согласных осей меньше общих, остаток - по согласным."""
    reference = built(axes=axes_block(GRID_X, GRID_Y))
    moved_x = {**scaled(GRID_X, 1.0, 1000.0), "1.3": 12000.0 + 1000.0 + 2500.0}
    floor_y = {**scaled(GRID_Y, 1.0, -400.0), "1.Б": 7000.0 - 400.0 + 6.0}
    _ref, floor = b3d.align_floors([reference, built(order=1, axes=axes_block(moved_x, floor_y))])
    assert floor.alignment == "axes" and floor.offset_mm == pytest.approx((-1000.0, 400.0))
    assert floor.alignment_axes_common == 9 and len(floor.alignment_axes) == 8
    assert floor.alignment_max_mm == pytest.approx(6.0, abs=0.1)
    assert floor.alignment_rms_mm == pytest.approx(2.1, abs=0.1)
    assert floor.alignment_scale_permille == pytest.approx(0.0, abs=0.3)


# ------------------------------------------------------------------ дубли планов


def stage_part() -> list[list[tuple[float, float]]]:
    """Монолит части листа: первые десять элементов ядра."""
    return [list(ring) for ring in CORE[:10]]


def test_smaller_sheet_with_the_same_monolith_on_the_same_level_is_superseded() -> None:
    """Лист «Этап 1» - часть листа «Этапы 1 и 2»: в стопке остаётся лист большей площади."""
    whole = with_cores(
        built(corps=None, section=None, axes=axes_block(GRID_X, GRID_Y)),
        CORE,
        bbox=[-8000.0, -5000.0, 17000.0, 14000.0],
    )
    part = with_cores(
        built(corps=None, section=None, order=1, axes=axes_block(GRID_X, GRID_Y)),
        stage_part(),
        bbox=[0.0, 0.0, 7200.0, 6000.0],
    )
    upper = with_cores(
        built(
            corps=None,
            section=None,
            order=2,
            elevation=BASE + 3300,
            axes=axes_block(GRID_X, GRID_Y),
        ),
        stage_part(),
        bbox=[0.0, 0.0, 7200.0, 6000.0],
    )
    items = [part, whole, upper]
    assert assembly.find_superseded(items, b3d.align_floors(items)) == {0: 1}
    stack = assembly.build_stack(items)
    assert stack.kept == [1, 2] and stack.superseded == {0: 1}
    assert len(stack.floors) == 2


def test_different_monolith_on_the_same_level_is_not_a_duplicate() -> None:
    whole = with_cores(
        built(corps=None, section=None, axes=axes_block(GRID_X, GRID_Y)),
        CORE,
        bbox=[-8000.0, -5000.0, 17000.0, 14000.0],
    )
    other = with_cores(
        built(corps=None, section=None, order=1, axes=axes_block(GRID_X, GRID_Y)),
        [wall(1000.0 * i, 9000.0, 800, 3000, 90) for i in range(8)],
        bbox=[0.0, 0.0, 9000.0, 12000.0],
    )
    items = [whole, other]
    assert assembly.find_superseded(items, b3d.align_floors(items)) == {}


# ------------------------------------------------------------------ сведение групп


def test_groups_with_one_axis_grid_are_merged_into_the_named_building() -> None:
    """«Корп. 8 · сек. 1» и «сек. 1» (техуровень без корпуса в заголовке) - одно здание."""
    floors = [
        built(
            corps="8",
            section="1",
            order=i,
            elevation=BASE + 3300 * i,
            axes=axes_block(GRID_X, GRID_Y),
        )
        for i in range(2)
    ]
    tech = built(
        corps=None,
        section="1",
        order=5,
        elevation=BASE - 2000,
        axes=axes_block(scaled(GRID_X, 1.0, 700.0), scaled(GRID_Y, 1.0, -300.0)),
        shift=(700.0, -300.0),
    )
    unnamed = built(
        corps=None,
        section=None,
        order=6,
        elevation=BASE + 9900,
        axes=axes_block(scaled(GRID_X, 1.0, 0.0), scaled(GRID_Y, 1.0, 29300.0)),
        # Начало DXF привязано к содержимому листа: геометрия сдвинута вместе с осями.
        shift=(0.0, 29300.0),
    )
    items = [*floors, tech, unnamed]
    merged = assembly.merge_groups(items, b3d.align_floors(items))
    assert merged == {
        "s1": ("k8-s1", "Корп. 8 · сек. 1"),
        "none": ("k8-s1", "Корп. 8 · сек. 1"),
    }
    stack = assembly.build_stack(items)
    assert [g.key for g in stack.groups] == ["k8-s1"]
    assert stack.groups[0].floor_count == 4 and stack.groups[0].aligned_count == 4
    # Эталон сведённого здания - нижний этаж (техуровень): остальные совмещены с ним по осям.
    first, second, low, high = stack.real
    assert (low.alignment, low.offset_mm) == ("reference", (0.0, 0.0))
    assert first.offset_mm == second.offset_mm == pytest.approx((700.0, -300.0))
    assert high.alignment == "axes" and high.offset_mm == pytest.approx((700.0, -29600.0))


def test_merge_keeps_unrelated_unnamed_buildings_apart() -> None:
    """Сведение одного здания не трогает деление «Корпус не указан» на здания по сеткам осей."""
    tower = built(corps="8", section="1", axes=axes_block(GRID_X, GRID_Y))
    tech = built(
        corps=None, section="1", order=1, elevation=BASE - 2000, axes=axes_block(GRID_X, GRID_Y)
    )
    park_x = {f"0{i}": 8000.0 * i for i in range(1, 6)}
    park_y = {"0А": 0.0, "0Б": 9000.0, "0В": 18000.0}
    parking = [
        built(
            corps=None,
            section=None,
            order=2 + i,
            elevation=-5350 + 3300 * i,
            axes=axes_block(park_x, park_y),
        )
        for i in range(2)
    ]
    other_x = {f"7.{i}": 6500.0 * i for i in range(1, 6)}
    other_y = {"7.А": 0.0, "7.Б": 7500.0, "7.В": 15000.0}
    other = built(corps=None, section=None, order=5, axes=axes_block(other_x, other_y))
    stack = assembly.build_stack([tower, tech, *parking, other])
    assert {g.key: g.floor_count for g in stack.groups} == {"k8-s1": 2, "none": 2, "none-2": 1}


def test_summary_plan_underground_and_other_sections_are_not_merged() -> None:
    tower = built(corps="8", section="1", axes=axes_block(GRID_X, GRID_Y))
    # Сводный план секций 1-6 несёт оси секции 1 целиком, но это не здание корпуса.
    wide_x = {**GRID_X, **{f"4.{i}": 40000.0 + 6000.0 * i for i in range(1, 6)}}
    summary = built(corps=None, section="1-6", order=1, axes=axes_block(wide_x, GRID_Y))
    parking = built(
        corps=None, section=None, order=2, elevation=-5350, axes=axes_block(GRID_X, GRID_Y)
    )
    # Та же сетка у секции 2 (заголовки называют разные секции) - не сводится.
    twin = built(corps="8", section="2", order=3, axes=axes_block(GRID_X, GRID_Y))
    items = [tower, summary, parking, twin]
    assert assembly.merge_groups(items, b3d.align_floors(items)) == {}


def test_unprefixed_marks_do_not_merge_a_group_without_section() -> None:
    """Марки без номера секции повторяются у типовых секций: без секции в заголовке не сводим."""
    plain_x = {str(i): 6000.0 * i for i in range(1, 6)}
    plain_y = {"А": 0.0, "Б": 7000.0, "В": 14000.0, "Г": 21000.0}
    tower = built(corps="8", section="1", axes=axes_block(plain_x, plain_y))
    unnamed = built(corps=None, section=None, order=1, axes=axes_block(plain_x, plain_y))
    hinted = dataclasses.replace(unnamed, hint=("8", "1"))
    for other, expected in ((unnamed, {}), (hinted, {"none": ("k8-s1", "Корп. 8 · сек. 1")})):
        items = [tower, other]
        assert assembly.merge_groups(items, b3d.align_floors(items)) == expected
    foreign = dataclasses.replace(unnamed, hint=("9", "1"))
    items = [tower, foreign]
    assert assembly.merge_groups(items, b3d.align_floors(items)) == {}


def test_section_count_reads_ranges_and_lists() -> None:
    assert [assembly.section_count(s) for s in (None, "3", "1-2", "12-14", "8, 9, 10", "4/5")] == [
        0,
        1,
        2,
        3,
        3,
        2,
    ]


# ------------------------------------------------------------------ сводные листы


SUMMARY_KEY = "summary-0a1b2c3d-7"


def test_unplaced_summary_sheet_leaves_the_stack() -> None:
    """Сводный лист планов секций, не вставший на площадку, - служебный: в здании его нет."""
    from tests.test_cad_site_cores import CORE, parking

    under = with_cores(
        built(corps=None, section=None, elevation=BASE - 5000),
        parking(),
        bbox=[0.0, 0.0, 220000.0, 180000.0],
    )
    tower = with_cores(built(corps="1", section="1", order=1), CORE)
    summary = patched(
        built(corps=None, section="17", order=2),
        group_key=SUMMARY_KEY,
        group_label="Сводный лист · АР1.2 · лист 8",
    )
    stack = assembly.build_stack([under, tower, summary])
    assert stack.summaries == (2,)
    assert stack.kept == [0, 1]
    assert SUMMARY_KEY not in {g.key for g in stack.groups}
    assert all(f.group_key != SUMMARY_KEY for f in stack.floors)
    # Постановка остальных не меняется: корпус встал на паркинг по ядрам.
    assert {g.key: g.placement for g in stack.groups} == {"none": "reference", "k1-s1": "cores"}


def test_placed_or_single_summary_sheet_stays_in_the_building() -> None:
    def placement(kind: CadBuilding3dPlacement) -> b3d.GroupPlacement:
        return b3d.GroupPlacement(kind, (0.0, 0.0), (), None, None, None)

    assert assembly.unplaced_summaries({SUMMARY_KEY: placement("reference")}) == frozenset()
    placed = {"none": placement("reference"), SUMMARY_KEY: placement("cores")}
    assert assembly.unplaced_summaries(placed) == frozenset()
    lost = {"none": placement("reference"), SUMMARY_KEY: placement("none"), "k1": placement("none")}
    assert assembly.unplaced_summaries(lost) == frozenset({SUMMARY_KEY})


# ------------------------------------------------------------------ типовые листы


def typical_title(floors: list[int], marks: list[int]) -> dict[str, Any]:
    return {
        "corps": "10",
        "section": "12-14",
        "floors": floors,
        "text": None,
        "kind": "floor",
        "marks_mm": marks,
    }


def typical_item(
    floors: list[int], marks: list[int], *, order: int = 0, elevation: int | None = None
) -> b3d.BuiltFloor:
    title = typical_title(floors, marks)
    raw = raw_document(title=title, floor_elevation_mm=marks[0] if elevation is None else elevation)
    doc = WallsDocument.model_validate(raw)
    item = built(corps="10", section="12-14", order=order, elevation=doc.heights.floor_elevation_mm)
    label = "К10 · С12-14 · " + ("5, 7 эт." if floors == [5, 7] else "3–7 эт.")
    return dataclasses.replace(
        patched(item, label=label), typical=b3d.typical_plan(doc, "АР · лист 1")
    )


def test_typical_plan_reads_floors_and_marks_of_the_title() -> None:
    doc = WallsDocument.model_validate(
        raw_document(title=typical_title([5, 7], [17700, 24300]), floor_elevation_mm=24300)
    )
    plan = b3d.typical_plan(doc, "АР · лист 1")
    assert plan == b3d.TypicalPlan(
        "К10 · С12-14 · 7 эт. (по листу «5, 7 эт.»)",
        (("К10 · С12-14 · 5 эт. (по листу «5, 7 эт.»)", -6600),),
    )
    # Отметок меньше, чем этажей: разнести нечем.
    none = WallsDocument.model_validate(raw_document(title=typical_title([4, 5, 6], [])))
    assert b3d.typical_plan(none, "АР · лист 1") is None
    single = WallsDocument.model_validate(raw_document(title=typical_title([1], [1050, 1750])))
    assert b3d.typical_plan(single, "АР · лист 1") is None


def test_typical_sheet_is_shown_on_every_floor_of_its_title() -> None:
    stack = assembly.build_stack([typical_item([5, 7], [17700, 24300])])
    own, copy = stack.floors
    assert (own.label, own.typical_of) == ("К10 · С12-14 · 5 эт. (по листу «5, 7 эт.»)", None)
    assert copy.label == "К10 · С12-14 · 7 эт. (по листу «5, 7 эт.»)"
    assert copy.typical_of == "К10 · С12-14 · 5, 7 эт."
    assert copy.base_z_mm - own.base_z_mm == 6600
    assert (copy.outline, copy.job_id, copy.page_index) == (own.outline, own.job_id, own.page_index)
    assert stack.groups[0].floor_count == 2


def test_typical_copy_is_not_put_on_a_level_taken_by_its_own_sheet() -> None:
    """Лист «3-7 эт.» и отдельный лист 6 этажа: на отметке 6 этажа копии нет."""
    marks = [12300, 15600, 18900, 22200, 25500]
    typical = typical_item([3, 4, 5, 6, 7], marks)
    sixth = built(corps="10", section="12-14", order=1, elevation=22200)
    stack = assembly.build_stack([typical, sixth])
    assert len(stack.floors) == 5
    assert [f.typical_of is not None for f in stack.floors] == [False, True, True, False, True]
    assert [f.base_z_mm - stack.floors[0].base_z_mm for f in stack.floors] == [
        0,
        3300,
        6600,
        9900,
        13200,
    ]


# ------------------------------------------------------------------ высота по стопке


def unknown_height(item: b3d.BuiltFloor) -> b3d.BuiltFloor:
    return patched(item, floor_height_mm=b3d.DEFAULT_FLOOR_HEIGHT_MM, floor_height_known=False)


def test_unknown_height_takes_the_step_to_the_next_floor_of_the_building() -> None:
    lower = unknown_height(built(elevation=BASE))
    middle = unknown_height(built(order=1, elevation=BASE + 3600))
    top = unknown_height(built(order=2, elevation=BASE + 7200))
    far = unknown_height(built(corps="1", section="1", order=3, elevation=BASE + 100))
    stack = assembly.build_stack([lower, middle, top, far])
    by_order = {f.page_index: f for f in stack.floors}
    assert (by_order[0].floor_height_mm, by_order[0].floor_height_source) == (3600, "derived_stack")
    assert (by_order[1].floor_height_mm, by_order[1].floor_height_source) == (3600, "derived_stack")
    # Верхний этаж здания и здание из одного листа: соседа сверху нет - типовая высота.
    assert (by_order[2].floor_height_mm, by_order[2].floor_height_source) == (3000, "default")
    assert (by_order[3].floor_height_mm, by_order[3].floor_height_source) == (3000, "default")
    assert not any(f.floor_height_known for f in stack.floors)


def test_step_out_of_range_and_the_same_level_do_not_give_a_height() -> None:
    known = built(elevation=BASE)
    floors = assembly.stack_heights(
        [
            unknown_height(built(elevation=BASE)).floor,
            # Лист того же уровня (отметка на 100 мм выше) - не следующий этаж.
            unknown_height(built(order=1, elevation=BASE + 100)).floor,
            unknown_height(built(order=2, elevation=BASE + 1900)).floor,
            unknown_height(built(order=3, elevation=BASE + 11800)).floor,
            known.floor,
        ]
    )
    assert [(f.floor_height_mm, f.floor_height_source) for f in floors] == [
        (3000, "default"),  # до следующего 1900 - меньше нижней границы
        (3000, "default"),
        (3000, "default"),  # до следующего 9900: этажей между ними нет в 3D
        (3000, "default"),
        (3000, None),
    ]
    assert floors[4].floor_height_known is True


# ------------------------------------------------------------------ ответ целиком

FLOOR_TITLE = {"corps": "9", "section": "3", "floors": [2], "text": None, "kind": "floor"}


def walls_bytes(title: dict[str, Any] | None, *, elevation: int, height: int | None) -> bytes:
    raw = raw_document()
    raw["generator"] = "cad_walls.v1.15"
    raw["heights"] = heights(
        title=title,
        floor_elevation_mm=elevation,
        floor_height_mm=height,
        height_status="derived" if height is not None else "missing",
    )
    return json.dumps({**raw_extras(), **raw}).encode()


async def test_response_lists_service_sheets_and_follows_the_stack_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b3d.floor_cache.clear()
    storage = FakeObjectStorage()
    refs: list[b3d.SheetRef] = []
    plans: list[tuple[dict[str, Any] | None, int, str | None]] = [
        (FLOOR_TITLE, BASE, None),
        ({**FLOOR_TITLE, "floors": [3]}, BASE + 3300, "floor_plan"),
        (None, BASE + 900, "section"),
    ]
    for index, (title, elevation, passport_kind) in enumerate(plans):
        key = f"walls-{index}"
        await storage.put_bytes(
            key,
            walls_bytes(title, elevation=elevation, height=None),
            content_type="application/json",
        )
        refs.append(
            dataclasses.replace(
                sheet(order=(0.0, 0.0, index, 1)),
                walls_key=key,
                label=f"АР · лист {index + 1}",
                passport_kind=passport_kind,
            )
        )

    async def collect(
        _session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[list[b3d.SheetRef], list[object], None]:
        return list(refs), [], None

    async def no_missing(_session: AsyncSession, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(b3d, "collect_sheets", collect)
    monkeypatch.setattr(assembly, "collect_missing_plans", no_missing)
    # Ручные привязки корпусов (ADR-0052) читаются из базы: в этом тесте базы нет.
    monkeypatch.setattr(cad_site_pins, "active_site_pins", _no_pins)
    body = await assembly.build_building3d(
        cast(AsyncSession, object()), storage, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
    )
    b3d.floor_cache.clear()
    assert [f.label for f in body.floors] == ["К9 · С3 · 2 эт.", "К9 · С3 · 3 эт."]
    lower, upper = body.floors
    assert (lower.floor_height_mm, lower.floor_height_source) == (3300, "derived_stack")
    assert (upper.floor_height_mm, upper.floor_height_source) == (3000, "default")
    # Предупреждение «высота типовая» остаётся только у этажа без соседа сверху.
    assert [w.message for w in body.warnings if w.code == "floor_height_default"] == [
        "АР · лист 2: высота этажа не определена, показана типовая."
    ]
    (service,) = body.service_sheets
    assert (service.reason, service.page_index) == ("not_plan", 2)
    assert service.message == "АР · лист 3: не план этажа: по паспорту листа - разрез."


async def test_response_lists_unplaced_summary_sheet_as_service_sheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b3d.floor_cache.clear()
    storage = FakeObjectStorage()
    summary_title: dict[str, Any] = {
        "corps": None,
        "section": "17",
        "floors": [],
        "text": None,
        "kind": "technical",
    }
    refs: list[b3d.SheetRef] = []
    for index, (title, stamp) in enumerate(
        [
            (FLOOR_TITLE, None),
            (summary_title, "Секции 8, 9, 10, 15-16, 17, 18, 19, 20. План тех. пространств"),
        ]
    ):
        key = f"walls-{index}"
        await storage.put_bytes(
            key, walls_bytes(title, elevation=BASE, height=3300), content_type="application/json"
        )
        refs.append(
            dataclasses.replace(
                sheet(order=(0.0, 0.0, index, 1)),
                walls_key=key,
                label=f"АР · лист {index + 1}",
                stamp_title=stamp,
            )
        )

    async def collect(
        _session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[list[b3d.SheetRef], list[object], None]:
        return list(refs), [], None

    async def no_missing(_session: AsyncSession, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(b3d, "collect_sheets", collect)
    monkeypatch.setattr(assembly, "collect_missing_plans", no_missing)
    monkeypatch.setattr(cad_site_pins, "active_site_pins", _no_pins)
    body = await assembly.build_building3d(
        cast(AsyncSession, object()), storage, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
    )
    b3d.floor_cache.clear()
    assert [f.label for f in body.floors] == ["К9 · С3 · 2 эт."]
    assert [g.key for g in body.groups] == ["k9-s3"]
    assert not [w for w in body.warnings if w.code == "groups_not_placed"]
    (service,) = body.service_sheets
    assert (service.reason, service.page_index) == ("summary_unplaced", 1)
    assert service.message.startswith("АР · лист 2: сводный лист с планами нескольких секций")


# ------------------------------------------------------------------ планов нет в 3D


def convert_job(views: list[dict[str, Any]], *, error: str | None = None) -> Job:
    return Job(
        job_type=JobType.CAD_PDF_CONVERT,
        status=JobStatus.FAILED if error else JobStatus.SUCCEEDED,
        error_code=error,
        payload={"cad_result": {"attempt": 1, "pages": [{"index": 4, "views": views}]}},
    )


def test_convert_failure_code_comes_from_the_view_then_from_the_job() -> None:
    failed = convert_job([{"view": 1, "status": "failed", "failure_code": "CAD_NO_GEOMETRY"}])
    assert assembly._convert_failure(failed, 4) == "CAD_NO_GEOMETRY"
    unscaled = convert_job([{"view": 1, "status": "needs_review", "scale_status": "needs_review"}])
    assert assembly._convert_failure(unscaled, 4) == "needs_review"
    # Итога страницы нет: код ошибки задания, а без него - его статус.
    assert assembly._convert_failure(convert_job([], error="CAD_ENGINE_FAILED"), 4) == (
        "CAD_ENGINE_FAILED"
    )
    assert assembly._convert_failure(convert_job([{"view": 1, "status": "passed"}]), 9) == (
        "succeeded"
    )


def test_review_placement_gets_its_own_warning_and_sure_placement_does_not() -> None:
    def group(key: str, placement: str, message: str | None) -> CadBuilding3dGroupRead:
        return CadBuilding3dGroupRead.model_validate(
            {
                "key": key,
                "label": f"Корп. {key}",
                "floor_count": 3,
                "aligned_count": 3,
                "placement": placement,
                "site_offset_mm": (0.0, 0.0),
                "placement_axes": [],
                "placement_anchor": None,
                "placement_message": message,
            }
        )

    warnings = assembly.review_warnings(
        [
            group("1", "cores", "на проверку: посадка по согласию этажей, 2 из 3 этажей"),
            group("2", "cores", None),
            group("3", "none", "по ядрам не совмещено"),
        ]
    )
    assert [(w.code, w.message) for w in warnings] == [
        (
            "group_placement_review",
            "Корп. 1: на проверку: посадка по согласию этажей, 2 из 3 этажей",
        )
    ]
