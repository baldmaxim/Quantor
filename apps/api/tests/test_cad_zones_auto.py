"""Авторазметка зон (`cad_zones`) и общий статус конвейера CAD ревизии.

Движок и настоящий CLI не нужны: родитель `cad_pdf_convert` выставляется прямо в базе и хранилище
(как у тестов трасс), а `cad_mep/run_zones.py` подменён заглушкой, которая пишет `zones.json`
по CLI-контракту. Режим заглушки задаёт файл `mode` рядом со скриптом: `fail` - код выхода 2.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker.handler import _run_while_owned
from app.cad_worker.zones_handler import execute_cad_zones
from app.contracts.cad_zones import CadZoneCreate
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadZone, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_zones as cad_zones_service
from app.services import cad_zones_auto
from app.services import jobs as jobs_service
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_mep import APPROVAL, FOLDER, PARAMS, _parent
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated
from tests.test_cad_zones import RECT, _room

STUB = """
import argparse, json, pathlib, sys

parser = argparse.ArgumentParser()
for name in ("pdf", "page-index", "view-dxf", "scale", "preview", "params", "out"):
    parser.add_argument("--" + name)
args = parser.parse_args()
here = pathlib.Path(__file__).parent
mode = (here / "mode").read_text().strip() if (here / "mode").exists() else ""
for name in ("pdf", "view_dxf", "scale", "preview", "params"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
(here / "args.json").write_text(json.dumps({
    "page_index": args.page_index, "out_name": pathlib.Path(args.out).name,
    "params_name": pathlib.Path(args.params).name}))
if mode == "fail":
    print(json.dumps({"code": "no_explication", "message": "Экспликация не найдена"}),
          file=sys.stderr)
    sys.exit(2)
rect = [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]]
bow = [[0.1, 0.1], [0.4, 0.4], [0.4, 0.1], [0.1, 0.4]]
zones = [
    {"kind": "room_apartment", "apartment_no": "0042", "room_mark": "3-1/6", "name": "Спальня",
     "expl_area_m2": 12.5, "poly_area_m2": 12.4, "points": rect, "notes": []},
    {"kind": "room_apartment", "apartment_no": "0042", "room_mark": "3-1/7", "name": "Узел",
     "expl_area_m2": 3.0, "poly_area_m2": 3.0, "points": bow, "notes": []},
]
doc = {"schema": "quantor.cad_mep.zones.v1", "generator_version": "cad_mep.v1",
       "page_index": int(args.page_index), "scale_mm_per_pt": 35.0, "zones": zones,
       "unmatched_marks": [], "summary": []}
if mode == "mop":
    doc["zones"] = [
        {"kind": "room_apartment", "apartment_no": "0042", "room_mark": "3-1/6", "name": "Спальня",
         "points": rect},
        {"kind": "room_mop", "apartment_no": None, "room_mark": "3-3.2", "name": "Тамбур-шлюз",
         "expl_area_m2": 3.5, "poly_area_m2": 3.53, "points": rect, "notes": []},
        {"kind": "room_mop", "apartment_no": None, "room_mark": "3-3.4",
         "name": "Лестничная клетка", "points": rect},
    ]
if mode == "parking":
    doc["zones"] = []
    doc["parking_spaces"] = [
        {"parking_type": "permanent", "label": "Места постоянное хранение", "points": rect,
         "width_m": 2.5, "length_m": 5.3, "area_m2": 13.25, "type_margin": 0.17, "notes": []},
        {"parking_type": "medium", "label": None, "points": rect, "notes": ["тип под вопросом"]},
        {"parking_type": "guest", "label": "Гостевое", "points": bow},
    ]
out = pathlib.Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
"""


@pytest.fixture
def zones_tools(tmp_path: Path) -> Path:
    """Параметры, версия и заглушка CLI зон: то, что в образе лежит в generators/cad_mep."""
    root = tmp_path / "tools" / "cad_mep"
    (root / "params").mkdir(parents=True)
    (root / "cad_mep").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_mep.py").write_text("", encoding="utf-8")
    (root / "run_zones.py").write_text(STUB, encoding="utf-8")
    return root


def zones_settings(tools: Path, tmp_path: Path, *, flag: bool = True) -> Settings:
    # Конвейер листа ставит и `cad_walls` (его заглушки здесь нет): в pins нужен и этот генератор.
    walls_params = tmp_path / "pinned" / "cad_walls" / "params" / "v1.json"
    walls_params.parent.mkdir(parents=True, exist_ok=True)
    walls_params.write_text(json.dumps(PARAMS), encoding="utf-8")
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_mep_runner=str(tools / "run_mep.py"),
        cad_mep_params=str(tools / "params" / "v1.json"),
        cad_engine_pins=write_pins(tmp_path, mep=tools / "params" / "v1.json", walls=walls_params),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


def _zones_url(project_id: str, job_id: str, page: int = 0, view: int = 1) -> str:
    return f"/api/v1/projects/{project_id}/cad/{job_id}/views/{page}/{view}/zones/auto"


async def _run_zones_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="cad-zones-test",
        job_types=[JobType.CAD_ZONES.value],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    assert HANDLERS[job.job_type] is execute_cad_zones
    job = await execute_cad_zones(session, job, storage, settings)
    await session.commit()
    return job


async def _zones_of(session: AsyncSession) -> list[CadZone]:
    session.expire_all()
    return list(await session.scalars(select(CadZone).order_by(CadZone.created_at)))


# ------------------------------------------------------------------ без базы


def test_zones_routes_are_in_openapi_and_job_type_is_registered() -> None:
    paths = create_app(clean_settings(environment="test")).openapi()["paths"]
    assert (
        "/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/zones/auto" in paths
    )
    assert "/api/v1/projects/{project_id}/revisions/{revision_id}/cad/pipeline" in paths
    assert HANDLERS[JobType.CAD_ZONES] is execute_cad_zones


def test_zones_artifact_name_is_closed() -> None:
    revision, job = uuid.uuid4(), uuid.uuid4()
    key = cad_service.artifact_storage_key(revision, job, 1, f"{FOLDER}/zones.json")
    assert key.endswith(f"/attempt-1/{FOLDER}/zones.json")
    for bad in ("zones.json", f"{FOLDER}/zones.dxf", "views/p001_v01/../zones.json"):
        with pytest.raises(ValueError):
            cad_service.artifact_storage_key(revision, job, 1, bad)


# ------------------------------------------------------------------ автопостановка


async def test_enqueue_after_convert_skips_sheets_with_zones_and_is_idempotent(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None

        # Генератор не настроен - конвертацию это не рушит, заданий нет.
        unset = settings.model_copy(update={"cad_mep_runner": ""})
        assert await cad_zones_auto.enqueue_after_convert(db_session, parent, unset) == []

        jobs = await cad_zones_auto.enqueue_after_convert(db_session, parent, settings)
        await db_session.commit()
        assert len(jobs) == 1
        payload = jobs[0].payload
        assert jobs[0].job_type is JobType.CAD_ZONES and jobs[0].status is JobStatus.QUEUED
        assert (payload["parent_job_id"], payload["page_index"], payload["view"]) == (job_id, 0, 1)
        assert payload["view_dxf_sha256"] and payload["parent_attempt"] == 1
        assert payload["generator_version"] == "cad_mep.v1"

        # Повтор того же успеха задание не дублирует.
        again = await cad_zones_auto.enqueue_after_convert(db_session, parent, settings)
        assert [j.id for j in again] == [jobs[0].id]

        # Лист с зонами человека разметке не отдаётся.
        await db_session.execute(delete(Job).where(Job.job_type == JobType.CAD_ZONES))
        created = await api.post(
            f"/api/v1/projects/{project_id}/cad/zones", json=_room(revision_id)
        )
        assert created.status_code == 201
        assert await cad_zones_auto.enqueue_after_convert(db_session, parent, settings) == []
        count = await db_session.scalar(
            select(func.count()).select_from(Job).where(Job.job_type == JobType.CAD_ZONES)
        )
        assert count == 0


# ------------------------------------------------------------------ ручной запуск


async def test_manual_start_is_closed_by_flag_and_foreign_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    second_id = second_workspace.id
    fake = f"{uuid.uuid4()}", f"{uuid.uuid4()}"
    async with build_api(
        make_context(), settings=zones_settings(zones_tools, tmp_path, flag=False)
    ) as api:
        response = await api.post(_zones_url(*fake))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"

    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
    async with build_api(
        make_context(platform_admin=False, workspace_id=second_id), settings=settings
    ) as foreign:
        assert (await foreign.post(_zones_url(project_id, job_id))).status_code == 404


async def test_manual_start_returns_conflicts_and_queues_a_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        assert (await api.post(_zones_url(project_id, job_id, view=9))).status_code == 404

        queued = await api.post(_zones_url(project_id, job_id))
        assert queued.status_code == 202, queued.text
        body = queued.json()
        assert body["parent_job_id"] == job_id and (body["page_index"], body["view"]) == (0, 1)
        assert body["status"] == "queued" and body["attempt"] == 0

        # Пока задание этого вида в очереди - 409 CAD_ZONES_BUSY.
        busy = await api.post(_zones_url(project_id, job_id))
        assert busy.status_code == 409 and busy.json()["detail"]["code"] == "CAD_ZONES_BUSY"

        # Появились зоны - 409 CAD_ZONES_NOT_EMPTY раньше BUSY.
        zone = await api.post(f"/api/v1/projects/{project_id}/cad/zones", json=_room(revision_id))
        assert zone.status_code == 201
        full = await api.post(_zones_url(project_id, job_id))
        assert full.status_code == 409 and full.json()["detail"]["code"] == "CAD_ZONES_NOT_EMPTY"


# ------------------------------------------------------------------ обработчик


async def test_handler_inserts_zones_through_the_zone_service_and_stores_zones_json(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        queued = await api.post(_zones_url(project_id, job_id))
        zones_id = queued.json()["job_id"]
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)

        result = cad_service.result_of(job)
        assert result["result_status"] == "zones_ready"
        # Годная зона создана, самопересекающаяся отклонена сервисом зон.
        assert result["counts"] == {"in_file": 2, "created": 1, "rejected": 1}
        key = f"revisions/{revision_id}/cad/{zones_id}/attempt-1/{FOLDER}/zones.json"
        assert [a["name"] for a in result["artifacts"]] == [f"{FOLDER}/zones.json"]
        assert key in fake_storage.objects
        assert result["zones_sha256"] == result["artifacts"][0]["sha256"]

        listed = await api.get(f"/api/v1/projects/{project_id}/cad/zones?revision_id={revision_id}")
        assert listed.status_code == 200
        (zone,) = listed.json()
        assert (zone["kind"], zone["apartment_no"], zone["room_mark"]) == (
            "room_apartment",
            "0042",
            "3-1/6",
        )
        assert zone["name"] == "Спальня" and zone["points"] == RECT
        # Площадь и периметр посчитал сервер по калибровке листа, а не взяты из файла.
        assert zone["area_m2"] is not None and zone["perimeter_m"] is not None
        assert zone["area_m2"] != 12.4

        seen = json.loads((zones_tools / "args.json").read_text())
        assert seen == {"page_index": "0", "out_name": "zones.json", "params_name": "params.json"}
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"

        # Разметка уже есть - второй запуск вручную закрыт.
        again = await api.post(_zones_url(project_id, job_id))
        assert again.status_code == 409 and again.json()["detail"]["code"] == "CAD_ZONES_NOT_EMPTY"


async def test_handler_inserts_mop_zones_with_derived_room_type(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    (zones_tools / "mode").write_text("mop")
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        queued = await api.post(_zones_url(project_id, job_id))
        job = await _run_zones_worker(db_session, fake_storage, settings, queued.json()["job_id"])
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert cad_service.result_of(job)["counts"] == {"in_file": 3, "created": 3, "rejected": 0}

        listed = await api.get(f"/api/v1/projects/{project_id}/cad/zones?revision_id={revision_id}")
        assert listed.status_code == 200
        by_mark = {z["room_mark"]: z for z in listed.json()}
        assert by_mark["3-1/6"]["kind"] == "room_apartment"
        assert by_mark["3-1/6"]["apartment_no"] == "0042"
        for mark, name, room_type in (
            ("3-3.2", "Тамбур-шлюз", "airlock"),
            ("3-3.4", "Лестничная клетка", "stair"),
        ):
            zone = by_mark[mark]
            assert (zone["kind"], zone["apartment_no"], zone["name"]) == ("room_mop", None, name)
            assert zone["room_type"] == room_type
            assert zone["area_m2"] is not None


async def test_handler_inserts_parking_spaces_when_there_are_no_room_zones(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    (zones_tools / "mode").write_text("parking")
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        result = cad_service.result_of(job)
        # Самопересекающееся место отклонено сервисом зон, как и у квартир.
        assert result["counts"] == {"in_file": 3, "created": 2, "rejected": 1}

        listed = await api.get(f"/api/v1/projects/{project_id}/cad/zones?revision_id={revision_id}")
        zones = listed.json()
        assert {(z["kind"], z["parking_type"], z["name"]) for z in zones} == {
            ("parking_space", "permanent", "Места постоянное хранение"),
            ("parking_space", "medium", "Medium"),
        }
        assert all(z["apartment_no"] is None and z["room_mark"] is None for z in zones)
        assert all(z["area_m2"] is not None for z in zones)

        # Места - разметка листа: повторный автозапуск их не дублирует.
        again = await api.post(_zones_url(project_id, job_id))
        assert again.status_code == 409 and again.json()["detail"]["code"] == "CAD_ZONES_NOT_EMPTY"
        assert len(await _zones_of(db_session)) == 2


async def test_handler_skips_when_zones_exist_before_start(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        # Человек успел разметить лист, пока задание ждало в очереди.
        assert (
            await api.post(f"/api/v1/projects/{project_id}/cad/zones", json=_room(revision_id))
        ).status_code == 201
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.SUCCEEDED
        result = cad_service.result_of(job)
        assert result["result_status"] == "zones_skipped_existing" and result["artifacts"] == []
        assert len(await _zones_of(db_session)) == 1
        assert not (zones_tools / "args.json").exists(), "CLI не должен запускаться"


async def test_handler_inserts_nothing_when_zones_appear_while_cli_runs(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)

    async def human_marks_meanwhile(
        session: AsyncSession, job: Job, *args: Any, **kwargs: Any
    ) -> tuple[int, bytes] | None:
        outcome = await _run_while_owned(session, job, *args, **kwargs)
        await cad_zones_service.create_zone(
            session,
            workspace_id=job.workspace_id or uuid.uuid4(),
            project_id=job.project_id or uuid.uuid4(),
            body=_zone_body(job),
            user_id=None,
        )
        return outcome

    def _zone_body(job: Job) -> Any:
        return CadZoneCreate(
            revision_id=uuid.UUID(str(job.payload["revision_id"])),
            page_index=0,
            kind="room_apartment",
            apartment_no="0007",
            points=[(x, y) for x, y in RECT],
        )

    monkeypatch.setattr("app.cad_worker.zones_handler._run_while_owned", human_marks_meanwhile)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        result = cad_service.result_of(job)
        assert result["result_status"] == "zones_skipped_existing"
        assert result["counts"]["created"] == 0
        (only,) = await _zones_of(db_session)
        assert only.apartment_no == "0007", "зона человека не тронута, зон генератора нет"


async def test_handler_rechecks_page_zones_after_taking_the_page_lock(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Соседний вид страницы вставил зоны, пока ждали блокировку: вставки нет, дублей нет."""
    settings = zones_settings(zones_tools, tmp_path)
    locked: list[tuple[uuid.UUID, int]] = []
    real_lock = cad_zones_service.lock_page_zones

    async def lock_then_neighbour_inserts(
        session: AsyncSession, *, revision_id: uuid.UUID, page_index: int
    ) -> None:
        await real_lock(session, revision_id=revision_id, page_index=page_index)
        locked.append((revision_id, page_index))
        owner = (
            await session.execute(
                select(Job.workspace_id, Job.project_id).where(Job.job_type == JobType.CAD_ZONES)
            )
        ).one()
        await cad_zones_service.create_zone(
            session,
            workspace_id=owner.workspace_id,
            project_id=owner.project_id,
            body=CadZoneCreate(
                revision_id=revision_id,
                page_index=page_index,
                kind="room_apartment",
                apartment_no="0009",
                points=[(x, y) for x, y in RECT],
            ),
            user_id=None,
        )

    monkeypatch.setattr(cad_zones_service, "lock_page_zones", lock_then_neighbour_inserts)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert cad_service.result_of(job)["result_status"] == "zones_skipped_existing"
        assert len(locked) == 1
        (only,) = await _zones_of(db_session)
        assert only.apartment_no == "0009"


async def test_lock_page_zones_runs_on_a_real_database(db_session: AsyncSession) -> None:
    await cad_zones_service.lock_page_zones(db_session, revision_id=uuid.uuid4(), page_index=3)
    # Повторная блокировка того же ключа в той же транзакции не блокируется.
    revision_id = uuid.uuid4()
    await cad_zones_service.lock_page_zones(db_session, revision_id=revision_id, page_index=0)
    await cad_zones_service.lock_page_zones(db_session, revision_id=revision_id, page_index=0)
    await db_session.rollback()


async def test_handler_fails_with_cli_error_and_inserts_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    (zones_tools / "mode").write_text("fail")
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == "CAD_INPUT_INVALID"
        assert "Экспликация не найдена" in (job.error_message or "")
        assert await _zones_of(db_session) == []
        assert not [k for k in fake_storage.objects if k.endswith("zones.json")]

        # Отказ не блокирует повторный запуск: нет ни зон, ни активного задания.
        retry = await api.post(_zones_url(project_id, job_id))
        assert retry.status_code == 202


async def test_handler_fails_closed_when_cli_is_not_configured(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        zones_id = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        (zones_tools / "run_zones.py").unlink()
        job = await _run_zones_worker(db_session, fake_storage, settings, zones_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_ENGINE_UNAVAILABLE"


# ------------------------------------------------------------------ статус конвейера


def _pipeline_url(project_id: str, revision_id: str) -> str:
    return f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/pipeline"


async def test_pipeline_is_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient], zones_tools: Path, tmp_path: Path
) -> None:
    async with build_api(
        make_context(), settings=zones_settings(zones_tools, tmp_path, flag=False)
    ) as api:
        response = await api.get(_pipeline_url(str(uuid.uuid4()), str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_pipeline_calibrated_page_without_jobs(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=zones_settings(zones_tools, tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        response = await api.get(_pipeline_url(project_id, revision_id))
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"revision_id", "server_time", "sheets"}
        assert body["revision_id"] == revision_id
        assert body["sheets"] == [
            {
                "page_index": 0,
                "page_label": None,
                "title": None,
                "is_plan": False,
                "calibrated": True,
                "floor_title": None,
                "convert": None,
                "update": None,
                "scale_source": None,
                "views": [],
            }
        ]
        # Чужая ревизия - 404.
        missing = await api.get(_pipeline_url(project_id, str(uuid.uuid4())))
        assert missing.status_code == 404


async def test_pipeline_converted_page_shows_walls_zones_and_decisions(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        walls = await api.post(f"/api/v1/projects/{project_id}/cad/{job_id}/views/0/1/walls")
        assert walls.status_code == 202, walls.text
        zones = await api.post(_zones_url(project_id, job_id))
        assert zones.status_code == 202

        body = (await api.get(_pipeline_url(project_id, revision_id))).json()
        (sheet,) = body["sheets"]
        assert (sheet["page_index"], sheet["calibrated"]) == (0, True)
        convert = sheet["convert"]
        assert convert["job_id"] == job_id and convert["job_type"] == "cad_pdf_convert"
        assert convert["status"] == "succeeded" and convert["result_status"] == (
            "completed_requires_review"
        )
        assert set(convert) == {
            "job_id",
            "job_type",
            "status",
            "progress",
            "stage",
            "result_status",
            "error_code",
            "created_at",
            "finished_at",
        }
        (view,) = sheet["views"]
        assert set(view) == {
            "page",
            "view",
            "has_dxf",
            "walls",
            "zones",
            "zones_count",
            "approved",
            "routes",
            "routes_accepted",
            "floor3d",
        }
        assert (view["page"], view["view"], view["has_dxf"]) == (0, 1, True)
        assert view["walls"]["job_id"] == walls.json()["job_id"]
        assert view["walls"]["job_type"] == "cad_walls" and view["walls"]["status"] == "queued"
        assert view["zones"]["job_id"] == zones.json()["job_id"]
        assert view["zones"]["job_type"] == "cad_zones" and view["zones"]["result_status"] is None
        assert (view["zones_count"], view["approved"]) == (0, False)
        assert (view["routes"], view["routes_accepted"], view["floor3d"]) == (None, False, None)

        # Зоны сделаны, вид одобрен: статус отражает и задание, и решение человека.
        done = await _run_zones_worker(db_session, fake_storage, settings, zones.json()["job_id"])
        assert done.status is JobStatus.SUCCEEDED
        assert (
            await api.post(f"{base}/{job_id}/views/0/1/approval", json=APPROVAL)
        ).status_code == 201
        view = (await api.get(_pipeline_url(project_id, revision_id))).json()["sheets"][0]["views"][
            0
        ]
        assert view["zones"]["status"] == "succeeded"
        assert view["zones"]["result_status"] == "zones_ready"
        assert view["zones"]["finished_at"] is not None
        assert (view["zones_count"], view["approved"]) == (1, True)


async def test_pipeline_shows_the_ready_convert_and_gives_the_newer_as_update(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    """Готовый прогон остаётся показанным, более новый идущий отдаётся как `update`."""
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        assert (await api.post(_zones_url(project_id, job_id))).status_code == 202
        old = await db_session.get(Job, uuid.UUID(job_id))
        assert old is not None
        newer = Job(
            job_type=JobType.CAD_PDF_CONVERT,
            workspace_id=old.workspace_id,
            project_id=old.project_id,
            status=JobStatus.RUNNING,
            payload={"revision_id": revision_id, "params": {"pages": [0]}},
        )
        db_session.add(newer)
        await db_session.commit()
        (sheet,) = (await api.get(_pipeline_url(project_id, revision_id))).json()["sheets"]
        assert sheet["convert"]["job_id"] == job_id
        assert sheet["update"]["job_id"] == str(newer.id)
        assert sheet["update"]["status"] == "running"
        # Виды и дочерние задания - от показываемого прогона.
        assert sheet["views"][0]["zones"]["status"] == "queued"


async def test_pipeline_gives_floor_title_from_the_last_successful_walls(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    zones_tools: Path,
    tmp_path: Path,
) -> None:
    """Заголовок плана берётся из итога успешного cad_walls; нет итога или заголовка - null."""
    settings = zones_settings(zones_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        walls = await api.post(f"/api/v1/projects/{project_id}/cad/{job_id}/views/0/1/walls")
        assert walls.status_code == 202, walls.text
        sheet = (await api.get(_pipeline_url(project_id, revision_id))).json()["sheets"][0]
        assert sheet["floor_title"] is None

        job = await db_session.get(Job, uuid.UUID(walls.json()["job_id"]))
        assert job is not None
        job.status = JobStatus.SUCCEEDED
        job.payload = {
            **job.payload,
            "cad_result": {
                "result_status": "walls_ready",
                "attempt": job.attempt,
                "floor_title": {
                    "corps": "9",
                    "section": "3",
                    "floors": [14],
                    "text": "Корпус 9. Секция 3. План 14 этажа",
                },
            },
        }
        await db_session.commit()
        sheet = (await api.get(_pipeline_url(project_id, revision_id))).json()["sheets"][0]
        assert sheet["floor_title"] == {
            "corps": "9",
            "section": "3",
            "floors": ["14"],
            "text": "Корпус 9. Секция 3. План 14 этажа",
        }

        # Итог без заголовка (старое задание или заголовок не найден) - null, не ошибка.
        job.payload = {
            **job.payload,
            "cad_result": {**job.payload["cad_result"], "floor_title": None},
        }
        await db_session.commit()
        sheet = (await api.get(_pipeline_url(project_id, revision_id))).json()["sheets"][0]
        assert sheet["floor_title"] is None
