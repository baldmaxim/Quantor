"""Общий вид здания для 3D: маршрут, границы доступа, этажи проекта, пропуск сбойных листов."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import Role
from app.main import create_app
from app.models import Workspace
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS, _ready_sheet, walls_settings
from tests.test_cad_floor3d_api import BASE, FLOOR_STUB, SECTION
from tests.test_cad_mep import _parent


@pytest.fixture
def floor_tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_walls.py").write_text(FLOOR_STUB, encoding="utf-8")
    return root


def _url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/building3d"


def _codes(body: dict[str, object]) -> list[str]:
    warnings = body["warnings"]
    assert isinstance(warnings, list)
    return [w["code"] for w in warnings]


def test_route_is_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/cad/building3d"]) == {"get"}


async def test_route_is_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(
        make_context(), settings=walls_settings(floor_tools, tmp_path, flag=False)
    ) as api:
        response = await api.get(_url(str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_unknown_project_is_404_and_foreign_workspace_sees_nothing(
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
        assert (await api.get(_url(str(uuid.uuid4())))).status_code == 404
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(_url(project_id))).status_code == 404


async def test_floor_of_a_ready_sheet_follows_project_levels_for_viewer(
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
        await api.put(
            f"/api/v1/projects/{project_id}/cad/levels",
            json={"slab_thickness_mm": 250, "slab_source_ref": SECTION},
        )
    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=settings) as reader:
        response = await reader.get(_url(project_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["units"] == "mm" and body["warnings"] == []
    (floor,) = body["floors"]
    assert (floor["job_id"], floor["revision_id"]) == (job_id, revision_id)
    assert (floor["page_index"], floor["view"]) == (0, 1)
    assert floor["document_id"] is not None and "лист 1" in floor["label"]
    assert (floor["elevation_known"], floor["base_z_mm"]) == (True, BASE)
    assert (floor["floor_height_mm"], floor["slab_thickness_mm"]) == (3000, 250)
    assert floor["outline_source"] == "slab"
    assert floor["outline"] == [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
    assert floor["bbox"] == [0.0, 0.0, 6000.0, 4000.0]
    # Заглушка не пишет заголовок плана и оси: здание без корпуса, этаж не совмещён.
    assert (floor["corps"], floor["section"]) == (None, None)
    assert (floor["group_key"], floor["group_label"]) == ("none", "Корпус не указан")
    assert (floor["alignment"], floor["offset_mm"], floor["alignment_axes"]) == (
        "none",
        [0.0, 0.0],
        [],
    )
    assert floor["alignment_message"] == (
        "в группе нет этажа с осями в обоих направлениях; "
        "лист: оси не распознаны: пересчитайте конструкции листа"
    )
    assert body["groups"] == [
        {"key": "none", "label": "Корпус не указан", "floor_count": 1, "aligned_count": 0}
    ]


async def test_sheet_without_walls_is_skipped_with_warning(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _base = await _parent(api, db_session, fake_storage)
        body = (await api.get(_url(project_id))).json()
    assert body["floors"] == []
    assert _codes(body) == ["walls_not_ready"]


async def test_unreadable_walls_file_does_not_fail_the_response(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            fake_storage.objects[key] = b"{not json"
        broken = (await api.get(_url(project_id))).json()
        assert broken["floors"] == [] and _codes(broken) == ["walls_unreadable"]
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            fake_storage.objects[key] = b'{"schema": "x"}'
        invalid = (await api.get(_url(project_id))).json()
        assert invalid["floors"] == [] and _codes(invalid) == ["walls_invalid"]


async def test_axes_in_walls_file_make_the_single_floor_a_reference(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            raw = json.loads(fake_storage.objects[key])
            raw["heights"]["title"] = {"corps": "9", "section": "3", "floors": [1], "text": None}
            raw["axes"] = {
                "status": "found",
                "message": None,
                "diameter_pt": 12.0,
                "items": [
                    {"label": "3.1", "orient": "vertical", "pos_pt": 110.0, "bubbles_pt": []},
                    {"label": "А", "orient": "horizontal", "pos_pt": 10.0, "bubbles_pt": []},
                ],
                "conflicts": [],
                "rejected": 0,
            }
            fake_storage.objects[key] = json.dumps(raw).encode()
        body = (await api.get(_url(project_id))).json()
    (floor,) = body["floors"]
    assert (floor["group_key"], floor["group_label"]) == ("k9-s3", "Корп. 9 · сек. 3")
    assert floor["alignment"] == "reference" and floor["alignment_message"] is None
    assert body["groups"] == [
        {"key": "k9-s3", "label": "Корп. 9 · сек. 3", "floor_count": 1, "aligned_count": 1}
    ]
