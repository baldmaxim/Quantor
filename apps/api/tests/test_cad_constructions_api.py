"""Конструкции CAD (ADR-0038): задание cad_walls, автопостановка, API величин и параметров.

Движок и настоящий скрипт не нужны: родитель `cad_pdf_convert` выставляется прямо в базе и
хранилище (как у тестов трасс), а скрипт `cad_walls` подменён заглушкой, которая пишет
`walls.json` по CLI-контракту. Режим заглушки задаёт файл `mode` рядом со скриптом: `fail` — код
выхода 2, `badsha` — walls.json другого DXF, `badschema` — чужая схема, `extra` — лишний файл,
`renamed` — те же конструкции под другими id, `gone` — конструкции `aaaaaaaaaaaa` больше нет.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker import handler as convert_handler
from app.cad_worker.handler import execute_cad_pdf_convert
from app.cad_worker.walls_handler import execute_cad_walls
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadConstructionProps, CadSheetLevels, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_walls as cad_walls_service
from app.services import cad_walls_zones
from app.services import jobs as jobs_service
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_mep import FOLDER, PARENT_DXF, _parent
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated

PARAMS = {"slab_thickness_mm": {"value": 200, "unit": "мм", "source": "assumed", "note": "тест"}}

STUB = """
import argparse, hashlib, json, pathlib, sys

parser = argparse.ArgumentParser()
for name in ("dxf", "params", "out", "pdf", "page", "zones"):
    parser.add_argument("--" + name)
args = parser.parse_args()
here = pathlib.Path(__file__).parent
mode = (here / "mode").read_text().strip() if (here / "mode").exists() else ""
for name in ("dxf", "params", "pdf"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
(here / "args.json").write_text(json.dumps({
    "page": args.page, "params_name": pathlib.Path(args.params).name,
    "pdf_head": pathlib.Path(args.pdf).read_bytes()[:5].decode("latin-1"),
    "zones": pathlib.Path(args.zones).read_text() if args.zones else None}))
if mode == "fail":
    print(json.dumps({"code": "pdf_unreadable", "message": "PDF не открывается"}), file=sys.stderr)
    sys.exit(2)
raw = json.loads(pathlib.Path(args.params).read_text(encoding="utf-8"))
params_sha = hashlib.sha256(
    json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
dxf_sha = hashlib.sha256(pathlib.Path(args.dxf).read_bytes()).hexdigest()
if mode == "badsha":
    dxf_sha = "f" * 64


def cons(key, kind, nominal, area, axis, status="matched"):
    if mode == "renamed":
        key = "r" + key[1:]
    return {
        "id": key, "kind": kind, "source_layers": ["01_КЛАДКА_И_ПЕРЕГОРОДКИ"],
        "polygon": {"shell": [[0.0, 0.0], [5000.0, 0.0], [5000.0, 200.0], [0.0, 200.0]],
                    "holes": []},
        "area_plan_mm2": area, "thickness_measured_mm": nominal or 137.0,
        "thickness_nominal_mm": nominal, "thickness_status": status,
        "length_axis_mm": axis, "axis": [[[0.0, 100.0], [5000.0, 100.0]]],
        "centroid": [2500.0, 100.0], "bbox": [0.0, 0.0, 5000.0, 200.0]}


def opening(key, kind, status, host):
    return {"id": key, "kind": kind, "status": status, "host_id": host, "adjacent_ids": [host],
            "width_mm": 1000.0, "width_source": "gap", "thickness_mm": 200.0, "block_name": None,
            "handle": None, "center": [1000.0, 100.0]}


doc = {
    "schema": "quantor.cad_walls.v0" if mode == "badschema" else "quantor.cad_walls.v1",
    "generator": "cad_walls.v1", "params_version": pathlib.Path(args.params).stem,
    "params_sha256": params_sha, "dxf_sha256": dxf_sha, "units": "mm",
    "heights": {"floor_elevation_mm": 47600, "floor_height_mm": 3000,
                "elevation_status": "observed", "height_status": "derived",
                "evidence": "стр. 1", "message": None, "slab_thickness_mm": 200,
                "slab_status": "assumption", "door_height_mm": 2100,
                "door_height_status": "assumption"},
    "constructions": [
        cons("aaaaaaaaaaaa", "masonry", 200.0, 1000000.0, 5000.0),
        cons("bbbbbbbbbbbb", "masonry", 100.0, 500000.0, 5000.0),
        cons("cccccccccccc", "masonry", None, 300000.0, 2000.0, "check"),
        cons("dddddddddddd", "monolith_column", 400.0, 160000.0, 400.0),
    ],
    "openings": [opening("door00000001", "door", "ok", "aaaaaaaaaaaa"),
                 opening("gap000000001", "gap", "no_data", "bbbbbbbbbbbb")],
    "totals": [],
    "checks": {"area_union_mm2": 1.0, "area_constructions_mm2": 1.0, "residue_ratio": 0.0,
               "warnings": [{"code": "area_residue", "message": "тест"}]},
}
if mode == "slabwarn":
    doc["checks"]["warnings"].append(
        {"code": "slab_without_zones", "message": "плита по стенам"})
if mode == "gone":
    doc["constructions"] = [c for c in doc["constructions"] if c["id"] != "aaaaaaaaaaaa"]
out = pathlib.Path(args.out)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
if mode == "extra":
    (out.parent / "other.txt").write_text("x")
"""

BASE_HEIGHT = 2800


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def walls_tools(tmp_path: Path) -> Path:
    """Параметры, версия и заглушка скрипта: то, что в образе лежит в generators/cad_walls."""
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_walls.py").write_text(STUB, encoding="utf-8")
    return root


def walls_settings(tools: Path, tmp_path: Path, *, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_walls_runner=str(tools / "run_walls.py"),
        cad_walls_params=str(tools / "params" / "v1.json"),
        cad_engine_pins=write_pins(tmp_path, walls=tools / "params" / "v1.json"),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


async def _run_walls_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="cad-walls-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_walls
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


def _url(project_id: str, job_id: str, tail: str, page: int = 0, view: int = 1) -> str:
    return f"/api/v1/projects/{project_id}/cad/{job_id}/views/{page}/{view}/{tail}"


async def _ready_sheet(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
) -> tuple[str, str, str, str]:
    """Родитель с видом, постановка и выполнение cad_walls: проект, ревизия, родитель, walls."""
    project_id, revision_id, job_id, _base = await _parent(api, session, storage)
    queued = await api.post(_url(project_id, job_id, "walls"))
    assert queued.status_code == 202, queued.text
    walls_id = queued.json()["job_id"]
    job = await _run_walls_worker(session, storage, settings, walls_id)
    assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
    return project_id, revision_id, job_id, walls_id


def _construction(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in body["constructions"] if c["id"] == key)


# ------------------------------------------------------------------ без базы


def test_routes_are_in_openapi_and_job_type_is_registered() -> None:
    base = "/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}"
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths[f"{base}/constructions"]) == {"get"}
    assert set(paths[f"{base}/constructions/{{construction_key}}/props"]) == {"put"}
    assert set(paths[f"{base}/constructions/props:bulk"]) == {"put"}
    assert set(paths[f"{base}/levels"]) == {"put"}
    assert set(paths[f"{base}/walls"]) == {"post"}
    assert JobType.CAD_WALLS.value == "cad_walls"
    assert HANDLERS[JobType.CAD_WALLS] is execute_cad_walls


def test_walls_artifact_name_is_closed() -> None:
    revision, job = uuid.uuid4(), uuid.uuid4()
    key = cad_service.artifact_storage_key(revision, job, 2, f"{FOLDER}/walls.json")
    assert key.endswith(f"/attempt-2/{FOLDER}/walls.json")
    for bad in ("walls.json", f"{FOLDER}/walls.dxf", f"{FOLDER}/../walls.json"):
        with pytest.raises(ValueError, match="артефакта"):
            cad_service.artifact_storage_key(revision, job, 1, bad)


def test_params_hash_and_versions_come_from_pins(walls_tools: Path, tmp_path: Path) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    params = cad_walls_service.load_params(settings)
    # Версия скрипта растёт аддитивно (cad_walls.v1, v1.1, …): проверяем семейство.
    assert params.generator_version.startswith("cad_walls.v1") and params.params_version == "v1"
    assert params.sha256 == cad_service.params_sha256(PARAMS)
    # Параметры в образе исполнителя другие, чем в пине, - понятная ошибка.
    (walls_tools / "params" / "v1.json").write_text(json.dumps({**PARAMS, "x": 1}), "utf-8")
    with pytest.raises(Exception, match="не совпадает с пином"):
        cad_walls_service.load_params(settings)


def test_repository_params_are_readable_by_the_api_service() -> None:
    """Версия и sha256 параметров настоящего скрипта читаются из pins.json без настройки путей."""
    params = cad_walls_service.load_params(clean_settings())
    # Версия скрипта растёт аддитивно (cad_walls.v1, v1.1, …): проверяем семейство.
    assert params.generator_version.startswith("cad_walls.v1") and params.params_version == "v1"


# ------------------------------------------------------------------ доступ


async def test_routes_are_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    fake = f"{uuid.uuid4()}", f"{uuid.uuid4()}"
    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("get", "constructions", None),
        ("put", "constructions/abc/props", {"props": {}}),
        ("put", "constructions/props:bulk", {"keys": ["a"], "props_patch": {}}),
        ("put", "levels", {}),
        ("post", "walls", None),
    ]
    async with build_api(
        make_context(), settings=walls_settings(walls_tools, tmp_path, flag=False)
    ) as api:
        for method, tail, body in calls:
            response = await api.request(method, _url(*fake, tail), json=body)
            assert response.status_code == 403, tail
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", tail


async def test_foreign_workspace_sees_and_changes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        for method, tail, body in (
            ("get", "constructions", None),
            ("put", "constructions/aaaaaaaaaaaa/props", {"props": {}}),
            ("put", "constructions/props:bulk", {"keys": ["aaaaaaaaaaaa"], "props_patch": {}}),
            ("put", "levels", {}),
            ("post", "walls", None),
        ):
            response = await foreign.request(method, _url(project_id, job_id, tail), json=body)
            assert response.status_code == 404, tail


# ------------------------------------------------------------------ задание и чтение


async def test_constructions_are_not_ready_until_the_walls_job_succeeds(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _base = await _parent(api, db_session, fake_storage)
        none_yet = await api.get(_url(project_id, job_id, "constructions"))
        assert none_yet.status_code == 404
        assert none_yet.json()["detail"]["code"] == "CAD_WALLS_NOT_READY"
        assert "issue" not in none_yet.json()["detail"]

        queued = await api.post(_url(project_id, job_id, "walls"))
        assert queued.status_code == 202
        walls_id = queued.json()["job_id"]
        assert queued.json()["status"] == "queued" and queued.json()["parent_job_id"] == job_id
        waiting = await api.get(_url(project_id, job_id, "constructions"))
        assert waiting.status_code == 404
        assert waiting.json()["detail"]["issue"]["job_status"] == "queued"

        busy = await api.post(_url(project_id, job_id, "walls"))
        assert busy.status_code == 409 and busy.json()["detail"]["code"] == "CAD_WALLS_BUSY"
        missing_view = await api.post(_url(project_id, job_id, "walls", view=7))
        assert missing_view.status_code == 404

        job = await _run_walls_worker(db_session, fake_storage, settings, walls_id)
        assert job.status is JobStatus.SUCCEEDED
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"


async def test_worker_publishes_walls_json_and_result_carries_hashes(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _p, revision_id, _job, walls_id = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
    job = await db_session.get(Job, uuid.UUID(walls_id))
    assert job is not None
    result = cad_service.result_of(job)
    key = f"revisions/{revision_id}/cad/{walls_id}/attempt-1/{FOLDER}/walls.json"
    assert result["walls_sha256"] == _sha(fake_storage.objects[key])
    assert result["generator"] == "cad_walls.v1" and result["params_version"] == "v1"
    assert result["params_sha256"] == cad_service.params_sha256(PARAMS)
    assert result["dxf_sha256"] == _sha(PARENT_DXF)
    assert result["counts"] == {
        "constructions": 4,
        "openings": 2,
        "thickness_check": 1,
        "warnings": 1,
    }
    assert [a["name"] for a in result["artifacts"]] == [f"{FOLDER}/walls.json"]
    # Скрипт получил PDF ревизии и страницу с нуля; копия параметров названа как исходный файл.
    seen = json.loads((walls_tools / "args.json").read_text())
    assert seen == {"page": "0", "params_name": "v1.json", "pdf_head": "%PDF-", "zones": None}


async def test_worker_passes_stored_zones_to_the_script(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    zones = cad_walls_zones.ZonesInput(
        raw=b'[{"kind":"room_mop","shell":[[0,0],[1,0],[1,1]]}]',
        sha256="",
        count=1,
        warning=None,
    )
    zones = dataclasses.replace(zones, sha256=_sha(zones.raw))
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        queued = await api.post(_url(project_id, job_id, "walls"))
        walls = await db_session.get(Job, uuid.UUID(queued.json()["job_id"]))
        assert walls is not None
        walls_id = walls.id
        await cad_walls_zones.store(
            fake_storage,
            revision_id=uuid.UUID(revision_id),
            parent_id=uuid.UUID(job_id),
            zones=zones,
        )
        payload = {
            **walls.payload,
            "zones_sha256": zones.sha256,
            "zones_size": len(zones.raw),
            "zones_count": 1,
        }
        await db_session.execute(update(Job).where(Job.id == walls_id).values(payload=payload))
        await db_session.commit()
        db_session.expire_all()
        job = await _run_walls_worker(db_session, fake_storage, settings, str(walls_id))
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        seen = json.loads((walls_tools / "args.json").read_text())
        assert seen["zones"] == zones.raw.decode()
        assert cad_service.result_of(job)["zones_count"] == 1

        # Подмена зон в хранилище: sha256 не совпал - запуска нет.
        again = await api.post(_url(project_id, job_id, "walls"))
        broken = await db_session.get(Job, uuid.UUID(again.json()["job_id"]))
        assert broken is not None
        broken_id = broken.id
        await db_session.execute(
            update(Job)
            .where(Job.id == broken_id)
            .values(payload={**broken.payload, "zones_sha256": "0" * 64, "zones_size": 5})
        )
        await db_session.commit()
        db_session.expire_all()
        job = await _run_walls_worker(db_session, fake_storage, settings, str(broken_id))
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_INPUT_INVALID"


@pytest.mark.parametrize(
    ("mode", "code", "message"),
    [
        ("fail", "CAD_INPUT_INVALID", "PDF не открывается"),
        ("badsha", "CAD_ENGINE_FAILED", "не относится"),
        ("badschema", "CAD_ENGINE_FAILED", "не относится"),
        ("extra", "CAD_ENGINE_FAILED", "состав out/"),
    ],
)
async def test_worker_fails_on_bad_script_output_and_publishes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
    mode: str,
    code: str,
    message: str,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    (walls_tools / "mode").write_text(mode)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _base = await _parent(api, db_session, fake_storage)
        before = set(fake_storage.objects)
        queued = await api.post(_url(project_id, job_id, "walls"))
        job = await _run_walls_worker(db_session, fake_storage, settings, queued.json()["job_id"])
        assert job.status is JobStatus.FAILED
        assert job.error_code == code and message in (job.error_message or "")
        assert set(fake_storage.objects) == before
        assert not any((tmp_path / "work").rglob("*"))
        waiting = await api.get(_url(project_id, job_id, "constructions"))
        assert waiting.json()["detail"]["issue"]["job_status"] == "failed"
        # После отказа пересчёт разрешён (новое задание).
        (walls_tools / "mode").write_text("")
        again = await api.post(_url(project_id, job_id, "walls"))
        assert again.status_code == 202 and again.json()["job_id"] != queued.json()["job_id"]


async def test_worker_fails_closed_when_the_script_is_not_configured_or_input_changed(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _base = await _parent(api, db_session, fake_storage)
        queued = await api.post(_url(project_id, job_id, "walls"))
        broken = settings.model_copy(update={"cad_walls_runner": str(walls_tools / "нет.py")})
        job = await _run_walls_worker(db_session, fake_storage, broken, queued.json()["job_id"])
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_ENGINE_UNAVAILABLE"

        # Подмена DXF в задании: sha родителя не совпадает - запуска нет.
        again = await api.post(_url(project_id, job_id, "walls"))
        walls = await db_session.get(Job, uuid.UUID(again.json()["job_id"]))
        assert walls is not None
        walls_id = str(walls.id)
        await db_session.execute(
            update(Job)
            .where(Job.id == walls.id)
            .values(payload={**walls.payload, "view_dxf_sha256": "0" * 64})
        )
        await db_session.commit()
        db_session.expire_all()
        job = await _run_walls_worker(db_session, fake_storage, settings, walls_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_INPUT_INVALID"


async def test_read_constructions_computes_values_and_sources(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, walls_id = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        response = await api.get(_url(project_id, job_id, "constructions"))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["job_id"] == job_id and body["walls_job_id"] == walls_id
        assert body["latest_walls_job"]["id"] == walls_id
        assert body["latest_walls_job"]["status"] == "succeeded"
        assert body["latest_walls_job"]["error_code"] is None
        assert body["generator"] == "cad_walls.v1" and body["dxf_sha256"] == _sha(PARENT_DXF)
        assert body["warnings"] == [{"code": "area_residue", "message": "тест"}]

        heights = body["heights"]
        assert heights["floor_elevation_mm"] == 47600
        assert heights["floor_height"] == {
            "value_mm": 3000,
            "source": "derived",
            "default_mm": 3000,
        }
        assert heights["slab_thickness"]["source"] == "assumption"
        assert heights["wall_height_mm"] == BASE_HEIGHT
        assert body["sheet_levels"] == {
            "floor_height_mm": None,
            "slab_thickness_mm": None,
            "door_height_mm": None,
            "floor_elevation_mm": None,
        }

        wall = _construction(body, "aaaaaaaaaaaa")["computed"]
        # Дверь 1000 в стене 200 толщиной: над ней 2800 - 2100 = 700.
        assert wall["volume_m3"] == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 700) / 1e9)
        assert wall["length_m"] == pytest.approx(5.0) and wall["status"] == "ok"
        assert wall["sources"] == {
            "thickness": "derived",
            "height": "derived",
            "door_height": "assumption",
            "gap_opening_height": None,
        }
        gap_host = _construction(body, "bbbbbbbbbbbb")["computed"]
        assert gap_host["warnings"] == ["opening_no_data"]
        assert gap_host["volume_m3"] == pytest.approx(500_000 * 2800 / 1e9)
        check = _construction(body, "cccccccccccc")
        assert check["thickness_status"] == "check"
        assert check["computed"]["status"] == "thickness_check"
        assert check["computed"]["volume_m3"] is None and check["computed"]["length_m"] is None
        assert check["props"]["count_openings"] is True and check["accepted"] is False

        assert body["summary"] == {
            "total_count": 4,
            "thickness_check_count": 1,
            "height_missing_count": 0,
            "unaccounted_gap_openings": 1,
            "door_openings_without_host": 0,
            "lintels_without_volume": 0,
            "orphaned_props": 0,
            "props_carried_over": 0,
        }
        assert [(g["kind"], g["thickness_mm"], g["count"]) for g in body["totals"]] == [
            ("masonry", 100.0, 1),
            ("masonry", 200.0, 1),
            ("monolith_column", 400.0, 1),
        ]
        assert {o["kind"] for o in body["openings"]} == {"door", "gap"}


async def test_props_put_replaces_props_and_recomputes_one_construction(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "constructions/cccccccccccc/props")
        body = {
            "props": {
                "material": "aerated_concrete",
                "density_grade": "D500",
                "thickness_override_mm": 250,
            },
            "accepted": True,
        }
        updated = await api.put(url, json=body)
        assert updated.status_code == 200, updated.text
        row = updated.json()
        assert row["id"] == "cccccccccccc" and row["accepted"] is True
        assert row["props"]["material"] == "aerated_concrete"
        assert row["computed"]["status"] == "ok" and row["computed"]["thickness_mm"] == 250.0
        assert row["computed"]["sources"]["thickness"] == "manual"
        # Номинала нет, толщина переопределена: длина = ось 2000 мм, объём = 2000 x 250 x 2800.
        assert row["computed"]["length_m"] == pytest.approx(2.0)
        assert row["computed"]["volume_m3"] == pytest.approx(2000 * 250 * 2800 / 1e9)

        stored = (await db_session.scalars(select(CadConstructionProps))).one()
        assert (
            stored.revision_id == uuid.UUID(revision_id)
            and stored.construction_key == "cccccccccccc"
        )
        assert (stored.page_index, stored.view, stored.accepted) == (0, 1, True)
        assert stored.props["density_grade"] == "D500" and stored.updated_by is not None

        # PUT заменяет целиком; accepted не передан - прежнее значение.
        replaced = await api.put(url, json={"props": {"note": "только заметка"}})
        assert replaced.status_code == 200
        assert replaced.json()["props"]["material"] is None and replaced.json()["accepted"] is True
        assert replaced.json()["computed"]["status"] == "thickness_check"

        listed = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert _construction(listed, "cccccccccccc")["props"]["note"] == "только заметка"

        assert (
            await api.put(_url(project_id, job_id, "constructions/nope/props"), json=body)
        ).status_code == 404
        for bad in (
            {"props": {"material": "wood"}},
            {"props": {"joint_mm": 99}},
            {"props": {"x": 1}},
        ):
            assert (await api.put(url, json=bad)).status_code == 422


async def test_props_survive_a_new_walls_job_of_the_same_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, first = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "constructions/aaaaaaaaaaaa/props")
        assert (await api.put(url, json={"props": {"purpose": "external"}})).status_code == 200

        queued = await api.post(_url(project_id, job_id, "walls"))
        assert queued.status_code == 202 and queued.json()["job_id"] != first
        job = await _run_walls_worker(db_session, fake_storage, settings, queued.json()["job_id"])
        assert job.status is JobStatus.SUCCEEDED
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert body["walls_job_id"] == str(job.id)
        assert _construction(body, "aaaaaaaaaaaa")["props"]["purpose"] == "external"


async def test_latest_walls_job_reports_a_newer_failed_recompute(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, first = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "constructions")
        (walls_tools / "mode").write_text("fail")
        queued = await api.post(_url(project_id, job_id, "walls"))
        assert queued.status_code == 202
        newer = queued.json()["job_id"]
        running = (await api.get(url)).json()
        assert running["latest_walls_job"]["id"] == newer
        assert running["latest_walls_job"]["status"] == "queued"
        job = await _run_walls_worker(db_session, fake_storage, settings, newer)
        assert job.status is JobStatus.FAILED
        body = (await api.get(url)).json()
        # Конструкции — из успешного задания, статус и ошибка — из более нового упавшего.
        assert body["walls_job_id"] == first
        assert len(body["constructions"]) == 4
        latest = body["latest_walls_job"]
        assert latest["id"] == newer and latest["status"] == "failed"
        assert latest["error_code"] == job.error_code and latest["error_code"]
        assert latest["error_message"] == job.error_message


async def test_bulk_merges_fields_counts_changes_and_rejects_unknown_keys(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        one = _url(project_id, job_id, "constructions/aaaaaaaaaaaa/props")
        await api.put(one, json={"props": {"material": "brick_solid", "note": "было"}})
        bulk = _url(project_id, job_id, "constructions/props:bulk")

        result = await api.put(
            bulk,
            json={
                "keys": ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "bbbbbbbbbbbb"],
                "props_patch": {"mortar": "glue", "note": None},
                "accepted": True,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["changed"] == 2
        assert result.json()["summary"]["total_count"] == 4 and len(result.json()["totals"]) == 3
        listed = (await api.get(_url(project_id, job_id, "constructions"))).json()
        first, second = _construction(listed, "aaaaaaaaaaaa"), _construction(listed, "bbbbbbbbbbbb")
        assert first["props"]["material"] == "brick_solid" and first["props"]["mortar"] == "glue"
        assert first["props"]["note"] is None and first["accepted"] is True
        assert second["props"]["mortar"] == "glue" and second["accepted"] is True

        # Тот же патч ничего не меняет.
        same = await api.put(
            bulk, json={"keys": ["aaaaaaaaaaaa"], "props_patch": {"mortar": "glue"}}
        )
        assert same.json()["changed"] == 0
        # Материал входит в группу итогов.
        grouped = await api.put(
            bulk, json={"keys": ["aaaaaaaaaaaa"], "props_patch": {"material": "ceramic_block"}}
        )
        assert grouped.json()["changed"] == 1
        assert "ceramic_block" in {g["material"] for g in grouped.json()["totals"]}

        unknown = await api.put(bulk, json={"keys": ["aaaaaaaaaaaa", "zzz"], "props_patch": {}})
        assert unknown.status_code == 422
        too_many = await api.put(
            bulk, json={"keys": [f"k{i}" for i in range(2001)], "props_patch": {}}
        )
        assert too_many.status_code == 422
        empty = await api.put(bulk, json={"keys": [], "props_patch": {}})
        assert empty.status_code == 422


async def test_levels_put_changes_heights_and_totals_and_null_resets(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "levels")
        changed = await api.put(url, json={"floor_height_mm": 3200, "door_height_mm": 2000})
        assert changed.status_code == 200, changed.text
        body = changed.json()
        assert body["sheet_levels"] == {
            "floor_height_mm": 3200,
            "slab_thickness_mm": None,
            "door_height_mm": 2000,
            "floor_elevation_mm": None,
        }
        assert body["heights"]["floor_height"] == {
            "value_mm": 3200,
            "source": "manual",
            "default_mm": 3000,
        }
        assert body["heights"]["wall_height_mm"] == 3000
        assert body["heights"]["wall_height_source"] == "manual"
        wall_volume = next(g for g in body["totals"] if g["thickness_mm"] == 200.0)["volume_m3"]
        assert wall_volume == pytest.approx((1_000_000 * 3000 + 1000 * 200 * 1000) / 1e9)

        stored = (await db_session.scalars(select(CadSheetLevels))).one()
        assert stored.revision_id == uuid.UUID(revision_id) and stored.floor_height_mm == 3200
        listed = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert listed["sheet_levels"]["floor_height_mm"] == 3200

        reset = await api.put(url, json={})
        assert reset.json()["heights"]["wall_height_mm"] == BASE_HEIGHT
        assert reset.json()["sheet_levels"]["floor_height_mm"] is None
        assert (
            await db_session.scalars(
                select(CadSheetLevels).execution_options(populate_existing=True)
            )
        ).one().floor_height_mm is None

        for bad in ({"floor_height_mm": 100}, {"slab_thickness_mm": 5000}, {"door_height_mm": 1}):
            assert (await api.put(url, json=bad)).status_code == 422


# ------------------------------------------------------------------ автопостановка


async def test_convert_success_enqueues_walls_for_every_view_with_dxf(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Настоящий обработчик конвертации с подменённым движком: задания появляются с успехом."""
    settings = walls_settings(walls_tools, tmp_path).model_copy(
        update={
            "cad_engine_runner": sys.executable,
            "cad_engine_archive": sys.executable,
        }
    )
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        queued = await api.post(
            f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad", json={"pages": [0]}
        )
        convert_id = queued.json()["job_id"]
        revision = await db_session.get(Job, uuid.UUID(convert_id))
        assert revision is not None and revision.job_type is JobType.CAD_PDF_CONVERT
        params_sha = str(revision.payload["params_sha256"])

        async def fake_engine(
            session: AsyncSession,
            job: Job,
            owner: str | None,
            attempt: int,
            argv: list[str],
            **_: Any,
        ) -> tuple[int, bytes]:
            out = Path(argv[argv.index("--out") + 1])
            files = {
                f"{FOLDER}/plan_candidates.dxf": PARENT_DXF,
                f"{FOLDER}/scale.json": b"{}",
                f"{FOLDER}/preview.json": b"{}",
            }
            rows = []
            for name, data in files.items():
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_bytes(data)
                rows.append({"name": name, "sha256": _sha(data), "size": len(data)})
            report = {
                "status": cad_service.RESULT_WITH_CAD,
                "disabled": ["finishes", "schedules"],
                "pages": [
                    {
                        "index": 0,
                        "legacy_pdf_page": 1,
                        "views": [
                            {
                                "view": 1,
                                "status": "needs_review",
                                "dxf": {"file": f"{FOLDER}/plan_candidates.dxf", "entities": 5},
                            },
                            {
                                "view": 2,
                                "status": "failed",
                                "failure_code": "x",
                                "failure_reason": "нет",
                            },
                        ],
                    }
                ],
            }
            (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
            report_bytes = (out / "report.json").read_bytes()
            rows.append(
                {"name": "report.json", "sha256": _sha(report_bytes), "size": len(report_bytes)}
            )
            manifest = {
                "files": rows,
                "engine": {
                    "archive_sha256": cad_service.ENGINE_ARCHIVE_SHA256,
                    "version": cad_service.ENGINE_VERSION,
                },
                "input": {"sha256": _sha(BROKEN_PDF)},
                "params_sha256": params_sha,
            }
            (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return 0, b""

        monkeypatch.setattr(convert_handler, "_run_while_owned", fake_engine)
        job = await jobs_service.claim(
            db_session,
            worker_id="cad-test",
            job_types=[t.value for t in HANDLERS],
            lease_seconds=600,
        )
        await db_session.commit()
        assert job is not None and str(job.id) == convert_id
        assert HANDLERS[job.job_type] is execute_cad_pdf_convert
        job = await execute_cad_pdf_convert(db_session, job, fake_storage, settings)
        await db_session.commit()
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)

        walls = (
            await db_session.scalars(select(Job).where(Job.job_type == JobType.CAD_WALLS))
        ).all()
        assert len(walls) == 1, "только вид с DXF"
        payload = walls[0].payload
        assert walls[0].status is JobStatus.QUEUED and walls[0].project_id == job.project_id
        assert (payload["parent_job_id"], payload["page_index"], payload["view"]) == (
            convert_id,
            0,
            1,
        )
        assert payload["view_dxf_sha256"] == _sha(PARENT_DXF)
        assert payload["generator_version"] == "cad_walls.v1" and payload["parent_attempt"] == 1

        # Повторный вызов того же успеха задание не дублирует.
        again = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, job, settings
        )
        await db_session.commit()
        assert [j.id for j in again] == [walls[0].id]

        # Сам выпущенный задачей cad_walls вид читается обработчиком cad_walls.
        done = await _run_walls_worker(db_session, fake_storage, settings, str(walls[0].id))
        assert done.status is JobStatus.SUCCEEDED, (done.error_code, done.error_message)
        read = await api.get(_url(project_id, convert_id, "constructions"))
        assert read.status_code == 200 and read.json()["summary"]["total_count"] == 4


async def test_convert_success_survives_missing_walls_params(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    """Нет параметров скрипта - конвертация остаётся успешной, заданий конструкций нет."""
    settings = walls_settings(walls_tools, tmp_path)
    (walls_tools / "params" / "v1.json").unlink()
    parent = Job(
        job_type=JobType.CAD_PDF_CONVERT,
        workspace_id=None,
        status=JobStatus.SUCCEEDED,
        payload={},
    )
    assert (
        await cad_walls_service.enqueue_after_convert(db_session, fake_storage, parent, settings)
        == []
    )


# ------------------------------------------------------------------ перенос параметров


async def _props_rows(session: AsyncSession) -> dict[str, dict[str, Any]]:
    session.expire_all()
    rows = (await session.scalars(select(CadConstructionProps))).all()
    return {row.construction_key: row.props for row in rows}


async def _recompute(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
    ids: tuple[str, str],
) -> Job:
    queued = await api.post(_url(ids[0], ids[1], "walls"))
    assert queued.status_code == 202, queued.text
    job = await _run_walls_worker(session, storage, settings, queued.json()["job_id"])
    assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
    return job


async def test_props_are_carried_to_the_new_id_after_a_recompute(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _first = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "constructions/aaaaaaaaaaaa/props")
        assert (await api.put(url, json={"props": {"purpose": "external"}})).status_code == 200
        before = (await db_session.scalars(select(CadConstructionProps))).one()
        updated_by = before.updated_by

        (walls_tools / "mode").write_text("renamed")
        await _recompute(api, db_session, fake_storage, settings, (project_id, job_id))
        response = await api.get(_url(project_id, job_id, "constructions"))
        assert response.status_code == 200, response.text
        body = response.json()
        assert {c["id"] for c in body["constructions"]} >= {"raaaaaaaaaaa"}
        assert _construction(body, "raaaaaaaaaaa")["props"]["purpose"] == "external"
        assert body["summary"]["props_carried_over"] == 1 and body["summary"]["orphaned_props"] == 0
        assert not any(w["code"] == "props_orphaned" for w in body["warnings"])
        rows = await _props_rows(db_session)
        assert set(rows) == {"raaaaaaaaaaa"} and rows["raaaaaaaaaaa"]["purpose"] == "external"
        db_session.expire_all()
        assert (
            await db_session.scalars(select(CadConstructionProps))
        ).one().updated_by == updated_by

        # Повторное чтение: переносить больше нечего, параметры на месте.
        again = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert again["summary"]["props_carried_over"] == 0
        assert _construction(again, "raaaaaaaaaaa")["props"]["purpose"] == "external"


async def test_props_without_a_match_are_reported_as_orphaned(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _first = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        url = _url(project_id, job_id, "constructions/aaaaaaaaaaaa/props")
        assert (await api.put(url, json={"props": {"purpose": "external"}})).status_code == 200

        (walls_tools / "mode").write_text("gone")
        await _recompute(api, db_session, fake_storage, settings, (project_id, job_id))
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert body["summary"]["orphaned_props"] == 1
        assert body["summary"]["props_carried_over"] == 0
        assert any(w["code"] == "props_orphaned" for w in body["warnings"])
        assert all(c["props"]["purpose"] is None for c in body["constructions"])
        # Запись не удаляется и не переписывается: она может пригодиться при откате.
        assert set(await _props_rows(db_session)) == {"aaaaaaaaaaaa"}


async def test_constructions_are_not_ready_when_the_dxf_changed_after_the_walls_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _first = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        payload = json.loads(json.dumps(parent.payload))
        for artifact in payload["cad_result"]["artifacts"]:
            if artifact["name"].endswith("plan_candidates.dxf"):
                artifact["sha256"] = "e" * 64
        await db_session.execute(update(Job).where(Job.id == parent.id).values(payload=payload))
        await db_session.commit()
        db_session.expire_all()

        response = await api.get(_url(project_id, job_id, "constructions"))
        assert response.status_code == 404, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "CAD_WALLS_NOT_READY"
        assert detail["issue"]["reason"] == "dxf_changed"
        # Пересчёт по новому DXF снова даёт результат (заглушка считает sha по входному файлу).
        put = await api.put(
            _url(project_id, job_id, "constructions/aaaaaaaaaaaa/props"), json={"props": {}}
        )
        assert put.status_code == 404 and put.json()["detail"]["code"] == "CAD_WALLS_NOT_READY"


async def test_generator_warning_slab_without_zones_reaches_the_response(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    (walls_tools / "mode").write_text("slabwarn")
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        body = (await api.get(_url(project_id, job_id, "constructions"))).json()
        assert body["warnings"] == [
            {"code": "area_residue", "message": "тест"},
            {"code": "slab_without_zones", "message": "плита по стенам"},
        ]
