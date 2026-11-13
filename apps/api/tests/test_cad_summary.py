"""Сводка распознавания CAD проекта: листы последних открываемых ревизий по состоянию конвейера."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_pipeline import CadPipelineSheetRead
from app.domain import DocumentKind, GeometryStatus, JobStatus, JobType
from app.models import Document, DocumentRevision, Job, Project, Sheet, Workspace
from app.services.cad_summary import sheet_state
from tests.conftest import FakeObjectStorage, make_context
from tests.doc_questions_support import add_pdf, make_project
from tests.test_cad_queue import BASE, add_job, queue_settings


def summary_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/summary"


def add_sheets(session: AsyncSession, revision_id: uuid.UUID, labels: list[str]) -> None:
    for index, label in enumerate(labels):
        session.add(Sheet(revision_id=revision_id, page_index=index, page_label=label, rotation=0))


def convert_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    pages: list[int],
    status: JobStatus,
    minutes: int = 0,
) -> Job:
    """Конвертация страниц: у успешной в итоге по одному виду на страницу."""
    payload: dict[str, Any] = {"revision_id": str(revision_id), "params": {"pages": pages}}
    if status is JobStatus.SUCCEEDED:
        payload["cad_result"] = {
            "attempt": 1,
            "pages": [{"index": page, "views": [{"view": 0}]} for page in pages],
        }
    return add_job(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        status=status,
        minutes=minutes,
        job_type=JobType.CAD_PDF_CONVERT,
        payload=payload,
        attempt=1,
    )


def child_job(
    session: AsyncSession,
    *,
    parent: Job,
    job_type: JobType,
    page_index: int,
    status: JobStatus,
    minutes: int = 1,
) -> Job:
    assert parent.workspace_id is not None
    return add_job(
        session,
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        status=status,
        minutes=minutes,
        job_type=job_type,
        payload={
            "revision_id": parent.payload["revision_id"],
            "parent_job_id": str(parent.id),
            "page_index": page_index,
            "view": 0,
            "cad_result": {"attempt": 1},
        },
        attempt=1,
    )


def test_sheet_state_ignores_the_optional_floor3d_stage() -> None:
    def sheet(**stages: Any) -> CadPipelineSheetRead:
        return CadPipelineSheetRead.model_validate(
            {
                "page_index": 0,
                "page_label": None,
                "title": None,
                "is_plan": True,
                "calibrated": False,
                "convert": None,
                "scale_source": None,
                "views": [
                    {
                        "page": 0,
                        "view": 0,
                        "has_dxf": True,
                        "walls": None,
                        "zones": None,
                        "zones_count": 0,
                        "approved": False,
                        "routes": None,
                        "routes_accepted": False,
                        "floor3d": None,
                        **stages,
                    }
                ],
            }
        )

    def stage(status: str, result_status: str | None = None) -> dict[str, Any]:
        return {
            "job_id": str(uuid.uuid4()),
            "job_type": "cad_walls",
            "status": status,
            "progress": None,
            "stage": None,
            "result_status": result_status,
            "error_code": None,
            "created_at": BASE.isoformat(),
            "finished_at": None,
        }

    assert sheet_state(sheet()) == "idle"
    assert sheet_state(sheet(walls=stage("succeeded"))) == "done"
    assert sheet_state(sheet(walls=stage("succeeded", "failed"))) == "failed"
    assert sheet_state(sheet(walls=stage("cancelled"))) == "failed"
    assert sheet_state(sheet(walls=stage("failed"), zones=stage("running"))) == "running"
    assert sheet_state(sheet(walls=stage("succeeded"), floor3d=stage("failed"))) == "done"
    assert sheet_state(sheet(floor3d=stage("running"))) == "idle"


async def test_summary_is_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=queue_settings(flag=False)) as api:
        response = await api.get(summary_url(str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_summary_of_a_missing_project_is_404(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        assert (await api.get(summary_url(str(uuid.uuid4())))).status_code == 404


async def test_summary_of_another_workspace_project_is_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    stranger = Project(workspace_id=second_workspace.id, name="Чужой")
    db_session.add(stranger)
    await db_session.commit()
    async with build_api(make_context(), settings=queue_settings()) as api:
        assert (await api.get(summary_url(str(stranger.id)))).status_code == 404


async def test_empty_project_summary_is_zeros(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        assert (await api.get(summary_url(project_id))).json() == {
            "sheets_total": 0,
            "sheets_done": 0,
            "sheets_running": 0,
            "sheets_failed": 0,
            "sheets_idle": 0,
            "documents_total": 0,
        }


async def test_summary_counts_sheets_of_the_latest_openable_revisions(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        # Старая ревизия документа и её работа в сводку не входят.
        old = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, old.id, ["План 1 этажа"])
        convert_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            revision_id=old.id,
            pages=[0],
            status=JobStatus.FAILED,
        )
        payload = b"%PDF-1.7 second"
        latest = DocumentRevision(
            document_id=old.document_id,
            source_filename="АР План.pdf",
            source_mime="application/pdf",
            source_size=len(payload),
            source_sha256=hashlib.sha256(payload).hexdigest(),
            storage_key=f"test/{uuid.uuid4()}",
            created_at=BASE + timedelta(days=1),
        )
        db_session.add(latest)
        await db_session.flush()
        # План без работы (idle) и пять листов в разных состояниях.
        add_sheets(
            db_session, latest.id, ["Лист 1", "Лист 2", "Лист 3", "Лист 4", "План 5", "Лист 6"]
        )
        jobs = {
            index: convert_job(
                db_session,
                workspace_id=workspace_id,
                project_id=pid,
                revision_id=latest.id,
                pages=[index],
                status=status,
            )
            for index, status in (
                (0, JobStatus.SUCCEEDED),
                (1, JobStatus.SUCCEEDED),
                (2, JobStatus.SUCCEEDED),
                (3, JobStatus.QUEUED),
                (5, JobStatus.FAILED),
            )
        }
        # Идентификаторы заданий-родителей появляются при записи.
        await db_session.flush()
        child_job(
            db_session,
            parent=jobs[0],
            job_type=JobType.CAD_WALLS,
            page_index=0,
            status=JobStatus.SUCCEEDED,
        )
        # Необязательный 3D DXF с отказом листа не портит.
        child_job(
            db_session,
            parent=jobs[0],
            job_type=JobType.CAD_FLOOR3D_DXF,
            page_index=0,
            status=JobStatus.FAILED,
        )
        child_job(
            db_session,
            parent=jobs[1],
            job_type=JobType.CAD_WALLS,
            page_index=1,
            status=JobStatus.RUNNING,
        )
        child_job(
            db_session,
            parent=jobs[2],
            job_type=JobType.CAD_WALLS,
            page_index=2,
            status=JobStatus.FAILED,
        )
        # Второй документ: один план без работы. Третий: геометрия не готова. Четвёртый: не PDF.
        other = await add_pdf(db_session, fake_storage, project_id, "КР План.pdf")
        add_sheets(db_session, other.id, ["План подвала"])
        broken = await add_pdf(db_session, fake_storage, project_id, "ОВ План.pdf")
        add_sheets(db_session, broken.id, ["План 1"])
        broken.geometry_status = GeometryStatus.FAILED
        package = await add_pdf(db_session, fake_storage, project_id, "Пакет.zip")
        add_sheets(db_session, package.id, ["План 2"])
        package_document = await db_session.get(Document, package.document_id)
        assert package_document is not None
        package_document.document_kind = DocumentKind.RECOGNIZED_PACKAGE
        await db_session.commit()

        body = (await api.get(summary_url(project_id))).json()
        assert body == {
            "sheets_total": 7,
            "sheets_done": 1,
            "sheets_running": 2,
            "sheets_failed": 2,
            "sheets_idle": 2,
            "documents_total": 2,
        }
        assert body["sheets_total"] == sum(
            body[key] for key in ("sheets_done", "sheets_running", "sheets_failed", "sheets_idle")
        )


async def _pipeline_sheet(
    api: AsyncClient, project_id: str, revision_id: uuid.UUID
) -> dict[str, Any]:
    response = await api.get(f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/pipeline")
    assert response.status_code == 200, response.text
    (sheet,) = response.json()["sheets"]
    assert isinstance(sheet, dict)
    return sheet


async def test_pipeline_keeps_the_ready_run_while_a_newer_one_is_not_ready(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    """Показывается самое новое готовое задание, более новое, но не готовое — `update`."""
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["План 1 этажа"])
        ready = convert_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            revision_id=revision.id,
            pages=[0],
            status=JobStatus.SUCCEEDED,
        )
        await db_session.flush()
        child_job(
            db_session,
            parent=ready,
            job_type=JobType.CAD_WALLS,
            page_index=0,
            status=JobStatus.SUCCEEDED,
        )
        newer = convert_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            revision_id=revision.id,
            pages=[0],
            status=JobStatus.QUEUED,
            minutes=10,
        )
        await db_session.commit()

        for status in (JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED):
            newer.status = status
            await db_session.commit()
            sheet = await _pipeline_sheet(api, project_id, revision.id)
            assert sheet["convert"]["job_id"] == str(ready.id)
            assert sheet["update"]["job_id"] == str(newer.id)
            assert sheet["update"]["status"] == status.value
            (view,) = sheet["views"]
            assert view["walls"]["status"] == "succeeded"

        # Обновление завершилось с видами: оно и показывается, обновления нет.
        newer.status = JobStatus.SUCCEEDED
        newer.payload = {
            **newer.payload,
            "cad_result": {"attempt": 1, "pages": [{"index": 0, "views": [{"view": 0}]}]},
        }
        await db_session.commit()
        sheet = await _pipeline_sheet(api, project_id, revision.id)
        assert sheet["convert"]["job_id"] == str(newer.id)
        assert sheet["update"] is None
        assert sheet["views"][0]["walls"] is None


async def test_pipeline_shows_the_only_queued_run_without_update(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["План 1 этажа"])
        only = convert_job(
            db_session,
            workspace_id=workspace_id,
            project_id=uuid.UUID(project_id),
            revision_id=revision.id,
            pages=[0],
            status=JobStatus.QUEUED,
        )
        await db_session.commit()
        sheet = await _pipeline_sheet(api, project_id, revision.id)
        assert sheet["convert"]["job_id"] == str(only.id)
        assert sheet["update"] is None
        assert sheet["views"] == []
