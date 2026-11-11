"""Плита перекрытия в API конструкций: список, итоги, свойства, ВОР (заглушка — из 3D-тестов)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_constructions_api import (
    STUB,
    _construction,
    _ready_sheet,
    _url,
    walls_settings,
)
from tests.test_cad_floor3d_api import FLOOR_STUB, floor_tools

__all__ = ["floor_tools"]

SLAB_FIELDS = '"area_mm2": 24000000.0, "close_radius_mm": 600.0}'
assert SLAB_FIELDS in FLOOR_STUB


@pytest.fixture
def floor_tools_with_slab_id(floor_tools: Path) -> Path:
    """Тот же walls.json, но плита несёт `id` и `kind` (новый движок)."""
    stub = floor_tools / "run_walls.py"
    stub.write_text(
        FLOOR_STUB.replace(
            SLAB_FIELDS, '"area_mm2": 24000000.0, "id": "slab", "kind": "floor_slab"}'
        ),
        encoding="utf-8",
    )
    return floor_tools


async def _setup(
    api: AsyncClient,
    db_session: AsyncSession,
    storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> tuple[str, str]:
    project_id, _rev, job_id, _walls = await _ready_sheet(
        api, db_session, storage, walls_settings(tools, tmp_path)
    )
    return project_id, job_id


async def test_slab_is_a_construction_of_the_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools_with_slab_id: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools_with_slab_id, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, job_id = await _setup(
            api, db_session, fake_storage, floor_tools_with_slab_id, tmp_path
        )
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert body["constructions"][-1]["id"] == "slab"
        slab = _construction(body, "slab")
        # Оба отверстия включены (решений нет): 24 - 1 - 2 = 21 м2, плита 200 мм -> 4,2 м3.
        assert slab["kind"] == "floor_slab" and slab["computed"]["area_m2"] == 21.0
        assert slab["computed"]["volume_m3"] == pytest.approx(4.2)
        assert len(slab["polygon"]["holes"]) == 2
        assert body["summary"]["total_count"] == 5
        group = next(t for t in body["totals"] if t["kind"] == "floor_slab")
        assert group["area_m2"] == 21.0 and group["thickness_mm"] == 200.0
        assert all(t["area_m2"] is None for t in body["totals"] if t["kind"] != "floor_slab")

        # Решение по отверстию «Не отверстие» возвращает его площадь плите.
        floor = (await api.get(_url(project_id, job_id, "floor3d"))).json()
        key = floor["slab_holes"][1]["key"]
        hole = await api.put(
            _url(project_id, job_id, f"floor3d/holes/{key}"), json={"enabled": False}
        )
        assert hole.status_code == 200, hole.text
        after = (await api.get(_url(project_id, job_id, "constructions"))).json()
        slab = _construction(after, "slab")
        assert slab["computed"]["area_m2"] == 23.0 and len(slab["polygon"]["holes"]) == 1
        assert slab["computed"]["volume_m3"] == pytest.approx(4.6)
        # Модель 3D прежняя: конструкции плиты в ней нет.
        assert all(
            w["construction_key"] != "slab"
            for w in (await api.get(_url(project_id, job_id, "floor3d"))).json()["walls"]
        )


async def test_slab_props_thickness_and_accept(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, job_id = await _setup(api, db_session, fake_storage, floor_tools, tmp_path)
        url = _url(project_id, job_id, "constructions/slab/props")
        put = await api.put(
            url, json={"props": {"thickness_override_mm": 250, "material": "monolith_concrete"}}
        )
        assert put.status_code == 200, put.text
        slab = put.json()
        assert slab["computed"]["thickness_mm"] == 250.0
        assert slab["computed"]["sources"]["thickness"] == "manual"
        assert slab["computed"]["volume_m3"] == pytest.approx(21.0 * 0.25)
        assert slab["material"]["value"] == "monolith_concrete"
        bulk = await api.put(
            _url(project_id, job_id, "constructions/props:bulk"),
            json={"keys": ["slab"], "props_patch": {}, "accepted": True},
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["changed"] == 1
        group = next(t for t in bulk.json()["totals"] if t["kind"] == "floor_slab")
        assert (group["thickness_mm"], group["material"]) == (250.0, "monolith_concrete")
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert _construction(body, "slab")["accepted"] is True
        # Неизвестный адрес по-прежнему отвергается.
        bad = await api.put(
            _url(project_id, job_id, "constructions/nope/props"), json={"props": {}}
        )
        assert bad.status_code == 404
        levels = await api.put(_url(project_id, job_id, "levels"), json={"slab_thickness_mm": 300})
        assert levels.status_code == 200, levels.text
        assert any(
            t["kind"] == "floor_slab" and t["thickness_mm"] == 250.0
            for t in levels.json()["totals"]
        )


async def test_sheet_without_slab_has_no_slab_construction(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    (floor_tools / "run_walls.py").write_text(STUB, encoding="utf-8")
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, job_id = await _setup(api, db_session, fake_storage, floor_tools, tmp_path)
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert all(c["kind"] != "floor_slab" for c in body["constructions"])
        assert all(t["kind"] != "floor_slab" for t in body["totals"])
        assert body["summary"]["total_count"] == 4
        missing = await api.put(
            _url(project_id, job_id, "constructions/slab/props"), json={"props": {}}
        )
        assert missing.status_code == 404


async def test_vor_coverage_includes_the_slab_group(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, job_id = await _setup(api, db_session, fake_storage, floor_tools, tmp_path)
        response = await api.get(_url(project_id, job_id, "vor-coverage"))
        assert response.status_code == 200, response.text
        keys = [g["group_key"] for g in response.json()["groups"]]
        assert "floor_slab|200|" in keys
