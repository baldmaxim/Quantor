"""Совмещение планов с уровнем (С3): задание, подтверждение, проверка в каркасе.

Только синтетика: задания CAD и их артефакты (масштаб, проверки вида, walls.json с осями) пишутся
в базу и поддельное хранилище напрямую, паспорта - в базу.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType, Role
from app.main import create_app
from app.models import DocumentRevision, Job, PlanAlignment, Project
from app.services import cad as cad_service
from app.services import jobs as jobs_service
from app.services.plan_alignments import NO_CAD
from app.worker.registry import handler_for, supported_types
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import add_passport, add_pdf, doc_settings, make_project

AR_PDF = "АР планы.pdf"
IOS_PDF = "ИОС2 планы.pdf"
LONELY_PDF = "АР секция 2.pdf"
VERTICAL = {"1": 0.0, "2": 6000.0, "3": 12000.0}
HORIZONTAL = {"А": 0.0, "Б": 6000.0}


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/plan-alignments{tail}"


async def _put(storage: FakeObjectStorage, key: str, data: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(data).encode()
    await storage.put_bytes(key, raw, content_type="application/json")
    return {"key": key, "size": len(raw), "sha256": "0" * 64}


async def _cad_view(
    session: AsyncSession,
    storage: FakeObjectStorage,
    project_id: str,
    revision: DocumentRevision,
    *,
    dx: float,
    dy: float,
) -> None:
    """Успешные `cad_pdf_convert` и `cad_walls` вида 1 страницы 0 с осями, сдвинутыми на (dx, dy).

    Кадр: начало координат DXF в точке (0, 0) страницы, 1 мм на точку PDF, калибровка человеком;
    вертикаль x = pos, горизонталь y = -pos.
    """
    project = await session.get(Project, uuid.UUID(project_id))
    assert project is not None
    convert = Job(
        job_type=JobType.CAD_PDF_CONVERT,
        status=JobStatus.SUCCEEDED,
        workspace_id=project.workspace_id,
        project_id=project.id,
        attempt=1,
        max_attempts=1,
        payload={"revision_id": str(revision.id)},
    )
    session.add(convert)
    await session.flush()
    folder = cad_service.view_folder(0, 1)
    artifacts = []
    files: dict[str, dict[str, Any]] = {
        "plan_candidates.dxf": {},
        "scale.json": {
            "status": "needs_review",
            "source": "operator_calibration",
            "operator_mm_per_pt": 1.0,
        },
        "cad_checks.json": {"units": "mm", "origin_pdf_display_pt": [0, 0]},
    }
    for name, data in files.items():
        full = f"{folder}/{name}"
        key = cad_service.artifact_storage_key(revision.id, convert.id, 1, full)
        artifacts.append({"name": full, **await _put(storage, key, data)})
    convert.payload = {
        "revision_id": str(revision.id),
        "cad_result": {
            "attempt": 1,
            "pages": [{"index": 0, "views": [{"view": 1}]}],
            "artifacts": artifacts,
        },
    }
    walls = Job(
        job_type=JobType.CAD_WALLS,
        status=JobStatus.SUCCEEDED,
        workspace_id=project.workspace_id,
        project_id=project.id,
        attempt=1,
        max_attempts=1,
        payload={},
    )
    session.add(walls)
    await session.flush()
    items = [
        {"label": label, "orient": "vertical", "pos_pt": x - dx} for label, x in VERTICAL.items()
    ] + [
        {"label": label, "orient": "horizontal", "pos_pt": -(y - dy)}
        for label, y in HORIZONTAL.items()
    ]
    name = f"{folder}/walls.json"
    key = cad_service.artifact_storage_key(revision.id, walls.id, 1, name)
    artifact = {"name": name, **await _put(storage, key, {"axes": {"items": items}})}
    walls.payload = {
        "revision_id": str(revision.id),
        "parent_job_id": str(convert.id),
        "page_index": 0,
        "view": 1,
        "cad_result": {"attempt": 1, "artifacts": [artifact]},
    }
    await session.commit()


async def _project(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage
) -> tuple[str, DocumentRevision, DocumentRevision]:
    """Секция 1: план АР (эталон) и план ИОС2, сдвинутый на (100, -250); секция 2: план без CAD."""
    project_id = await make_project(api)
    ar = await add_pdf(session, storage, project_id, AR_PDF)
    ios = await add_pdf(session, storage, project_id, IOS_PDF)
    lonely = await add_pdf(session, storage, project_id, LONELY_PDF)
    for revision, mark, section in ((ar, "АР", "1"), (ios, "ИОС2", "1"), (lonely, "АР", "2")):
        await add_passport(
            session,
            project_id,
            revision,
            0,
            section_mark=mark,
            sheet_kind="floor_plan",
            building="1",
            section=section,
            status="confirmed",
        )
    await _cad_view(session, storage, project_id, ar, dx=0.0, dy=0.0)
    await _cad_view(session, storage, project_id, ios, dx=100.0, dy=-250.0)
    return project_id, ar, ios


async def _run(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage, project_id: str
) -> Job:
    response = await api.post(_url(project_id, "/run"))
    assert response.status_code == 202, response.text
    assert response.json()["job_type"] == "plan_align"
    job = await jobs_service.claim(
        session, worker_id="plan-align-test", job_types=["plan_align"], lease_seconds=600
    )
    await session.commit()
    assert job is not None and str(job.id) == response.json()["id"]
    handler = handler_for(job.job_type)
    assert handler is not None
    job = await handler(session, job, storage, clean_settings())
    await session.commit()
    return job


def _check(body: dict[str, Any], section: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = body["checks"]
    [item] = [c for c in checks if c["code"] == "plans_aligned" and c["section"] == section]
    return item


def test_routes_are_in_openapi_and_job_is_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/plan-alignments"
    assert set(paths[base]) == {"get"}
    assert set(paths[f"{base}/run"]) == {"post"}
    assert set(paths[f"{base}/bulk-status"]) == {"post"}
    assert JobType.PLAN_ALIGN.value in supported_types()


async def test_routes_are_closed_by_flag(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=doc_settings(flag=False)) as api:
        project_id = str(uuid.uuid4())
        responses = [
            await api.get(_url(project_id)),
            await api.post(_url(project_id, "/run")),
            await api.post(
                _url(project_id, "/bulk-status"),
                json={"ids": [str(uuid.uuid4())], "status": "confirmed"},
            ),
        ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_align_confirm_and_check(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, ar, ios = await _project(api, db_session, fake_storage)
        before = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        assert before["versions"]["align_checks"] == "consistency.checks.align.v1"
        [idle] = [c for c in before["checks"] if c["code"] == "plans_aligned"]
        assert idle["status"] == "not_run" and "запустите совмещение" in idle["message"]

        job = await _run(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        assert (job.payload["plans"], job.payload["views"], job.payload["without_cad"]) == (3, 3, 1)
        assert (job.payload["aligned"], job.payload["not_run"]) == (2, 1)

        view = (await api.get(_url(project_id))).json()
        assert view["last_run"]["status"] == "succeeded"
        assert view["params"] == {"axis_agree_mm": 150.0, "residual_check_mm": 50.0}
        by_file = {row["file_name"]: row for row in view["alignments"]}
        reference, aligned, lonely = by_file[AR_PDF], by_file[IOS_PDF], by_file[LONELY_PDF]
        assert reference["result"] == "reference" and reference["reference_id"] == reference["id"]
        assert reference["revision_id"] == str(ar.id) and reference["view"] == 1
        assert reference["scale_source"] == "calibration"
        assert reference["mm_per_pdf_point"] == 1.0 and reference["origin_pt"] == [0.0, 0.0]
        assert aligned["result"] == "aligned" and aligned["reference_id"] == reference["id"]
        assert aligned["revision_id"] == str(ios.id)
        assert (aligned["rotation_deg"], aligned["dx_mm"], aligned["dy_mm"]) == (0, 100.0, -250.0)
        assert aligned["axes"] == ["1", "2", "3", "А", "Б"]
        assert aligned["residual_rms_mm"] == 0.0 and aligned["reasons"] == []
        assert lonely["result"] == "not_run" and lonely["view"] == 0
        assert lonely["reasons"] == [NO_CAD] and lonely["cad_job_id"] is None

        pending = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        assert _check(pending, "1")["status"] == "not_run"
        assert _check(pending, "2")["status"] == "mismatch"
        assert _check(pending, "2")["refs"][0]["kind"] == "alignment"

        ids = [reference["id"], aligned["id"]]
        confirmed = await api.post(
            _url(project_id, "/bulk-status"), json={"ids": ids, "status": "confirmed"}
        )
        assert confirmed.status_code == 200 and confirmed.json() == {"updated": 2}
        body = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        assert _check(body, "1")["status"] == "match"
        assert "совмещено планов - 2, невязка до 0 мм" in _check(body, "1")["message"]

        # Повторный запуск: подтверждённые остаются, кандидат без CAD заменяется новым.
        await _run(api, db_session, fake_storage, project_id)
        rows = (await db_session.scalars(select(PlanAlignment))).all()
        kept = {str(row.id) for row in rows if row.status == "confirmed"}
        assert kept == set(ids)
        [fresh] = [row for row in rows if row.status == "candidate"]
        assert str(fresh.id) != lonely["id"] and fresh.result == "not_run"


async def test_bulk_status_foreign_id_and_viewer(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _, _ = await _project(api, db_session, fake_storage)
        await _run(api, db_session, fake_storage, project_id)
        row = (await api.get(_url(project_id))).json()["alignments"][0]
        foreign = await api.post(
            _url(project_id, "/bulk-status"),
            json={"ids": [row["id"], str(uuid.uuid4())], "status": "confirmed"},
        )
        assert foreign.status_code == 404
        stored = await db_session.get(PlanAlignment, uuid.UUID(row["id"]))
        assert stored is not None
        await db_session.refresh(stored)
        assert stored.status == "candidate"

    async with build_api(make_context(Role.VIEWER), settings=doc_settings()) as viewer:
        assert (await viewer.get(_url(project_id))).status_code == 200
        assert (await viewer.post(_url(project_id, "/run"))).status_code == 403
