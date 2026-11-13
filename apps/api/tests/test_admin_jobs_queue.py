"""Очередь заданий администратора: список «как в очереди» и массовая отмена."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.permissions import Permission, permissions_for
from app.domain import JobStatus, JobType, Role
from app.models import Job, Workspace
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from tests.conftest import make_context

CANCEL_URL = "/api/v1/admin/jobs/cancel"


def _space_admin(workspace_id: uuid.UUID) -> AuthContext:
    """Не администратор платформы, но с доступом в административный контур.

    Контур целиком закрыт правом `system.admin`; роль пространства его не несёт, поэтому
    границу видимости по пространству проверяем контекстом, которому право выдано явно.
    """
    context = make_context(Role.WORKSPACE_ADMIN, workspace_id=workspace_id)
    return replace(context, permissions=context.permissions | {Permission.SYSTEM_ADMIN})


async def _job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    status: JobStatus = JobStatus.QUEUED,
    available_at: datetime | None = None,
) -> Job:
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.LEGACY_IMPORT,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    job.status = status
    if available_at is not None:
        job.available_at = available_at
    await session.commit()
    return job


async def _reload(session: AsyncSession, job: Job) -> JobStatus:
    await session.refresh(job)
    return job.status


async def test_cancel_selected_queued_running_and_skip_finished(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    project = await projects_service.create_project(db_session, workspace_id=workspace_id, name="П")
    await db_session.commit()
    queued = await _job(db_session, workspace_id=workspace_id, project_id=project.id)
    running = await _job(
        db_session, workspace_id=workspace_id, project_id=project.id, status=JobStatus.RUNNING
    )
    done = await _job(
        db_session, workspace_id=workspace_id, project_id=project.id, status=JobStatus.SUCCEEDED
    )

    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.post(
            CANCEL_URL, json={"job_ids": [str(queued.id), str(running.id), str(done.id)]}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] == 2
    assert body["skipped"] == 1
    assert set(body["cancelled_ids"]) == {str(queued.id), str(running.id)}
    assert await _reload(db_session, queued) is JobStatus.CANCELLED
    assert await _reload(db_session, running) is JobStatus.CANCELLED
    assert await _reload(db_session, done) is JobStatus.SUCCEEDED


async def test_cancel_all_active(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    project = await projects_service.create_project(db_session, workspace_id=workspace_id, name="П")
    await db_session.commit()
    first = await _job(db_session, workspace_id=workspace_id, project_id=project.id)
    second = await _job(
        db_session, workspace_id=workspace_id, project_id=project.id, status=JobStatus.RUNNING
    )
    failed = await _job(
        db_session, workspace_id=workspace_id, project_id=project.id, status=JobStatus.FAILED
    )

    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.post(CANCEL_URL, json={"all_active": True})

    assert response.status_code == 200
    assert response.json()["cancelled"] == 2
    assert response.json()["skipped"] == 0
    assert await _reload(db_session, first) is JobStatus.CANCELLED
    assert await _reload(db_session, second) is JobStatus.CANCELLED
    assert await _reload(db_session, failed) is JobStatus.FAILED


async def test_cancel_all_active_narrowed_to_project(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    mine = await projects_service.create_project(db_session, workspace_id=workspace_id, name="А")
    other = await projects_service.create_project(db_session, workspace_id=workspace_id, name="Б")
    await db_session.commit()
    in_mine = await _job(db_session, workspace_id=workspace_id, project_id=mine.id)
    in_other = await _job(db_session, workspace_id=workspace_id, project_id=other.id)

    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.post(
            CANCEL_URL, json={"all_active": True, "project_id": str(mine.id)}
        )

    assert response.json()["cancelled_ids"] == [str(in_mine.id)]
    assert await _reload(db_session, in_mine) is JobStatus.CANCELLED
    assert await _reload(db_session, in_other) is JobStatus.QUEUED


async def test_foreign_workspace_jobs_are_not_cancelled(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    foreign_project = await projects_service.create_project(
        db_session, workspace_id=second_workspace.id, name="Чужой"
    )
    await db_session.commit()
    foreign = await _job(
        db_session, workspace_id=second_workspace.id, project_id=foreign_project.id
    )

    async with build_api(_space_admin(workspace_id)) as client:
        by_id = await client.post(CANCEL_URL, json={"job_ids": [str(foreign.id)]})
        everything = await client.post(CANCEL_URL, json={"all_active": True})

    assert by_id.json() == {"cancelled": 0, "skipped": 1, "cancelled_ids": []}
    assert everything.json()["cancelled"] == 0
    assert await _reload(db_session, foreign) is JobStatus.QUEUED


async def test_cancel_requires_jobs_manage(
    build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    read_only = replace(
        context, permissions=permissions_for(Role.PLATFORM_ADMIN) - {Permission.JOBS_MANAGE}
    )
    async with build_api(read_only) as client:
        response = await client.post(CANCEL_URL, json={"all_active": True})

    assert response.status_code == 403


async def test_cancel_requires_exactly_one_selector(
    build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        both = await client.post(
            CANCEL_URL, json={"job_ids": [str(uuid.uuid4())], "all_active": True}
        )
        neither = await client.post(CANCEL_URL, json={})
        empty = await client.post(CANCEL_URL, json={"job_ids": []})

    assert both.status_code == 422
    assert neither.status_code == 422
    assert empty.status_code == 422


async def test_active_list_is_queue_ordered_with_project_name(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="Башня"
    )
    await db_session.commit()
    now = datetime.now(UTC)
    late = await _job(
        db_session,
        workspace_id=workspace_id,
        project_id=project.id,
        available_at=now + timedelta(minutes=5),
    )
    early = await _job(
        db_session,
        workspace_id=workspace_id,
        project_id=project.id,
        available_at=now - timedelta(minutes=5),
    )
    running = await _job(
        db_session,
        workspace_id=workspace_id,
        project_id=project.id,
        status=JobStatus.RUNNING,
        available_at=now + timedelta(minutes=30),
    )
    await _job(
        db_session, workspace_id=workspace_id, project_id=project.id, status=JobStatus.SUCCEEDED
    )

    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.get("/api/v1/admin/jobs", params={"active": True})

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(running.id), str(early.id), str(late.id)]
    assert body["total"] == 3
    assert {item["project_name"] for item in body["items"]} == {"Башня"}
