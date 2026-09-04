"""Переходы состояний заданий.

Таблица переходов проверяется без базы: это чистая логика, и она не должна зависеть
от поднятой инфраструктуры.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import Job, Project
from app.services import jobs as jobs_service
from app.services import projects as projects_service

TERMINAL = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class TestTransitionTable:
    @pytest.mark.parametrize("status", TERMINAL)
    def test_terminal_states_have_no_exit(self, status: JobStatus) -> None:
        assert jobs_service.ALLOWED_TRANSITIONS[status] == frozenset()
        assert status.is_terminal

    def test_queued_cannot_jump_to_succeeded(self) -> None:
        # Успех без запуска означал бы, что работа не выполнялась.
        assert JobStatus.SUCCEEDED not in jobs_service.ALLOWED_TRANSITIONS[JobStatus.QUEUED]

    def test_every_status_has_a_rule(self) -> None:
        assert set(jobs_service.ALLOWED_TRANSITIONS) == set(JobStatus)


async def _project(session: AsyncSession, workspace_id: object) -> Project:
    return await projects_service.create_project(
        session, workspace_id=workspace_id, name="Проект для заданий"
    )


class TestJobLifecycle:
    async def test_full_successful_run(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)

        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )
        assert job.status is JobStatus.QUEUED
        assert job.started_at is None

        await jobs_service.start(db_session, job=job, stage="unpack")
        assert job.status is JobStatus.RUNNING
        assert job.started_at is not None

        await jobs_service.report_progress(db_session, job=job, progress=0.5, stage="regions")
        assert job.progress == pytest.approx(0.5)
        assert job.stage == "regions"

        await jobs_service.succeed(db_session, job=job, payload={"sheets": 77})
        assert job.status is JobStatus.SUCCEEDED
        assert job.progress == pytest.approx(1.0)
        assert job.finished_at is not None
        assert job.payload["sheets"] == 77

    async def test_finished_job_cannot_restart(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )
        await jobs_service.start(db_session, job=job)
        await jobs_service.fail(db_session, job=job, error_code="ARCHIVE_LIMIT_EXCEEDED")

        with pytest.raises(DomainError):
            await jobs_service.start(db_session, job=job)

    async def test_progress_rejected_for_queued_job(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )

        with pytest.raises(DomainError):
            await jobs_service.report_progress(db_session, job=job, progress=0.3)

    async def test_progress_is_clamped(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )
        await jobs_service.start(db_session, job=job)

        await jobs_service.report_progress(db_session, job=job, progress=5.0)

        # Ограничение базы (0..1) не должно срабатывать: сервис приводит значение сам.
        assert job.progress == pytest.approx(1.0)

    async def test_error_message_is_truncated(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )
        await jobs_service.start(db_session, job=job)

        await jobs_service.fail(
            db_session, job=job, error_code="IMPORT_FAILED", error_message="я" * 900
        )

        assert job.error_message is not None
        assert len(job.error_message) == 500


class TestIdempotency:
    async def test_repeat_with_same_key_returns_same_job(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)

        first = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="package-sha256-abc",
        )
        second = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="package-sha256-abc",
        )

        assert first.id == second.id
        assert await jobs_service.count_jobs(db_session, project_id=project.id) == 1

    async def test_different_keys_create_separate_jobs(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)

        await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="first",
        )
        await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="second",
        )

        assert await jobs_service.count_jobs(db_session, project_id=project.id) == 2


class TestJobIsolation:
    async def test_job_of_another_workspace_is_invisible(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        import uuid

        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )

        found = await jobs_service.get_job(db_session, workspace_id=uuid.uuid4(), job_id=job.id)

        assert found is None


def test_job_model_defaults() -> None:
    """Задание создаётся в очереди и без отметок времени выполнения."""
    job = Job(job_type=JobType.LEGACY_IMPORT)

    assert job.started_at is None
    assert job.finished_at is None
