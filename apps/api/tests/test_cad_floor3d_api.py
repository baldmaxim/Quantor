"""3D-вид этажа (ADR-0039): уровень проекта, модель этажа, решения по отверстиям, границы доступа.

Скрипт `tools/cad_walls` подменён заглушкой из тестов конструкций, дополненной полями cad_walls
v1.1 (плита, отверстия, перемычки). Режим `old` в файле `mode` отдаёт walls.json прежнего формата.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import Role
from app.main import create_app
from app.models import CadProjectLevels, CadSheetLevels, CadSlabHoleDecision, Workspace
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import (
    PARAMS,
    STUB,
    _ready_sheet,
    _url,
    walls_settings,
)
from tests.test_cad_mep import _parent
from tests.test_cad_qa import A3_HEIGHT, A3_WIDTH

BASE = 47600
SECTION = "АР1.1 л. 45, разрез 4-4"
# Модель этажа, которую пишет заглушка для режима «новый walls.json».
EXTRAS = """
if mode != "old":
    doc["slab"] = {"shell": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]],
                   "area_mm2": 24000000.0, "close_radius_mm": 600.0}
    doc["slab_holes"] = [
        {"id": "h1", "shell": [[1000.0, 1000.0], [2000.0, 1000.0], [2000.0, 2000.0],
                               [1000.0, 2000.0]],
         "area_mm2": 1000000.0, "status": "candidate", "reason": "enclosed_no_door"},
        {"id": "h2", "shell": [[3000.0, 1000.0], [4000.0, 1000.0], [4000.0, 3000.0],
                               [3000.0, 3000.0]],
         "area_mm2": 2000000.0, "status": "candidate", "reason": "enclosed_no_door"}]
    doc["openings"][0]["direction"] = [1.0, 0.0]
    doc["openings"][0]["lintel"] = [[500.0, 0.0], [1500.0, 0.0], [1500.0, 200.0], [500.0, 200.0]]
    doc["openings"][1]["direction"] = [1.0, 0.0]
    doc["openings"][1]["lintel"] = [[2000.0, 0.0], [3000.0, 0.0], [3000.0, 200.0], [2000.0, 200.0]]
"""
FLOOR_STUB = STUB.replace(
    "out = pathlib.Path(args.out)\n", EXTRAS + "out = pathlib.Path(args.out)\n"
)
assert FLOOR_STUB != STUB


@pytest.fixture
def floor_tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "cad_walls" / "version.py").write_text('GENERATOR_VERSION = "cad_walls.v1"\n')
    (root / "run_walls.py").write_text(FLOOR_STUB, encoding="utf-8")
    return root


def _floor(project_id: str, job_id: str, tail: str = "floor3d") -> str:
    return _url(project_id, job_id, tail)


def _codes(body: dict[str, Any]) -> list[str]:
    return [w["code"] for w in body["warnings"]]


# ------------------------------------------------------------------ без базы


def test_routes_are_in_openapi() -> None:
    base = "/api/v1/projects/{project_id}/cad"
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths[f"{base}/levels"]) == {"get", "put"}
    sheet = f"{base}/{{job_id}}/views/{{page_index}}/{{view}}"
    assert set(paths[f"{sheet}/floor3d"]) == {"get"}
    assert set(paths[f"{sheet}/floor3d/holes/{{hole_key}}"]) == {"put"}


# ------------------------------------------------------------------ доступ


async def test_routes_are_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    project_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("get", f"/api/v1/projects/{project_id}/cad/levels", None),
        ("put", f"/api/v1/projects/{project_id}/cad/levels", {}),
        ("get", _floor(project_id, job_id), None),
        ("put", _floor(project_id, job_id, "floor3d/holes/abc"), {"enabled": True}),
    ]
    async with build_api(
        make_context(), settings=walls_settings(floor_tools, tmp_path, flag=False)
    ) as api:
        for method, url, body in calls:
            response = await api.request(method, url, json=body)
            assert response.status_code == 403, url
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", url


async def test_foreign_workspace_sees_and_changes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        levels = f"/api/v1/projects/{project_id}/cad/levels"
        for method, url, body in (
            ("get", levels, None),
            ("put", levels, {"slab_thickness_mm": 220, "slab_source_ref": SECTION}),
            ("get", _floor(project_id, job_id), None),
            ("put", _floor(project_id, job_id, "floor3d/holes/abc"), {"enabled": True}),
        ):
            response = await foreign.request(method, url, json=body)
            assert response.status_code == 404, url
    assert (await db_session.scalars(select(CadProjectLevels))).first() is None


async def test_viewer_reads_but_cannot_write(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=settings) as reader:
        levels = f"/api/v1/projects/{project_id}/cad/levels"
        assert (await reader.get(levels)).status_code == 200
        assert (await reader.get(_floor(project_id, job_id))).status_code == 200
        assert (await reader.put(levels, json={})).status_code == 403
        hole = _floor(project_id, job_id, "floor3d/holes/abc")
        assert (await reader.put(hole, json={"enabled": True})).status_code == 403


async def test_floor3d_is_not_ready_until_walls_job_succeeds(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _base = await _parent(api, db_session, fake_storage)
        response = await api.get(_floor(project_id, job_id))
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "CAD_WALLS_NOT_READY"


# ------------------------------------------------------------------ уровень проекта


async def test_project_levels_roundtrip_and_validation(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        url = f"/api/v1/projects/{project_id}/cad/levels"
        empty = await api.get(url)
        assert empty.status_code == 200
        assert empty.json() == {
            "slab_thickness_mm": None,
            "slab_source_ref": None,
            "updated_at": None,
        }

        for bad in (
            {"slab_thickness_mm": 220},
            {"slab_thickness_mm": 99, "slab_source_ref": SECTION},
            {"slab_thickness_mm": 1001, "slab_source_ref": SECTION},
            {"slab_thickness_mm": 220, "slab_source_ref": SECTION, "x": 1},
        ):
            assert (await api.put(url, json=bad)).status_code == 422, bad
        assert (
            await api.put(f"/api/v1/projects/{uuid.uuid4()}/cad/levels", json={})
        ).status_code == 404

        saved = await api.put(url, json={"slab_thickness_mm": 220, "slab_source_ref": SECTION})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert (body["slab_thickness_mm"], body["slab_source_ref"]) == (220, SECTION)
        assert body["updated_at"] is not None
        assert (await api.get(url)).json() == body
        stored = (await db_session.scalars(select(CadProjectLevels))).one()
        assert str(stored.project_id) == project_id and stored.slab_thickness_mm == 220

        replaced = await api.put(url, json={"slab_thickness_mm": 250, "slab_source_ref": "АР2"})
        assert replaced.json()["slab_thickness_mm"] == 250
        cleared = await api.put(url, json={})
        assert cleared.json()["slab_thickness_mm"] is None
        assert cleared.json()["slab_source_ref"] is None


async def test_project_slab_reaches_constructions_totals_and_floor3d(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        before = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert before["heights"]["wall_height_mm"] == 2800
        assert before["heights"]["slab_thickness"]["source"] == "assumption"
        assert before["heights"]["slab_thickness_sheet_ref"] is None

        levels = f"/api/v1/projects/{project_id}/cad/levels"
        await api.put(levels, json={"slab_thickness_mm": 250, "slab_source_ref": SECTION})
        after = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert after["heights"]["wall_height_mm"] == 2750
        assert after["heights"]["slab_thickness"] == {
            "value_mm": 250,
            "source": "manual",
            "default_mm": 200,
        }
        assert after["heights"]["slab_thickness_sheet_ref"] == SECTION
        assert after["sheet_levels"]["slab_thickness_mm"] is None
        floor = (await api.get(_floor(project_id, job_id))).json()
        assert floor["slab"]["z_bottom_mm"] == BASE - 250
        assert floor["walls"][0]["z_top_mm"] == BASE + 2750

        # Переопределение листа сильнее проекта.
        sheet = await api.put(_url(project_id, job_id, "levels"), json={"slab_thickness_mm": 300})
        assert sheet.status_code == 200, sheet.text
        assert sheet.json()["heights"]["slab_thickness"]["value_mm"] == 300
        assert sheet.json()["heights"]["slab_thickness_sheet_ref"] is None
        floor = (await api.get(_floor(project_id, job_id))).json()
        assert floor["slab"]["z_bottom_mm"] == BASE - 300


# ------------------------------------------------------------------ модель этажа


async def test_floor3d_model_of_a_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        response = await api.get(_floor(project_id, job_id))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["units"] == "mm" and body["generator"] == "cad_walls.v1"
        assert body["base_z_mm"] == BASE and body["elevation_known"] is True
        assert body["heights"]["floor_elevation_source"] == "observed"
        assert body["slab"]["z_top_mm"] == BASE and body["slab"]["z_bottom_mm"] == BASE - 200
        assert body["slab"]["area_m2"] == 24.0
        assert [h["state"] for h in body["slab_holes"]] == ["candidate", "candidate"]
        assert [h["area_m2"] for h in body["slab_holes"]] == [1.0, 2.0]
        keys = [w["construction_key"] for w in body["walls"]]
        assert keys == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd"]
        assert body["walls"][0]["family"] == "masonry"
        assert body["walls"][3]["family"] == "monolith"
        assert body["walls"][2]["thickness_nominal_mm"] is None
        assert all(w["z_bottom_mm"] == BASE and w["z_top_mm"] == BASE + 2800 for w in body["walls"])
        lintels = {item["opening_id"]: item for item in body["lintels"]}
        assert set(lintels) == {"door00000001", "gap000000001"}
        door = lintels["door00000001"]
        assert (door["z_bottom_mm"], door["z_top_mm"]) == (BASE + 2100, BASE + 2800)
        assert (door["door_height_mm"], door["door_height_source"]) == (2100, "assumption")
        assert body["bbox"] == [0.0, 0.0, 6000.0, 4000.0]
        assert body["warnings"] == []


async def test_old_walls_json_gives_walls_outdated(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    (floor_tools / "run_walls.py").write_text(FLOOR_STUB, encoding="utf-8")
    (floor_tools / "mode").write_text("old")
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        body = (await api.get(_floor(project_id, job_id))).json()
        assert _codes(body) == ["walls_outdated"]
        assert body["slab"] is None and body["slab_holes"] == [] and body["lintels"] == []
        assert len(body["walls"]) == 4
        missing = await api.put(
            _floor(project_id, job_id, "floor3d/holes/abc"), json={"enabled": True}
        )
        assert missing.status_code == 404


async def test_sheet_floor_elevation_override_moves_the_model(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "levels")
        for bad in (-100001, 500001):
            assert (await api.put(url, json={"floor_elevation_mm": bad})).status_code == 422
        changed = await api.put(url, json={"floor_elevation_mm": 52000})
        assert changed.status_code == 200, changed.text
        body = changed.json()
        assert body["sheet_levels"]["floor_elevation_mm"] == 52000
        assert body["heights"]["floor_elevation_mm"] == 52000
        assert body["heights"]["floor_elevation_source"] == "manual"
        stored = (await db_session.scalars(select(CadSheetLevels))).one()
        assert str(stored.revision_id) == revision_id and stored.floor_elevation_mm == 52000

        floor = (await api.get(_floor(project_id, job_id))).json()
        assert floor["base_z_mm"] == 52000 and floor["slab"]["z_top_mm"] == 52000
        assert floor["walls"][0]["z_bottom_mm"] == 52000 and floor["walls"][0]["z_top_mm"] == 54800

        reset = await api.put(url, json={})
        assert reset.json()["heights"]["floor_elevation_source"] == "observed"
        assert (await api.get(_floor(project_id, job_id))).json()["base_z_mm"] == BASE


# ------------------------------------------------------------------ решения по отверстиям


async def test_hole_decision_changes_state_and_persists(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        first, second = (
            h["key"] for h in (await api.get(_floor(project_id, job_id))).json()["slab_holes"]
        )
        assert first != second and len(first) == 12

        missing = await api.put(
            _floor(project_id, job_id, "floor3d/holes/nosuchhole00"), json={"enabled": True}
        )
        assert missing.status_code == 404
        for bad in ({}, {"enabled": "maybe"}, {"enabled": True, "x": 1}):
            response = await api.put(_floor(project_id, job_id, f"floor3d/holes/{first}"), json=bad)
            assert response.status_code == 422, bad

        url = _floor(project_id, job_id, f"floor3d/holes/{first}")
        enabled = await api.put(url, json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        states = {h["key"]: h["state"] for h in enabled.json()["slab_holes"]}
        assert states == {first: "enabled", second: "candidate"}

        disabled = await api.put(url, json={"enabled": False})
        states = {h["key"]: h["state"] for h in disabled.json()["slab_holes"]}
        assert states == {first: "disabled", second: "candidate"}
        listed = (await api.get(_floor(project_id, job_id))).json()
        assert {h["key"]: h["state"] for h in listed["slab_holes"]} == states

        rows = (await db_session.scalars(select(CadSlabHoleDecision))).all()
        assert len(rows) == 1
        assert (str(rows[0].revision_id), rows[0].hole_key, rows[0].enabled) == (
            revision_id,
            first,
            False,
        )


# ------------------------------------------------------------------ зоны двери


async def _door_zone(
    api: AsyncClient, project_id: str, revision_id: str, *, height: int, mm: tuple[float, float]
) -> None:
    """Зона двери по двум точкам в мм DXF; кадр вида: начало (10, 20) pt, 35.2778 мм/pt."""
    factor, origin = 35.2778, (10.0, 20.0)
    width, height_pt = float(A3_WIDTH), float(A3_HEIGHT)
    points = [
        [(origin[0] + x / factor) / width, (origin[1] - 100.0 / factor) / height_pt] for x in mm
    ]
    created = await api.post(
        f"/api/v1/projects/{project_id}/cad/zones",
        json={
            "revision_id": revision_id,
            "page_index": 0,
            "kind": "door",
            "points": points,
            "door_height_mm": height,
        },
    )
    assert created.status_code == 201, created.text


async def test_door_zone_sets_lintel_height_through_the_view_frame(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        await _door_zone(api, project_id, revision_id, height=2300, mm=(500.0, 1500.0))
        body = (await api.get(_floor(project_id, job_id))).json()
        lintels = {item["opening_id"]: item for item in body["lintels"]}
        door = lintels["door00000001"]
        assert (door["door_height_mm"], door["door_height_source"]) == (2300, "manual")
        assert (door["z_bottom_mm"], door["z_top_mm"]) == (BASE + 2300, BASE + 2800)
        # Окно-разрыв (середина перемычки в 2500 мм) зоной не затронуто.
        assert lintels["gap000000001"]["door_height_source"] == "assumption"
        assert lintels["gap000000001"]["door_height_mm"] == 2100
        assert "door_zones_unmapped" not in _codes(body)
