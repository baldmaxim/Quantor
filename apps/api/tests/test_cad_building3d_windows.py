"""Окна этажей в общем 3D здания (ADR-0048 п. 6): высоты, обрезка по верху стены, сдвиг и поворот.

Ожидаемые числа выписаны руками. Этаж: верх плиты 47600, высота этажа 3000, плита 200 - верх стены
50400. Окно листа: контур 1000 x 200 мм, подоконник 900, верх 2400 мм от чистого пола.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import CadFrameRead
from app.contracts.cad_building3d import CadBuilding3dFloorRead, CadBuilding3dRead
from app.contracts.cad_constructions import CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import (
    cad_axis_coordination_jobs,
    cad_building3d_grid,
    cad_project_levels,
    cad_site_pins,
)
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from app.services import cad_building3d_windows as windows
from app.services import cad_facade_windows as fw
from app.services.cad_constructions import ProjectSlab
from tests.conftest import FakeObjectStorage
from tests.test_cad_facade_windows import FACADE_OK, view
from tests.test_cad_floor3d import BASE, NO_LEVELS, raw_document, raw_extras

WALLS_KEY = "walls/k1.json"
WALL_TOP = BASE + 2800
WINDOW_RING = [[3000.0, 0.0], [4000.0, 0.0], [4000.0, 200.0], [3000.0, 200.0]]
FRAME = CadFrameRead(
    confirmed=True, reason=None, units="mm", origin_pt=(0.0, 0.0), mm_per_pdf_point=1.0
)


def _levels(sill: int | None, head: int | None) -> CadSheetLevelsRead:
    return NO_LEVELS.model_copy(update={"window_sill_mm": sill, "window_head_mm": head})


def _raw(
    *,
    axes: bool = False,
    no_lintel: bool = False,
    heights_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = raw_document(**(heights_patch or {}))
    window = {
        "id": "win00000001",
        "kind": "window",
        "status": "no_data",
        "host_id": "aaaaaaaaaaaa",
        "adjacent_ids": [],
        "width_mm": 1000.0,
        "width_source": "window_bay",
        "thickness_mm": 200.0,
        "block_name": None,
        "handle": None,
        "center": [3500.0, 100.0],
        "opening_height_mm": None,
    }
    # В walls.json проём и его контур лежат в одной записи `openings`.
    window["direction"] = [1.0, 0.0]
    if not no_lintel:
        window["lintel"] = WINDOW_RING
    document["openings"] = [*document["openings"], window]
    extras = raw_extras()
    raw: dict[str, Any] = {**extras, **document}
    if axes:
        raw["axes"] = {
            "items": [
                {"label": "1", "orient": "vertical", "pos_pt": 0.0},
                {"label": "2", "orient": "vertical", "pos_pt": 6000.0},
            ]
        }
    return raw


def _sheet(overrides: CadSheetLevelsRead = NO_LEVELS, *, number: int = 1) -> b3d.SheetRef:
    return b3d.SheetRef(
        job_id=uuid.UUID(int=number),
        revision_id=uuid.UUID(int=2),
        document_id=uuid.UUID(int=3),
        page_index=0,
        view=1,
        label=f"АР · лист {number}",
        order=(0.0, 0.0, 0, number),
        overrides=overrides,
        walls_key=WALLS_KEY if number == 1 else f"walls/k{number}.json",
    )


def _built(raw: dict[str, Any], levels: CadSheetLevelsRead, frame: CadFrameRead | None) -> Any:
    item = b3d._sheet_floor(_sheet(levels), raw, frame, None, True)
    assert item.floor is not None
    return item


def _floor_windows(item: Any, views: Sequence[fw.FacadeViewInput] = ()) -> windows.FloorWindows:
    assert item.windows is not None
    return windows.floor_windows(item.windows, item.floor.base_z_mm, fw.LoadedViews(list(views)))


def _finalized(item: Any, reads: list[Any]) -> CadBuilding3dFloorRead:
    floor = item.floor.model_copy(update={"windows": reads})
    return windows.finalize_windows(floor)


# ------------------------------------------------------------------ высоты и обрезка по стене


def test_manual_input_builds_sill_glass_and_lintel_without_a_frame() -> None:
    item = _built(_raw(), _levels(900, 2400), None)
    result = _floor_windows(item)
    assert result.without_height == 0
    floor = _finalized(item, result.windows)
    assert floor.windows is not None
    (window,) = floor.windows
    assert window.opening_id == "win00000001"
    assert (window.sill_z_bottom_mm, window.glass_z_bottom_mm) == (BASE, BASE + 900)
    assert (window.glass_z_top_mm, window.lintel_z_top_mm) == (BASE + 2400, WALL_TOP)
    assert window.accepted is True and window.source == "manual"
    assert window.shell == [[3000, 0], [4000, 0], [4000, 200], [3000, 200]]


def test_window_without_sill_has_no_sill_part() -> None:
    item = _built(_raw(), _levels(0, 2100), None)
    floor = _finalized(item, _floor_windows(item).windows)
    assert floor.windows is not None
    (window,) = floor.windows
    assert window.sill_z_bottom_mm == window.glass_z_bottom_mm == BASE


def test_head_not_below_wall_top_has_no_lintel_and_is_clipped() -> None:
    item = _built(_raw(), _levels(900, 3000), None)
    floor = _finalized(item, _floor_windows(item).windows)
    assert floor.windows is not None
    (window,) = floor.windows
    assert window.glass_z_top_mm == window.lintel_z_top_mm == WALL_TOP


def test_window_starting_above_wall_top_is_dropped() -> None:
    item = _built(_raw(), _levels(2900, 3300), None)
    floor = _finalized(item, _floor_windows(item).windows)
    assert floor.windows == []


def test_without_height_nothing_is_issued_and_it_is_counted() -> None:
    item = _built(_raw(), NO_LEVELS, None)
    result = _floor_windows(item)
    assert result.windows == [] and result.without_height == 1
    assert windows.summarize([result]).without_height == 1


def test_window_with_own_height_in_walls_json_is_not_issued() -> None:
    raw = _raw()
    raw["openings"][-1]["opening_height_mm"] = 1500
    item = b3d._sheet_floor(_sheet(), raw, None, None, True)
    assert item.windows is None


def test_without_walls_windows_are_not_prepared() -> None:
    item = b3d._sheet_floor(_sheet(_levels(900, 2400)), _raw(), None, None, False)
    assert item.floor is not None and item.windows is None and item.floor.windows is None


# ------------------------------------------------------------------ фасады


def _facade_item(frame: CadFrameRead | None) -> Any:
    raw = _raw(axes=True)
    # План листа в ту же систему, что у проверенных видов фасадов (чистый пол 47600).
    return _built(raw, NO_LEVELS, frame)


def test_candidate_facade_view_gives_a_pale_candidate_window() -> None:
    item = _facade_item(FRAME)
    result = _floor_windows(item, [view([FACADE_OK], accepted=False)])
    floor = _finalized(item, result.windows)
    assert floor.windows is not None
    (window,) = floor.windows
    assert window.accepted is False and window.source == "facade"
    assert (window.glass_z_bottom_mm, window.glass_z_top_mm) == (BASE + 900, BASE + 2400)


def test_window_on_a_non_main_slab_part_gets_the_facade_height() -> None:
    # Основная (большая) часть плиты правее окна; окно на южной стене малой части (лист из двух
    # корпусов): по одному `slab.shell` окно «не наружное», по всем частям - берёт высоту фасада.
    raw = _raw(axes=True)
    main = [[8000.0, 0.0], [14000.0, 0.0], [14000.0, 4000.0], [8000.0, 4000.0]]
    small = [[2500.0, 0.0], [5000.0, 0.0], [5000.0, 4000.0], [2500.0, 4000.0]]
    raw["slab"] = {
        "shell": main,
        "area_mm2": 34_000_000.0,
        "parts": [
            {"shell": main, "area_mm2": 24_000_000.0},
            {"shell": small, "area_mm2": 10_000_000.0},
        ],
    }
    item = _built(raw, NO_LEVELS, FRAME)
    assert item.windows is not None and item.windows.slab_rings == [main, small]
    (window,) = _floor_windows(item, [view([FACADE_OK])]).windows
    assert window.accepted is True and window.source == "facade"
    assert (window.glass_z_bottom_mm, window.glass_z_top_mm) == (BASE + 900, BASE + 2400)


def test_accepted_facade_view_gives_an_accepted_window() -> None:
    item = _facade_item(FRAME)
    (window,) = _floor_windows(item, [view([FACADE_OK])]).windows
    assert window.accepted is True and window.source == "facade"


def test_manual_input_beats_a_candidate_facade_view() -> None:
    raw = _raw(axes=True)
    item = _built(raw, _levels(800, 2000), FRAME)
    (window,) = _floor_windows(item, [view([FACADE_OK], accepted=False)]).windows
    assert (window.source, window.accepted) == ("manual", True)
    assert (window.glass_z_bottom_mm, window.glass_z_top_mm) == (BASE + 800, BASE + 2000)


def test_unconfirmed_frame_gives_no_facade_windows_but_a_remark() -> None:
    bad = CadFrameRead(
        confirmed=False,
        reason="масштаб не прошёл проверку",
        units=None,
        origin_pt=None,
        mm_per_pdf_point=None,
    )
    item = _facade_item(bad)
    result = _floor_windows(item, [view([FACADE_OK])])
    assert result.windows == [] and result.without_height == 1
    assert [issue.code for issue in result.issues] == ["facade_windows_no_frame"]


def test_manual_input_without_axes_needs_no_frame_even_when_views_exist() -> None:
    item = _built(_raw(), _levels(900, 2400), None)
    result = _floor_windows(item, [view([FACADE_OK])])
    assert len(result.windows) == 1 and result.windows[0].source == "manual"


# ------------------------------------------------------------------ сдвиг, поворот, типовой лист


def _floor_with_window() -> CadBuilding3dFloorRead:
    item = _built(_raw(), _levels(900, 2400), None)
    return _finalized(item, _floor_windows(item).windows)


def test_shift_moves_the_window_shell_like_walls() -> None:
    floor = _floor_with_window()
    moved = b3d._shifted(floor, 1000.0, -500.0)
    assert moved.windows is not None and floor.windows is not None
    assert moved.windows[0].shell == [[x + 1000, y - 500] for x, y in floor.windows[0].shell]
    assert moved.windows[0].glass_z_top_mm == floor.windows[0].glass_z_top_mm


def test_turn_by_90_degrees_rotates_the_window_shell_around_the_origin() -> None:
    floor = _floor_with_window()
    turned = b3d._rotated(floor, 90.0, 10.0, 20.0)
    assert turned.windows is not None
    # R(90): (x, y) -> (-y, x), затем сдвиг (10, 20).
    assert turned.windows[0].shell == [[10, 3020], [10, 4020], [-190, 4020], [-190, 3020]]


def test_typical_copy_lifts_all_window_levels() -> None:
    floor = _floor_with_window()
    lifted = assembly._lifted(floor, 3000)
    assert lifted.windows is not None and floor.windows is not None
    a, b = floor.windows[0], lifted.windows[0]
    assert (b.sill_z_bottom_mm, b.glass_z_bottom_mm) == (
        a.sill_z_bottom_mm + 3000,
        a.glass_z_bottom_mm + 3000,
    )
    assert (b.glass_z_top_mm, b.lintel_z_top_mm) == (
        a.glass_z_top_mm + 3000,
        a.lintel_z_top_mm + 3000,
    )


# ------------------------------------------------------------------ ответ здания целиком


@pytest.fixture(autouse=True)
def empty_cache() -> Iterator[None]:
    b3d.floor_cache.clear()
    yield
    b3d.floor_cache.clear()


def _serve(monkeypatch: pytest.MonkeyPatch, sheets: list[b3d.SheetRef], loads: list[int]) -> None:
    async def collect(
        _session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[list[b3d.SheetRef], list[object], ProjectSlab | None]:
        return list(sheets), [], None

    async def no_missing(_session: AsyncSession, **_kwargs: object) -> list[object]:
        return []

    async def no_pins(_session: AsyncSession, **_kwargs: object) -> list[object]:
        return []

    async def no_levels(_session: AsyncSession, **_kwargs: object) -> dict[object, object]:
        return {}

    async def load_views(
        _session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> fw.LoadedViews:
        loads.append(1)
        return fw.LoadedViews([])

    monkeypatch.setattr(b3d, "collect_sheets", collect)
    monkeypatch.setattr(assembly, "collect_missing_plans", no_missing)
    monkeypatch.setattr(cad_site_pins, "active_site_pins", no_pins)
    monkeypatch.setattr(cad_project_levels, "load_project_levels", no_levels)
    monkeypatch.setattr(cad_axis_coordination_jobs, "load_hints", AsyncMock(return_value={}))
    monkeypatch.setattr(cad_building3d_grid, "load_model_reference", _no_model)
    monkeypatch.setattr(fw, "load_views", load_views)


async def _build(storage: FakeObjectStorage, *, walls: bool = True) -> CadBuilding3dRead:
    return await assembly.build_building3d(
        cast(AsyncSession, object()),
        storage,
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        include_walls=walls,
    )


async def test_building_response_carries_windows_with_manual_height_and_loads_views_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeObjectStorage()
    await storage.put_bytes(WALLS_KEY, json.dumps(_raw()).encode(), content_type="application/json")
    loads: list[int] = []
    sheets = [_sheet(_levels(900, 2400))]
    _serve(monkeypatch, sheets, loads)
    body = await _build(storage)
    (floor,) = body.floors
    assert floor.windows is not None and len(floor.windows) == 1
    window = floor.windows[0]
    assert (window.sill_z_bottom_mm, window.glass_z_bottom_mm) == (BASE, BASE + 900)
    assert (window.glass_z_top_mm, window.lintel_z_top_mm) == (BASE + 2400, WALL_TOP)
    assert loads == [1]
    # Повторный запрос берёт этаж из кеша, окна считаются заново и дают то же.
    again = await _build(storage)
    assert again.floors[0].windows == floor.windows


async def test_floor_without_height_has_no_windows_and_the_building_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeObjectStorage()
    await storage.put_bytes(WALLS_KEY, json.dumps(_raw()).encode(), content_type="application/json")
    _serve(monkeypatch, [_sheet()], [])
    body = await _build(storage)
    assert body.floors[0].windows == []
    assert windows.CODE_WITHOUT_HEIGHT in [w.code for w in body.warnings]


async def test_windows_are_not_requested_without_walls(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = FakeObjectStorage()
    await storage.put_bytes(WALLS_KEY, json.dumps(_raw()).encode(), content_type="application/json")
    loads: list[int] = []
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], loads)
    body = await _build(storage, walls=False)
    assert body.floors[0].windows is None and loads == []


async def test_failure_of_one_floor_gives_an_empty_list_and_a_remark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeObjectStorage()
    await storage.put_bytes(WALLS_KEY, json.dumps(_raw()).encode(), content_type="application/json")
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])

    def boom(*_args: object, **_kwargs: object) -> windows.FloorWindows:
        raise ValueError("повреждённый контур")

    monkeypatch.setattr(windows, "floor_windows", boom)
    body = await _build(storage)
    assert body.floors[0].windows == []
    assert windows.CODE_FAILED in [w.code for w in body.warnings]
    assert body.floors[0].walls is not None


def test_walls_document_fixture_is_valid() -> None:
    raw = _raw()
    WallsDocument.model_validate(raw)
    WallsFloorExtras.model_validate(raw)


# ------------------------------------------------------------------ замечания и сбои


def _codes(body: CadBuilding3dRead) -> list[str]:
    return [w.code for w in body.warnings]


def _message(body: CadBuilding3dRead, code: str) -> str:
    return next(w.message for w in body.warnings if w.code == code)


async def _stored(*raws: dict[str, Any]) -> FakeObjectStorage:
    storage = FakeObjectStorage()
    for number, raw in enumerate(raws, start=1):
        key = WALLS_KEY if number == 1 else f"walls/k{number}.json"
        await storage.put_bytes(key, json.dumps(raw).encode(), content_type="application/json")
    return storage


def test_window_with_height_but_without_contour_is_counted_not_silent() -> None:
    item = _built(_raw(no_lintel=True), _levels(900, 2400), None)
    result = _floor_windows(item)
    assert result.windows == [] and result.no_contour == 1 and result.without_height == 0
    assert windows.summarize([result]).no_contour == 1


async def test_building_warns_about_windows_without_contour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = await _stored(_raw(no_lintel=True))
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])
    body = await _build(storage)
    assert body.floors[0].windows == []
    assert "1" in _message(body, windows.CODE_NO_CONTOUR)


async def test_without_height_message_says_the_opening_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = await _stored(_raw())
    _serve(monkeypatch, [_sheet()], [])
    body = await _build(storage)
    text = _message(body, windows.CODE_WITHOUT_HEIGHT)
    assert "проём остаётся открытым" in text and "стена сплошная" not in text


async def test_default_floor_height_builds_no_windows_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw(heights_patch={"floor_height_mm": None, "height_status": "missing"})
    storage = await _stored(raw)
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])
    body = await _build(storage)
    (floor,) = body.floors
    assert floor.floor_height_known is False and floor.floor_height_source == "default"
    assert floor.windows == []
    assert "Этажей: 1" in _message(body, windows.CODE_WALL_HEIGHT_UNKNOWN)


async def test_default_slab_thickness_builds_no_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _raw(heights_patch={"slab_thickness_mm": None, "slab_status": "missing"})
    storage = await _stored(raw)
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])
    body = await _build(storage)
    assert body.floors[0].slab_thickness_known is False
    assert body.floors[0].windows == []
    assert windows.CODE_WALL_HEIGHT_UNKNOWN in _codes(body)


async def test_height_derived_from_the_next_floor_still_builds_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw(heights_patch={"floor_height_mm": None, "height_status": "missing"})
    storage = await _stored(raw, raw)
    lower = _levels(900, 2400)
    upper = lower.model_copy(update={"floor_elevation_mm": BASE + 3000})
    _serve(monkeypatch, [_sheet(lower), _sheet(upper, number=2)], [])
    body = await _build(storage)
    by_base = {floor.base_z_mm: floor for floor in body.floors}
    assert by_base[BASE].floor_height_source == "derived_stack"
    assert [w.opening_id for w in by_base[BASE].windows or []] == ["win00000001"]
    # Верхний этаж - типовая высота: окон нет, замечание про один этаж.
    assert by_base[BASE + 3000].windows == []
    assert "Этажей: 1" in _message(body, windows.CODE_WALL_HEIGHT_UNKNOWN)


async def test_superseded_duplicate_is_not_counted_in_window_remarks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = await _stored(_raw(), _raw())
    _serve(monkeypatch, [_sheet(), _sheet(number=2)], [])
    # Признаки дубля (оси, монолит) в синтетике громоздки: дубль назначается напрямую.
    monkeypatch.setattr(assembly, "find_superseded", lambda _items, _aligned: {1: 0})
    body = await _build(storage)
    assert [s.reason for s in body.service_sheets] == ["superseded"]
    assert len(body.floors) == 1
    assert "1 (этажей: 1)" in _message(body, windows.CODE_WITHOUT_HEIGHT)


@pytest.mark.parametrize("error", [RuntimeError("сбой"), KeyError("x"), ZeroDivisionError()])
async def test_any_error_of_a_floor_gives_an_empty_list_and_a_remark(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    storage = await _stored(_raw())
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])

    def boom(*_args: object, **_kwargs: object) -> windows.FloorWindows:
        raise error

    monkeypatch.setattr(windows, "floor_windows", boom)
    body = await _build(storage)
    assert body.floors[0].windows == []
    assert windows.CODE_FAILED in _codes(body)


async def test_views_read_failure_empties_windows_of_the_building_but_not_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = await _stored(_raw())
    _serve(monkeypatch, [_sheet(_levels(900, 2400))], [])

    async def broken(*_args: object, **_kwargs: object) -> fw.LoadedViews:
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(fw, "load_views", broken)
    body = await _build(storage)
    assert len(body.floors) == 1 and body.floors[0].windows == []
    assert body.floors[0].walls is not None
    assert _codes(body).count(windows.CODE_VIEWS_FAILED) == 1


async def _no_model(*_args: object, **_kwargs: object) -> None:
    """Утверждённой модели здания нет: сборка как без IFC."""
    return None
