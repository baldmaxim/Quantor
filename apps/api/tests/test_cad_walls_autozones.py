"""Зоны помещений во входе автопостановки `cad_walls` и пересчёт после авторазметки зон.

Родитель `cad_pdf_convert` выставляется прямо в базе и хранилище (как у тестов трасс); скрипты
конструкций и зон подменены заглушками из соседних тестов.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import walls_handler
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_walls as cad_walls_service
from app.services import cad_walls_zones, cad_zones_auto
from app.storage.base import StorageUnavailableError
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS as WALLS_PARAMS
from tests.test_cad_constructions_api import STUB as WALLS_STUB
from tests.test_cad_constructions_api import _run_walls_worker
from tests.test_cad_mep import FOLDER, _parent
from tests.test_cad_mep import PARAMS as MEP_PARAMS
from tests.test_cad_qa import A3_HEIGHT, A3_WIDTH
from tests.test_cad_zones_auto import STUB as ZONES_STUB
from tests.test_cad_zones_auto import _run_zones_worker


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    walls = tmp_path / "tools" / "cad_walls"
    (walls / "params").mkdir(parents=True)
    (walls / "cad_walls").mkdir()
    (walls / "params" / "v1.json").write_text(json.dumps(WALLS_PARAMS), encoding="utf-8")
    (walls / "run_walls.py").write_text(WALLS_STUB, encoding="utf-8")
    mep = tmp_path / "tools" / "cad_mep"
    (mep / "params").mkdir(parents=True)
    (mep / "cad_mep").mkdir()
    (mep / "params" / "v1.json").write_text(json.dumps(MEP_PARAMS), encoding="utf-8")
    (mep / "run_mep.py").write_text("", encoding="utf-8")
    (mep / "run_zones.py").write_text(ZONES_STUB, encoding="utf-8")
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true",
        cad_engine_python=sys.executable,
        cad_walls_runner=str(walls / "run_walls.py"),
        cad_walls_params=str(walls / "params" / "v1.json"),
        cad_mep_runner=str(mep / "run_mep.py"),
        cad_mep_params=str(mep / "params" / "v1.json"),
        cad_engine_pins=write_pins(
            tmp_path, mep=mep / "params" / "v1.json", walls=walls / "params" / "v1.json"
        ),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


async def _apartment_zone(api: AsyncClient, project_id: str, revision_id: str) -> None:
    """Квартира 1000 x 2000 мм DXF в кадре родителя (масштаб 35.2778, начало 10, 20 pt)."""
    factor, origin = 35.2778, (10.0, 20.0)
    corners_mm = [(1000.0, -500.0), (2000.0, -500.0), (2000.0, -2500.0), (1000.0, -2500.0)]
    points = [
        [(origin[0] + x / factor) / float(A3_WIDTH), (origin[1] - y / factor) / float(A3_HEIGHT)]
        for x, y in corners_mm
    ]
    created = await api.post(
        f"/api/v1/projects/{project_id}/cad/zones",
        json={
            "revision_id": revision_id,
            "page_index": 0,
            "kind": "room_apartment",
            "apartment_no": "1",
            "points": points,
        },
    )
    assert created.status_code == 201, created.text


async def _walls_jobs(session: AsyncSession) -> list[Job]:
    session.expire_all()
    rows = await session.scalars(
        select(Job).where(Job.job_type == JobType.CAD_WALLS).order_by(Job.created_at, Job.id)
    )
    return list(rows)


async def test_auto_enqueue_passes_sheet_zones_to_the_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _apartment_zone(api, project_id, revision_id)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        await db_session.commit()
        assert job.payload["zones_count"] == 1 and job.payload["zones_sha256"]
        assert "zones_warning" not in job.payload
        key = cad_walls_zones.input_key(uuid.UUID(revision_id), job.payload["zones_sha256"])
        assert key in fake_storage.objects


async def test_auto_enqueue_without_zones_is_as_before(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert job.payload["zones_count"] == 0 and job.payload["zones_sha256"] == ""
        assert "zones_warning" not in job.payload


async def test_parking_spaces_are_not_passed_to_the_walls_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        created = await api.post(
            f"/api/v1/projects/{project_id}/cad/zones",
            json={
                "revision_id": revision_id,
                "page_index": 0,
                "kind": "parking_space",
                "parking_type": "guest",
                "points": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]],
            },
        )
        assert created.status_code == 201, created.text
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert job.payload["zones_count"] == 0 and job.payload["zones_sha256"] == ""


async def test_auto_enqueue_without_view_frame_reports_why(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _apartment_zone(api, project_id, revision_id)
        scale = next(key for key in fake_storage.objects if key.endswith(f"{FOLDER}/scale.json"))
        del fake_storage.objects[scale]
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert job.payload["zones_count"] == 0 and job.payload["zones_sha256"] == ""
        assert "кадр координат не установлен" in job.payload["zones_warning"]


async def test_auto_enqueue_survives_storage_failure_reading_zones(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_args: object, **_kwargs: object) -> cad_walls_zones.ZonesInput:
        raise StorageUnavailableError("хранилище недоступно")

    monkeypatch.setattr(cad_walls_zones, "sheet_room_zones", broken)
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert job.status is JobStatus.QUEUED and job.payload["zones_sha256"] == ""
        assert "зоны листа не прочитаны" in job.payload["zones_warning"]


async def test_recompute_is_queued_after_auto_zones_and_does_not_loop(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        # Лист без разметки человека: первое задание конструкций уходит без зон.
        (first,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        await db_session.commit()
        assert first.payload["zones_sha256"] == ""
        done = await _run_walls_worker(db_session, fake_storage, settings, str(first.id))
        assert done.status is JobStatus.SUCCEEDED, (done.error_code, done.error_message)

        (zones_job,) = await cad_zones_auto.enqueue_after_convert(db_session, parent, settings)
        await db_session.commit()
        finished = await _run_zones_worker(db_session, fake_storage, settings, str(zones_job.id))
        assert finished.status is JobStatus.SUCCEEDED
        assert cad_service.result_of(finished)["counts"]["created"] == 1

        walls = await _walls_jobs(db_session)
        assert len(walls) == 2
        recompute = walls[1]
        assert recompute.id != first.id and recompute.status is JobStatus.QUEUED
        assert recompute.payload["zones_count"] == 1 and recompute.payload["zones_sha256"]
        assert recompute.payload["page_index"] == 0 and recompute.payload["view"] == 1

        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        # Повторный запуск авторазметки по тому же листу зон не создаёт и пересчёта не ставит.
        repeat = await cad_zones_auto._enqueue(
            db_session,
            parent=parent,
            page_index=0,
            view=1,
            dxf=cad_walls_service.view_has_dxf(parent, 0, 1) or {},
            params=cad_mep_service.load_params(settings),
            sequence=1,
        )
        await db_session.commit()
        again = await _run_zones_worker(db_session, fake_storage, settings, str(repeat.id))
        assert cad_service.result_of(again)["result_status"] == "zones_skipped_existing"
        assert len(await _walls_jobs(db_session)) == 2


async def test_recompute_after_auto_zones_is_queued_next_to_active_job_without_zones(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        await cad_walls_service.enqueue_after_convert(db_session, fake_storage, parent, settings)
        (zones_job,) = await cad_zones_auto.enqueue_after_convert(db_session, parent, settings)
        await db_session.commit()
        finished = await _run_zones_worker(db_session, fake_storage, settings, str(zones_job.id))
        assert finished.status is JobStatus.SUCCEEDED
        assert cad_service.result_of(finished)["counts"]["created"] == 1
        first, second = await _walls_jobs(db_session)
        assert first.status is JobStatus.QUEUED and first.payload["zones_sha256"] == ""
        assert second.status is JobStatus.QUEUED and second.payload["zones_count"] == 1
        assert second.created_at > first.created_at


async def test_recompute_after_auto_zones_is_skipped_when_active_job_has_same_zones(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _apartment_zone(api, project_id, revision_id)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (active,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        await db_session.commit()
        assert active.payload["zones_sha256"]
        queued = await cad_walls_service.schedule_after_auto_zones(
            db_session, fake_storage, parent=parent, page_index=0, view=1, settings=settings
        )
        assert queued is None
        assert len(await _walls_jobs(db_session)) == 1


# ------------------------------------------------------------------ зона вида (--view-zone)

VIEW_BBOX_MM = [0, 0, 3527.78, 7055.56]
# Кадр родителя: начало (10, 20) pt, 35.2778 мм/pt; y_pt = 20 - y_mm / k, поэтому верх — по y1.
VIEW_ZONE_PT = (10.0, -180.0, 110.0, 20.0)


def _set_preview_bbox(storage: FakeObjectStorage, bbox: list[float] | None) -> None:
    key = next(k for k in storage.objects if k.endswith(f"{FOLDER}/preview.json"))
    storage.objects[key] = json.dumps({} if bbox is None else {"bbox": bbox}).encode()


def _argv_of(settings: Settings, tmp_path: Path, view_zone: tuple[float, ...] | None) -> list[str]:
    return walls_handler._argv(
        settings,
        dxf=tmp_path / "a.dxf",
        params=tmp_path / "v1.json",
        out=tmp_path / "walls.json",
        pdf=tmp_path / "source.pdf",
        page_index=0,
        view_zone=None
        if view_zone is None
        else (view_zone[0], view_zone[1], view_zone[2], view_zone[3]),
    )


def test_view_zone_formula_is_inverse_of_frame() -> None:
    zone = cad_walls_zones.view_zone_pt(
        [100.0, 200.0, 400.0, 500.0], origin_pt=(10.0, 20.0), mm_per_pdf_point=10.0
    )
    assert zone == (20.0, -30.0, 50.0, 0.0)
    for bad in (None, [1, 2, 3], [0, 0, 0, 5], ["a", 0, 1, 1], [0, 0, float("inf"), 1]):
        assert cad_walls_zones.view_zone_pt(bad, origin_pt=(0.0, 0.0), mm_per_pdf_point=1.0) is None
    assert cad_walls_zones.view_zone_pt([0, 0, 1, 1], origin_pt=None, mm_per_pdf_point=1.0) is None
    assert (
        cad_walls_zones.view_zone_pt([0, 0, 1, 1], origin_pt=(0.0, 0.0), mm_per_pdf_point=None)
        is None
    )


def test_argv_passes_view_zone_with_equals_form(settings: Settings, tmp_path: Path) -> None:
    argv = _argv_of(settings, tmp_path, (10.0, -180.004, 110.0, 20.0))
    assert argv[-1] == "--view-zone=10.0,-180.0,110.0,20.0"
    assert not any(a.startswith("--view-zone") for a in _argv_of(settings, tmp_path, None))


def test_view_zone_of_payload_is_validated() -> None:
    assert walls_handler._view_zone_of({"view_zone": [1, 2, 3, 4]}) == (1.0, 2.0, 3.0, 4.0)
    for bad in (None, [1, 2, 3], [3, 2, 1, 4], ["a", 2, 3, 4], "1,2,3,4"):
        assert walls_handler._view_zone_of({"view_zone": bad}) is None
    assert walls_handler._view_zone_of({}) is None


async def test_auto_enqueue_puts_view_zone_into_payload(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        _set_preview_bbox(fake_storage, VIEW_BBOX_MM)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert job.payload["view_zone"] == pytest.approx(list(VIEW_ZONE_PT), abs=0.01)
        assert job.payload["zones_count"] == 0 and "zones_warning" not in job.payload
        view_zone = walls_handler._view_zone_of(job.payload)
        assert view_zone is not None
        argv = _argv_of(settings, Path("/x"), view_zone)
        assert argv[-1] == "--view-zone=10.0,-180.0,110.0,20.0"


async def test_auto_enqueue_without_confirmed_frame_has_no_view_zone(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        _project, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        _set_preview_bbox(fake_storage, VIEW_BBOX_MM)
        scale = next(key for key in fake_storage.objects if key.endswith(f"{FOLDER}/scale.json"))
        del fake_storage.objects[scale]
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (job,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        assert "view_zone" not in job.payload
        assert walls_handler._view_zone_of(job.payload) is None
