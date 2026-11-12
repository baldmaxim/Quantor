"""Очередь CAD проекта: порядок, `ahead` с учётом чужих пространств, окно завершённых, доступ."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import Job, Project, Workspace
from app.services.cad_queue import QUEUE_JOB_TYPES
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import add_pdf, make_project

BASE = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def queue_settings(*, flag: bool = True) -> Settings:
    return clean_settings(environment="test", feature_flags="cad.export=true" if flag else "")


def queue_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/queue"


def add_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    status: JobStatus,
    minutes: int = 0,
    job_type: JobType = JobType.CAD_PDF_CONVERT,
    payload: dict[str, Any] | None = None,
    **fields: Any,
) -> Job:
    """Задание с заданным временем постановки (`BASE` + minutes)."""
    moment = BASE + timedelta(minutes=minutes)
    job = Job(
        workspace_id=workspace_id,
        project_id=project_id,
        job_type=job_type,
        status=status,
        payload=payload or {},
        created_at=moment,
        updated_at=moment,
        available_at=moment,
        max_attempts=3,
        **fields,
    )
    session.add(job)
    return job


def test_queue_types_match_the_cad_worker() -> None:
    assert set(QUEUE_JOB_TYPES) == set(HANDLERS)


async def test_queue_is_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=queue_settings(flag=False)) as api:
        response = await api.get(queue_url(str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_queue_of_a_missing_project_is_404(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        assert (await api.get(queue_url(str(uuid.uuid4())))).status_code == 404


async def test_queue_of_another_workspace_project_is_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    stranger = Project(workspace_id=second_workspace.id, name="Чужой")
    db_session.add(stranger)
    await db_session.commit()
    async with build_api(make_context(), settings=queue_settings()) as api:
        assert (await api.get(queue_url(str(stranger.id)))).status_code == 404


async def test_empty_queue_has_totals_only(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        body = (await api.get(queue_url(project_id))).json()
        assert body == {"items": [], "running_total": 0, "queued_total": 0}


async def test_queue_order_ahead_and_foreign_jobs(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        stranger = Project(workspace_id=second_workspace.id, name="Чужой")
        db_session.add(stranger)
        await db_session.flush()
        mine = {"revision_id": str(revision.id)}

        # Чужие: одно выполняется и два ждут (раньше и позже моих).
        add_job(
            db_session,
            workspace_id=second_workspace.id,
            project_id=stranger.id,
            status=JobStatus.RUNNING,
            minutes=-10,
            started_at=BASE - timedelta(minutes=9),
        )
        add_job(
            db_session,
            workspace_id=second_workspace.id,
            project_id=stranger.id,
            status=JobStatus.QUEUED,
            minutes=1,
        )
        add_job(
            db_session,
            workspace_id=second_workspace.id,
            project_id=stranger.id,
            status=JobStatus.QUEUED,
            minutes=50,
        )
        # Не CAD: в счёт не идёт.
        add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.QUEUED,
            job_type=JobType.PDF_GEOMETRY_EXTRACT,
            minutes=-20,
        )
        # Мои: ждут (позже поставленное создано раньше по кругу), одно идёт.
        later = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.QUEUED,
            job_type=JobType.CAD_WALLS,
            minutes=5,
            payload={**mine, "page_index": 3},
        )
        first = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.QUEUED,
            minutes=2,
            payload={**mine, "params": {"pages": [0, 4]}},
        )
        running = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.RUNNING,
            job_type=JobType.CAD_SECTIONS,
            minutes=-5,
            started_at=BASE - timedelta(minutes=4),
            attempt=2,
            payload={**mine, "page_indexes": [7]},
        )
        await db_session.commit()

        body = (await api.get(queue_url(project_id))).json()
        assert (body["running_total"], body["queued_total"]) == (2, 4)
        items = body["items"]
        assert [item["job_id"] for item in items] == [
            str(running.id),
            str(first.id),
            str(later.id),
        ]
        run_item, first_item, later_item = items
        assert (run_item["status"], run_item["ahead"]) == ("running", None)
        assert (run_item["attempt"], run_item["max_attempts"]) == (2, 3)
        assert run_item["pages"] == [7] and run_item["job_type"] == "cad_sections"
        assert run_item["document_name"] == "АР План.pdf"
        assert run_item["revision_id"] == str(revision.id)
        assert run_item["document_id"] is not None
        # Перед первым: два выполняющихся (мой и чужой) и чужое queued на минуте 1.
        assert first_item["ahead"] == 3 and first_item["pages"] == [0, 4]
        # Перед вторым: те же и моё на минуте 2.
        assert later_item["ahead"] == 4 and later_item["pages"] == [3]
        assert later_item["job_type"] == "cad_walls"


async def test_finished_window_and_limit(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        now = datetime.now(UTC)
        old = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.SUCCEEDED,
            finished_at=now - timedelta(hours=2),
        )
        failed = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.FAILED,
            finished_at=now - timedelta(minutes=1),
            error_code="CAD_ENGINE_FAILED",
        )
        succeeded = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.SUCCEEDED,
            finished_at=now - timedelta(minutes=2),
            error_code="IGNORED",
        )
        cancelled = add_job(
            db_session,
            workspace_id=workspace_id,
            project_id=pid,
            status=JobStatus.CANCELLED,
            finished_at=now - timedelta(minutes=3),
        )
        await db_session.commit()

        items = (await api.get(queue_url(project_id))).json()["items"]
        assert [item["job_id"] for item in items] == [
            str(failed.id),
            str(succeeded.id),
            str(cancelled.id),
        ]
        assert str(old.id) not in {item["job_id"] for item in items}
        assert items[0]["error_code"] == "CAD_ENGINE_FAILED"
        assert items[1]["error_code"] is None
        assert all(item["ahead"] is None for item in items)

        for minute in range(4, 16):
            add_job(
                db_session,
                workspace_id=workspace_id,
                project_id=pid,
                status=JobStatus.SUCCEEDED,
                finished_at=now - timedelta(minutes=minute),
            )
        await db_session.commit()
        items = (await api.get(queue_url(project_id))).json()["items"]
        assert len(items) == 10
