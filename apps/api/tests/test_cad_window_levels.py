"""Ручные подоконник и высота окна листа (ADR-0048 п. 5): контракт, приоритет, 3D, кладка, секция.

Окно без `opening_height_mm` получает высоту: принятый вид фасада, затем ручной ввод листа (он
проверен человеком), затем вид-кандидат фасада (только 3D). Нет ручного ввода - поля пустые, окна
без высоты остаются с замечанием. Ожидаемые числа выписаны руками.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.cad_floor3d import _without_unaccepted_windows
from app.contracts.cad_constructions import (
    CadSheetFloorTitle,
    CadSheetLevelsRead,
    CadSheetLevelsWrite,
    WallsDocument,
)
from app.contracts.cad_floor3d import WallsFloorExtras
from app.models import CadSheetLevels
from app.services import cad_building3d, cad_views, cad_window_levels
from app.services import cad_constructions as calc
from app.services import cad_facade_windows as fw
from app.services import cad_floor3d as f3d
from app.storage.base import ObjectNotFoundError, StorageUnavailableError
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_constructions_api import _ready_sheet, _url, walls_settings, walls_tools
from tests.test_cad_constructions_calc import NO_LEVELS, construction, document
from tests.test_cad_floor3d import BASE, raw_document, raw_extras
from tests.test_cad_windows_contract import WINDOW_LINTEL, facade_height, window

__all__ = ["walls_tools"]

OPENING = "win00000001"


def levels(sill: int | None = None, head: int | None = None) -> CadSheetLevelsRead:
    return CadSheetLevelsRead(
        floor_height_mm=None,
        slab_thickness_mm=None,
        door_height_mm=None,
        floor_elevation_mm=None,
        window_sill_mm=sill,
        window_head_mm=head,
    )


def doc_with_window(height: int | None = None) -> WallsDocument:
    return document([construction()], [window(status="ok", height=height)])


# ------------------------------------------------------------------ контракт


@pytest.mark.parametrize(("sill", "head"), [(0, 1500), (900, 2400), (5999, 6000), (None, None)])
def test_write_accepts_a_consistent_window_pair(sill: int | None, head: int | None) -> None:
    body = CadSheetLevelsWrite(window_sill_mm=sill, window_head_mm=head)
    assert (body.window_sill_mm, body.window_head_mm) == (sill, head)


@pytest.mark.parametrize(
    ("sill", "head"),
    [
        (900, None),
        (None, 2400),
        (2400, 2400),
        (2500, 2400),
        (-1, 1000),
        (0, 6001),
        (0, 0),
        (6000, 6000),
    ],
)
def test_write_rejects_an_inconsistent_window_pair(sill: int | None, head: int | None) -> None:
    with pytest.raises(ValidationError):
        CadSheetLevelsWrite(window_sill_mm=sill, window_head_mm=head)


def test_effective_levels_mark_the_window_pair_as_manual_or_unset() -> None:
    unset = calc.effective_levels(doc_with_window().heights, levels())
    assert unset.window_sill.value_mm is None and unset.window_sill.source is None
    assert unset.window_head.value_mm is None and unset.window_head.source is None
    manual = calc.effective_levels(doc_with_window().heights, levels(900, 2400))
    assert (manual.window_sill.value_mm, manual.window_sill.source) == (900, "manual")
    read = calc.heights_read(doc_with_window().heights, manual)
    assert read.window_head.model_dump() == {
        "value_mm": 2400,
        "source": "manual",
        "default_mm": None,
    }


# ------------------------------------------------------------------ приоритет высоты


def _match(*heights: tuple[str, fw.FacadeWindowHeight]) -> fw.FacadeMatch:
    return fw.FacadeMatch(dict(heights), (fw.MatchIssue("facade_view_not_linked", "тест"),))


def test_without_manual_input_the_facade_match_is_unchanged() -> None:
    match = _match((OPENING, facade_height(accepted=False)))
    openings = doc_with_window().openings
    assert fw.merge_manual_heights(match, openings, None, None) is match
    assert fw.merge_manual_heights(match, openings, 900, None) is match


def test_accepted_facade_beats_manual_input() -> None:
    match = _match((OPENING, facade_height(sill=700, head=2200)))
    merged = fw.merge_manual_heights(match, doc_with_window().openings, 900, 2400)
    found = merged.heights[OPENING]
    assert (found.sill_mm, found.head_mm, found.source) == (700, 2200, "facade")


def test_manual_input_beats_a_candidate_facade_height() -> None:
    match = _match((OPENING, facade_height(sill=700, head=2200, accepted=False)))
    found = fw.merge_manual_heights(match, doc_with_window().openings, 900, 2400).heights[OPENING]
    assert (found.sill_mm, found.head_mm, found.source, found.accepted) == (
        900,
        2400,
        "manual",
        True,
    )
    assert found.view_id is None and found.view_key is None and found.axes_checked is False


def test_manual_input_fills_windows_without_any_facade_height_and_drops_issues() -> None:
    merged = fw.merge_manual_heights(fw.FacadeMatch(), doc_with_window().openings, 900, 2400)
    assert merged.heights[OPENING].source == "manual" and merged.issues == ()
    noisy = fw.merge_manual_heights(_match(), doc_with_window().openings, 900, 2400)
    assert noisy.issues == ()


def test_manual_input_keeps_view_invalid_and_height_conflict_issues() -> None:
    match = fw.FacadeMatch(
        {},
        (
            fw.MatchIssue(fw.CODE_VIEW_INVALID, "вид вне контракта"),
            fw.MatchIssue(fw.CODE_CONFLICT, "конфликт высот"),
            fw.MatchIssue(fw.CODE_NOT_LINKED, "нет привязки"),
            fw.MatchIssue(fw.CODE_NO_LEVEL, "нет отметки"),
            fw.MatchIssue(fw.CODE_OTHER_BUILDING, "другой корпус"),
        ),
    )
    merged = fw.merge_manual_heights(match, doc_with_window().openings, 900, 2400)
    assert [i.code for i in merged.issues] == [fw.CODE_VIEW_INVALID, fw.CODE_CONFLICT]
    assert merged.heights[OPENING].source == "manual"


def test_manual_input_does_not_touch_windows_with_their_own_height_or_other_kinds() -> None:
    openings = doc_with_window(height=1500).openings
    assert fw.merge_manual_heights(fw.FacadeMatch(), openings, 900, 2400).heights == {}
    plain = document([construction()], []).openings
    assert fw.merge_manual_heights(fw.FacadeMatch(), plain, 900, 2400).heights == {}


# ------------------------------------------------------------------ 3D и кладка


def _manual() -> fw.FacadeWindowHeight:
    merged = fw.merge_manual_heights(fw.FacadeMatch(), doc_with_window().openings, 900, 2400)
    return merged.heights[OPENING]


def _build_3d(height: fw.FacadeWindowHeight | None) -> Any:
    raw = raw_document()
    raw["openings"] = [window(OPENING, "aaaaaaaaaaaa")]
    extras = raw_extras()
    extras["openings"] = [
        {"id": OPENING, "direction": [1.0, 0.0], "lintel": WINDOW_LINTEL, "leaf": None}
    ]
    return f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(extras),
        props_by_key={},
        overrides=levels(),
        project_slab=None,
        hole_decisions={},
        door_zones=[],
        window_heights=None if height is None else {OPENING: height},
    )


def test_floor3d_builds_a_manual_window_as_accepted_without_facade_fields() -> None:
    model = _build_3d(_manual())
    [item] = model.windows
    assert item.source == "manual" and item.accepted is True and item.axes_checked is False
    assert (item.sill_mm, item.head_mm) == (900, 2400)
    assert (item.sill_z_bottom_mm, item.sill_z_top_mm, item.glass_z_top_mm) == (
        BASE,
        BASE + 900,
        BASE + 2400,
    )
    assert item.facade_view_key is None and item.facade_page_index is None
    assert item.facade_revision_id is None and item.facade_title is None
    [lintel] = model.lintels
    assert (lintel.z_bottom_mm, lintel.door_height_source) == (BASE + 2400, "manual")
    codes = [w.code for w in model.warnings]
    assert "window_height_unknown" not in codes and "facade_windows_unaccepted" not in codes


def test_floor3d_facade_window_keeps_the_facade_source() -> None:
    [item] = _build_3d(facade_height()).windows
    assert item.source == "facade" and item.facade_view_key == "p36v1"


def test_floor3d_window_without_any_height_keeps_the_warning() -> None:
    model = _build_3d(None)
    assert model.windows == []
    assert [w.code for w in model.warnings].count("window_height_unknown") == 1


def test_dxf_model_keeps_manual_windows() -> None:
    model = _build_3d(_manual())
    assert _without_unaccepted_windows(model) is model


def test_manual_window_is_subtracted_from_the_masonry_volume() -> None:
    spans = {OPENING: _manual()}
    result = calc.compute_sheet(doc_with_window(), {}, NO_LEVELS, window_heights=spans)
    computed = result.constructions[0].computed
    # H = 2800; пустота 2400 - 900 = 1500: добавка 1000 x 200 x (2800 - 1500)
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 1300) / 1e9)
    assert computed.sources.gap_opening_height == "manual"
    assert result.summary.unaccounted_gap_openings == 0
    assert calc.WINDOW_HEIGHT_UNKNOWN not in [c for c, _m in result.partition_warnings]


def test_window_without_manual_input_is_not_subtracted_and_warns() -> None:
    result = calc.compute_sheet(doc_with_window(), {}, NO_LEVELS)
    assert result.constructions[0].computed.volume_m3 == pytest.approx(1_000_000 * 2800 / 1e9)
    assert calc.WINDOW_HEIGHT_UNKNOWN in [c for c, _m in result.partition_warnings]


# ------------------------------------------------------------------ секция


def sheet(
    page: int,
    title: CadSheetFloorTitle | None,
    view: int = 1,
    *,
    summary: bool = False,
    unreadable: bool = False,
) -> cad_window_levels.SectionSheet:
    return cad_window_levels.SectionSheet(
        uuid.UUID(int=1),
        page,
        view,
        f"Лист {page + 1}",
        title,
        summary=summary,
        unreadable=unreadable,
    )


def titled(corps: str | None, section: str | None) -> CadSheetFloorTitle:
    return CadSheetFloorTitle(corps=corps, section=section)


def test_plan_section_takes_sheets_of_the_same_corps_and_section() -> None:
    source = sheet(0, titled("1", "3"))
    plan = cad_window_levels.plan_section(
        source,
        [
            source,
            sheet(1, titled("1", " 3 ")),
            sheet(2, titled("1", "4")),
            sheet(3, titled("2", "3")),
            sheet(4, None),
            sheet(5, titled(None, "3")),
        ],
    )
    assert plan.group_label == "Корп. 1 · сек. 3"
    assert [t.page_index for t in plan.targets] == [0, 1]
    assert [(s.page_index, reason) for s, reason in plan.skipped] == [
        (2, "other_group"),
        (3, "other_group"),
        (4, "no_walls"),
        (5, "other_group"),
    ]


def test_plan_section_skips_summary_and_unreadable_sheets_with_their_own_reasons() -> None:
    source = sheet(0, titled("1", "3"))
    plan = cad_window_levels.plan_section(
        source,
        [
            sheet(1, titled("1", "3"), summary=True),
            sheet(2, None, unreadable=True),
            sheet(3, None),
            sheet(4, titled("1", "3")),
        ],
    )
    assert [t.page_index for t in plan.targets] == [0, 4]
    assert [(s.page_index, reason) for s, reason in plan.skipped] == [
        (1, "summary_sheet"),
        (2, "walls_unreadable"),
        (3, "no_walls"),
    ]


def test_plan_section_for_a_summary_source_is_the_sheet_itself() -> None:
    source = sheet(0, titled("1", "3"), summary=True)
    plan = cad_window_levels.plan_section(source, [source, sheet(1, titled("1", "3"))])
    assert plan.group_label is None and plan.targets == [source] and plan.skipped == []


def _ref(walls_key: str | None, stamp_title: str | None = None) -> cad_building3d.SheetRef:
    return cad_building3d.SheetRef(
        job_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_index=3,
        view=1,
        label="Лист 4",
        order=(0.0, 0.0, 3, 1),
        overrides=levels(),
        walls_key=walls_key,
        stamp_title=stamp_title,
    )


@pytest.mark.parametrize(
    "failure",
    [
        StorageUnavailableError("down"),
        ObjectNotFoundError("gone"),
        OSError("io"),
        ValueError("bad json"),
    ],
)
async def test_title_read_errors_are_walls_unreadable_not_no_walls(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    async def broken(storage: Any, key: str) -> Any:
        raise failure

    monkeypatch.setattr(cad_views, "read_json", broken)
    item = await cad_window_levels._title_of(FakeObjectStorage(), _ref("k"), asyncio.Semaphore(1))
    assert item.unreadable is True and item.title is None


@pytest.mark.parametrize("raw", [[], {"heights": 5}, {"heights": {"title": {"floors": {}}}}])
async def test_title_with_unexpected_shape_is_walls_unreadable(
    monkeypatch: pytest.MonkeyPatch, raw: Any
) -> None:
    async def fake(storage: Any, key: str) -> Any:
        return raw

    monkeypatch.setattr(cad_views, "read_json", fake)
    item = await cad_window_levels._title_of(FakeObjectStorage(), _ref("k"), asyncio.Semaphore(1))
    assert item.unreadable is True


async def test_title_without_a_file_is_no_walls_and_summary_comes_from_the_stamp() -> None:
    item = await cad_window_levels._title_of(
        FakeObjectStorage(),
        _ref(None, "План. Секции 8, 9, 10, 15-16"),
        asyncio.Semaphore(1),
    )
    assert item.unreadable is False and item.title is None and item.summary is True


@pytest.mark.parametrize("title", [None, titled(None, None), titled("1", None), titled(None, "3")])
def test_plan_section_without_corps_or_section_is_the_sheet_itself(
    title: CadSheetFloorTitle | None,
) -> None:
    source = sheet(0, title)
    plan = cad_window_levels.plan_section(source, [source, sheet(1, titled("1", "3"))])
    assert plan.group_label is None and plan.targets == [source] and plan.skipped == []


async def test_apply_to_section_writes_only_window_levels_of_the_group(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
    revision = uuid.UUID(revision_id)
    titles: dict[str, CadSheetFloorTitle | None] = {
        "same": titled("1", "3"),
        "other": titled("1", "4"),
        "nowalls": None,
    }
    pages = {"same": 7, "other": 8, "nowalls": 9}

    def ref(name: str) -> cad_building3d.SheetRef:
        return cad_building3d.SheetRef(
            job_id=uuid.UUID(job_id),
            revision_id=revision,
            document_id=uuid.uuid4(),
            page_index=pages[name],
            view=1,
            label=name,
            order=(0.0, 0.0, pages[name], 1),
            overrides=levels(),
            walls_key=None,
        )

    async def fake_collect(
        session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[list[cad_building3d.SheetRef], list[Any], None]:
        return [ref("same"), ref("other"), ref("nowalls")], [], None

    async def fake_title(
        storage: Any, item: cad_building3d.SheetRef, gate: asyncio.Semaphore
    ) -> cad_window_levels.SectionSheet:
        return cad_window_levels.SectionSheet(
            item.revision_id, item.page_index, item.view, item.label, titles[item.label]
        )

    monkeypatch.setattr(cad_building3d, "collect_sheets", fake_collect)
    monkeypatch.setattr(cad_window_levels, "_title_of", fake_title)
    source = cad_window_levels.SectionSheet(revision, 0, 1, "Лист 1", titled("1", "3"))
    workspace_id = make_context().tenant

    preview = await cad_window_levels.apply_to_section(
        db_session,
        fake_storage,
        workspace_id=workspace_id,
        project_id=uuid.UUID(project_id),
        source=source,
        sill_mm=900,
        head_mm=2400,
        user_id=None,
        dry_run=True,
    )
    assert preview.dry_run is True and preview.updated == 2
    assert (await db_session.scalars(select(CadSheetLevels))).all() == []

    result = await cad_window_levels.apply_to_section(
        db_session,
        fake_storage,
        workspace_id=workspace_id,
        project_id=uuid.UUID(project_id),
        source=source,
        sill_mm=900,
        head_mm=2400,
        user_id=None,
        dry_run=False,
    )
    assert result.updated == 2 and result.group_label == "Корп. 1 · сек. 3"
    assert [(s.label, s.reason) for s in result.skipped] == [
        ("other", "other_group"),
        ("nowalls", "no_walls"),
    ]
    rows = {row.page_index: row for row in await db_session.scalars(select(CadSheetLevels))}
    assert set(rows) == {0, 7}
    assert all((r.window_sill_mm, r.window_head_mm) == (900, 2400) for r in rows.values())
    assert all(r.floor_height_mm is None and r.door_height_mm is None for r in rows.values())


# ------------------------------------------------------------------ API


async def test_levels_put_stores_the_window_pair_and_rejects_bad_ones(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "levels")
        saved = await api.put(url, json={"window_sill_mm": 900, "window_head_mm": 2400})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert (body["sheet_levels"]["window_sill_mm"], body["sheet_levels"]["window_head_mm"]) == (
            900,
            2400,
        )
        assert body["heights"]["window_sill"] == {
            "value_mm": 900,
            "source": "manual",
            "default_mm": None,
        }
        listed = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert listed["heights"]["window_head"]["value_mm"] == 2400

        for bad in (
            {"window_sill_mm": 900},
            {"window_head_mm": 2400},
            {"window_sill_mm": 2400, "window_head_mm": 2400},
            {"window_sill_mm": 0, "window_head_mm": 6001},
            {"window_sill_mm": -5, "window_head_mm": 1000},
        ):
            rejected = await api.put(url, json=bad)
            assert rejected.status_code == 422, bad

        # запись заменяет высоты целиком: пустая пара снимает ручной ввод
        reset = await api.put(url, json={})
        assert reset.json()["heights"]["window_sill"]["value_mm"] is None
        assert reset.json()["heights"]["window_sill"]["source"] is None


async def test_apply_to_section_needs_values_and_without_a_group_stays_on_the_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        apply = _url(project_id, job_id, "window-levels/apply-to-section")
        empty = await api.post(apply)
        assert empty.status_code == 422, empty.text
        assert empty.json()["detail"]["code"] == "VALIDATION_FAILED"

        await api.put(
            _url(project_id, job_id, "levels"),
            json={"window_sill_mm": 900, "window_head_mm": 2400},
        )
        # в walls.json заглушки заголовка плана нет: секции у листа нет, значения только ему
        done = await api.post(apply)
        assert done.status_code == 200, done.text
        assert done.json() == {
            "sill_mm": 900,
            "head_mm": 2400,
            "dry_run": False,
            "group_label": None,
            "updated": 1,
            "skipped": [],
        }
        dry = await api.post(apply, params={"dry_run": "true"})
        assert dry.json()["dry_run"] is True and dry.json()["updated"] == 1
