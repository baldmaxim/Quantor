"""Трассы механики в 3D (ADR-0041): высоты по умолчанию из уровней листа и `GET .../mep/routes3d`.

Генератор трасс и скрипт конструкций подменены заглушками из тестов `test_cad_mep` и
`test_cad_constructions_api`: заглушка трасс пишет `routes3d.json` с отметкой и высотой, с
которыми её запустили; заглушка конструкций отдаёт отметку этажа 47600 и высоту 3000.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_mep import CadMepRoutes3dFile
from app.core.config import Settings
from app.domain import JobStatus
from app.models import Job, Workspace
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS as WALLS_PARAMS
from tests.test_cad_constructions_api import STUB as WALLS_STUB
from tests.test_cad_constructions_api import _ready_sheet, _url
from tests.test_cad_mep import PARAMS as MEP_PARAMS
from tests.test_cad_mep import STUB as MEP_STUB
from tests.test_cad_mep import (
    _approve_and_queue,
    _parent,
    _run_route_worker,
    mep_settings,
)


@pytest.fixture
def mep_tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_mep"
    (root / "params").mkdir(parents=True)
    (root / "cad_mep").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(MEP_PARAMS), encoding="utf-8")
    (root / "run_mep.py").write_text(MEP_STUB, encoding="utf-8")
    return root


@pytest.fixture
def walls_tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(WALLS_PARAMS), encoding="utf-8")
    (root / "run_walls.py").write_text(WALLS_STUB, encoding="utf-8")
    return root


def both_settings(
    mep_tools: Path, walls_tools: Path, tmp_path: Path, *, flag: bool = True
) -> Settings:
    mep = mep_settings(mep_tools, tmp_path, flag=flag)
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_mep_runner=mep.cad_mep_runner,
        cad_mep_params=mep.cad_mep_params,
        cad_walls_runner=str(walls_tools / "run_walls.py"),
        cad_walls_params=str(walls_tools / "params" / "v1.json"),
        cad_engine_pins=write_pins(
            tmp_path,
            mep=mep_tools / "params" / "v1.json",
            walls=walls_tools / "params" / "v1.json",
        ),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


def _routes3d_url(project_id: str, revision_id: str, page: int = 0, view: int = 1) -> str:
    return (
        f"/api/v1/projects/{project_id}/cad/mep/routes3d"
        f"?revision_id={revision_id}&page_index={page}&view={view}"
    )


async def _payload(session: AsyncSession, job_id: str) -> dict[str, object]:
    job = await session.get(Job, uuid.UUID(job_id))
    assert job is not None
    return dict(job.payload)


# ------------------------------------------------------------------ единые высоты


async def test_levels_of_the_sheet_become_the_default_heights_of_the_routes(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = both_settings(mep_tools, walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        route_id = await _approve_and_queue(api, base, job_id, None, None)
        payload = await _payload(db_session, route_id)
        # Уровни листа из walls.json (отметка 47600, высота 3000) - те же, что видит 3D.
        assert (payload["floor_elevation_mm"], payload["floor_height_mm"]) == (47600, 3000)


async def test_manual_sheet_levels_win_over_walls_and_explicit_body_wins_over_levels(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = both_settings(mep_tools, walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        levels = await api.put(
            _url(project_id, job_id, "levels"),
            json={"floor_height_mm": 3200, "floor_elevation_mm": 50900},
        )
        assert levels.status_code == 200, levels.text
        # Явная высота в запросе главнее; отметка - из уровней листа.
        route_id = await _approve_and_queue(api, base, job_id, None, 3500)
        payload = await _payload(db_session, route_id)
        assert (payload["floor_elevation_mm"], payload["floor_height_mm"]) == (50900, 3500)


async def test_unknown_levels_leave_the_heights_to_the_generator(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id, None, None)
        payload = await _payload(db_session, route_id)
        assert payload["floor_elevation_mm"] is None and payload["floor_height_mm"] is None


async def test_the_idempotency_key_ignores_the_levels(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = both_settings(mep_tools, walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        first = await _approve_and_queue(api, base, job_id, None, None)
        again = await api.post(
            f"{base}/{job_id}/views/0/1/mep-routes", json={"attempt": 1, "floor_height_mm": 3500}
        )
        assert again.status_code == 202 and again.json()["job_id"] == first


# ------------------------------------------------------------------ GET routes3d


async def test_routes3d_is_404_until_routes_succeed_and_when_the_file_is_missing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        url = _routes3d_url(project_id, revision_id)
        none = await api.get(url)
        assert none.status_code == 404
        assert none.json()["detail"]["code"] == "CAD_ROUTES_NOT_FOUND"

        route_id = await _approve_and_queue(api, base, job_id)
        queued = await api.get(url)  # задание поставлено, но не успешно
        assert queued.json()["detail"]["code"] == "CAD_ROUTES_NOT_FOUND"

        (mep_tools / "no_routes3d").write_text("1", encoding="utf-8")  # прежний генератор
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED
        old = await api.get(url)
        assert old.status_code == 404
        assert old.json()["detail"]["code"] == "CAD_ROUTES3D_MISSING"


async def test_routes3d_reads_the_file_and_compares_heights_with_the_sheet_levels(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = both_settings(mep_tools, walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        route_id = await _approve_and_queue(api, base, job_id, None, None)
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)

        read = await api.get(_routes3d_url(project_id, revision_id))
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["job_id"] == route_id and body["generator_version"] == "cad_mep.v1"
        assert (body["floor_elevation_mm"], body["floor_height_mm"]) == (47600, 3000)
        assert (body["levels_elevation_mm"], body["levels_height_mm"]) == (47600, 3000)
        assert body["heights_match"] is True
        # Файл v1: поля сечения и изоляции - по умолчанию, элементов нет.
        v1_defaults = {
            "kind": None,
            "shape": None,
            "dn_mm": None,
            "w_mm": None,
            "h_mm": None,
            "insulation_mm": 0,
            "slope": None,
            "apt": None,
        }
        assert body["polylines"] == [
            {"layer": "M-OV-T1", "pts": [[0, 0, 50], [1000, 0, 50]], **v1_defaults},
            {"layer": "M-VK-V1", "pts": [[500, 500, 0], [500, 500, 2900]], **v1_defaults},
        ]
        assert body["elements"] == []

        # Человек поменял высоту этажа в 3D: трассы построены по прежней - стоит перестроить.
        put = await api.put(_url(project_id, job_id, "levels"), json={"floor_height_mm": 3200})
        assert put.status_code == 200
        changed = (await api.get(_routes3d_url(project_id, revision_id))).json()
        assert changed["levels_height_mm"] == 3200 and changed["floor_height_mm"] == 3000
        assert changed["heights_match"] is False

        # Другой вид или страница - трасс нет.
        other = await api.get(_routes3d_url(project_id, revision_id, view=2))
        assert other.json()["detail"]["code"] == "CAD_ROUTES_NOT_FOUND"


async def test_routes3d_reads_the_v2_file_with_sections_insulation_and_elements(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        (mep_tools / "routes3d_v2").write_text("1", encoding="utf-8")
        route_id = await _approve_and_queue(api, base, job_id)
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        read = await api.get(_routes3d_url(project_id, revision_id))
        assert read.status_code == 200, read.text
        body = read.json()
        pipe, duct = body["polylines"]
        assert (pipe["shape"], pipe["dn_mm"], pipe["insulation_mm"], pipe["apt"]) == (
            "round",
            25,
            9,
            "12",
        )
        assert (duct["shape"], duct["w_mm"], duct["h_mm"], duct["dn_mm"]) == (
            "rect",
            400,
            200,
            None,
        )
        valve, sleeve = body["elements"]
        assert (valve["type"], valve["subtype"], valve["axis"]) == (
            "valve",
            "ball_valve",
            [1000, 0, 0],
        )
        assert (sleeve["type"], sleeve["length_mm"], sleeve["outer_d_mm"]) == ("sleeve", 260, 135)


def test_routes3d_contract_accepts_both_schemas_and_rejects_foreign_ones() -> None:
    base = {"frame": "view_dxf_mm", "floor_elevation_mm": None, "floor_height_mm": None}
    line = {"layer": "M-VK-V1", "pts": [[0, 0, 0], [1, 0, 0]]}
    v1 = CadMepRoutes3dFile.model_validate(
        {**base, "schema": "cad_mep_routes3d.v1", "polylines": [line]}
    )
    assert v1.elements == [] and v1.polylines[0].shape is None
    assert v1.polylines[0].insulation_mm == 0
    v2 = CadMepRoutes3dFile.model_validate(
        {**base, "schema": "cad_mep_routes3d.v2", "polylines": [line], "elements": []}
    )
    assert v2.schema_id == "cad_mep_routes3d.v2"
    with pytest.raises(ValidationError):
        CadMepRoutes3dFile.model_validate(
            {**base, "schema": "cad_mep_routes3d.v3", "polylines": []}
        )
    with pytest.raises(ValidationError):
        CadMepRoutes3dFile.model_validate(
            {
                **base,
                "schema": "cad_mep_routes3d.v2",
                "polylines": [],
                "elements": [
                    {
                        "type": "valve",
                        "subtype": "x",
                        "layer": "M",
                        "pos": [0, 0],
                        "axis": [1, 0, 0],
                    }
                ],
            }
        )


async def test_routes3d_without_walls_has_no_levels_and_no_match(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        body = (await api.get(_routes3d_url(project_id, revision_id))).json()
        assert body["levels_elevation_mm"] is None and body["levels_height_mm"] is None
        assert body["heights_match"] is False


async def test_routes3d_takes_the_newest_succeeded_route_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id, 47600, 3300)
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        body = (await api.get(_routes3d_url(project_id, revision_id))).json()
        assert body["job_id"] == route_id and body["floor_height_mm"] == 3300


async def test_routes3d_is_closed_for_strangers_and_without_the_flag(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    mep_tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(mep_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert (await api.get(_routes3d_url(project_id, revision_id))).status_code == 200
        # Ревизия не из этого проекта - 404.
        foreign_revision = await api.get(_routes3d_url(project_id, str(uuid.uuid4())))
        assert foreign_revision.status_code == 404

    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(_routes3d_url(project_id, revision_id))).status_code == 404

    async with build_api(
        make_context(), settings=mep_settings(mep_tools, tmp_path, flag=False)
    ) as off:
        closed = await off.get(_routes3d_url(project_id, revision_id))
        assert closed.status_code == 403
        assert closed.json()["detail"]["code"] == "FEATURE_DISABLED"
