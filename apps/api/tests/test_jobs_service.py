"""Переходы состояний заданий.

Таблица переходов проверяется без базы: это чистая логика, и она не должна зависеть
от поднятой инфраструктуры.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobScope, JobStatus, JobType
from app.errors import DomainError
from app.models import Job, Project, Workspace
from app.services import jobs as jobs_service
from app.services import projects as projects_service

# Окончательные состояния: выхода нет и не появится. Отказ сюда больше не входит —
# у него есть ровно один выход, и только через повтор (см. ниже).
FINAL = (JobStatus.SUCCEEDED, JobStatus.CANCELLED)


class TestTransitionTable:
    @pytest.mark.parametrize("status", FINAL)
    def test_final_states_have_no_exit(self, status: JobStatus) -> None:
        """Успех и отмена окончательны: переделать их нельзя, можно только начать заново."""
        assert jobs_service.ALLOWED_TRANSITIONS[status] == frozenset()
        assert status.is_terminal

    def test_failure_leads_back_to_the_queue_and_nowhere_else(self) -> None:
        """У отказа один выход — обратно в очередь, и только повтором.

        Это появилось вместе с отдельным исполнителем. Прямой переход `failed → running`
        означал бы, что задание «продолжили» — а его надо начать сначала, с новой попытки.
        """
        assert jobs_service.ALLOWED_TRANSITIONS[JobStatus.FAILED] == frozenset({JobStatus.QUEUED})
        assert JobStatus.FAILED.is_terminal

    def test_running_returns_to_the_queue_when_abandoned(self) -> None:
        """Брошенное задание возвращается в очередь, иначе оно висит «выполняется» вечно."""
        assert JobStatus.QUEUED in jobs_service.ALLOWED_TRANSITIONS[JobStatus.RUNNING]

    def test_only_circumstantial_failures_are_retryable(self) -> None:
        """Битый архив останется битым: предлагать для него повтор — обещать невозможное."""
        retryable = jobs_service.RETRYABLE_ERROR_CODES
        assert "STORAGE_UNAVAILABLE" in retryable
        assert "JOB_LEASE_LOST" in retryable
        assert "ARCHIVE_UNSAFE_PATH" not in retryable
        assert "LEGACY_BLOCKS_INVALID" not in retryable
        assert "CORRUPT_ARCHIVE" not in retryable

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
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
        )
        assert job.status is JobStatus.QUEUED
        assert job.started_at is None

        await jobs_service.start(db_session, job=job, stage="unpack")
        assert job.status is JobStatus.RUNNING
        assert job.started_at is not None

        # claim() уже перевёл в running — повторный start только выставляет стадию.
        await jobs_service.start(db_session, job=job, stage="regions")
        assert job.status is JobStatus.RUNNING
        assert job.stage == "regions"

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
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
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
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
        )

        with pytest.raises(DomainError):
            await jobs_service.report_progress(db_session, job=job, progress=0.3)

    async def test_progress_is_clamped(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
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
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
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
            workspace_id=workspace_id,
            project_id=project.id,
            idempotency_key="package-sha256-abc",
        )
        second = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
            idempotency_key="package-sha256-abc",
        )

        assert first.id == second.id
        assert (
            await jobs_service.count_jobs(
                db_session, workspace_id=workspace_id, project_id=project.id
            )
            == 1
        )

    async def test_different_keys_create_separate_jobs(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)

        await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
            idempotency_key="first",
        )
        await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
            idempotency_key="second",
        )

        assert (
            await jobs_service.count_jobs(
                db_session, workspace_id=workspace_id, project_id=project.id
            )
            == 2
        )


class TestJobIsolation:
    async def test_job_of_another_workspace_is_invisible(
        self, db_session: AsyncSession, workspace_id: object
    ) -> None:
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
        )

        found = await jobs_service.get_job(db_session, workspace_id=uuid.uuid4(), job_id=job.id)

        assert found is None

    async def test_system_job_is_invisible_to_every_workspace(
        self, db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
    ) -> None:
        """Общесистемное задание не принадлежит никому — значит, не видно никому.

        До явной области видимости пустой `project_id` означал обратное: такое задание
        попадало в любое рабочее пространство.
        """
        job = await jobs_service.enqueue_system(db_session, job_type=JobType.LEGACY_IMPORT)

        assert job.scope is JobScope.SYSTEM
        assert (
            await jobs_service.get_job(db_session, workspace_id=workspace_id, job_id=job.id) is None
        )
        assert (
            await jobs_service.get_job(db_session, workspace_id=second_workspace.id, job_id=job.id)
            is None
        )

    async def test_system_job_is_reachable_only_through_its_own_path(
        self, db_session: AsyncSession
    ) -> None:
        job = await jobs_service.enqueue_system(db_session, job_type=JobType.LEGACY_IMPORT)

        found = await jobs_service.get_system_job(db_session, job_id=job.id)

        assert found is not None
        assert found.id == job.id

    async def test_system_path_does_not_return_a_workspace_job(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Симметрия: путь администратора не превращается в универсальную отмычку."""
        project = await _project(db_session, workspace_id)
        job = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
        )

        assert await jobs_service.get_system_job(db_session, job_id=job.id) is None

    async def test_workspace_job_without_project_belongs_to_its_workspace(
        self, db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
    ) -> None:
        """Задание пространства без проекта видно своим и не видно чужим."""
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, workspace_id=workspace_id
        )

        assert job.scope is JobScope.WORKSPACE
        found = await jobs_service.get_job(db_session, workspace_id=workspace_id, job_id=job.id)
        assert found is not None
        assert (
            await jobs_service.get_job(db_session, workspace_id=second_workspace.id, job_id=job.id)
            is None
        )


class TestScopeInvariants:
    async def test_enqueue_rejects_a_project_from_another_workspace(
        self, db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
    ) -> None:
        project = await _project(db_session, workspace_id)

        with pytest.raises(DomainError):
            await jobs_service.enqueue(
                db_session,
                job_type=JobType.LEGACY_IMPORT,
                workspace_id=second_workspace.id,
                project_id=project.id,
            )

    async def test_idempotency_key_does_not_cross_the_boundary(
        self, db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
    ) -> None:
        """Ключ уникален на всю установку — но чужое задание по нему не отдаётся."""
        project = await _project(db_session, workspace_id)
        await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=workspace_id,
            project_id=project.id,
            idempotency_key="shared-key",
        )

        with pytest.raises(DomainError):
            await jobs_service.enqueue(
                db_session,
                job_type=JobType.LEGACY_IMPORT,
                workspace_id=second_workspace.id,
                idempotency_key="shared-key",
            )

    async def test_database_rejects_a_project_job_without_a_workspace(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Проверяет, что CHECK доехал до схемы, а не остался в модели."""
        project = await _project(db_session, workspace_id)
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into jobs (id, project_id, workspace_id, job_type, status,"
                    " attempt, max_attempts, payload, created_at, updated_at)"
                    " values (:id, :project_id, null, 'legacy_import', 'queued',"
                    " 0, 1, '{}', now(), now())"
                ),
                {"id": uuid.uuid4(), "project_id": project.id},
            )
        await db_session.rollback()

    async def test_database_rejects_a_job_whose_workspace_differs_from_its_project(
        self, db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
    ) -> None:
        """Составной внешний ключ держит инвариант и при записи мимо сервиса."""
        project = await _project(db_session, workspace_id)
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into jobs (id, project_id, workspace_id, job_type, status,"
                    " attempt, max_attempts, payload, created_at, updated_at)"
                    " values (:id, :project_id, :workspace_id, 'legacy_import', 'queued',"
                    " 0, 1, '{}', now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "project_id": project.id,
                    "workspace_id": second_workspace.id,
                },
            )
        await db_session.rollback()


def test_job_model_defaults() -> None:
    """Задание создаётся в очереди и без отметок времени выполнения."""
    job = Job(job_type=JobType.LEGACY_IMPORT)

    assert job.started_at is None
    assert job.finished_at is None
