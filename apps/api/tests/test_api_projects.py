"""API проектов: создание, список, поиск, пагинация, границы доступа."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import DocumentKind, ProjectStatus
from app.models import Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service


class TestCreateProject:
    async def test_creates_project_with_russian_name(self, api: AsyncClient) -> None:
        response = await api.post("/api/v1/projects", json={"name": "ЖК «Северный», корпус 3"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "ЖК «Северный», корпус 3"
        assert body["status"] == ProjectStatus.ACTIVE.value
        uuid.UUID(body["id"])

    async def test_rejects_whitespace_only_name(self, api: AsyncClient) -> None:
        response = await api.post("/api/v1/projects", json={"name": "   "})

        assert response.status_code == 422

    async def test_rejects_missing_name(self, api: AsyncClient) -> None:
        response = await api.post("/api/v1/projects", json={})

        assert response.status_code == 422


class TestListProjects:
    async def test_empty_list_has_zero_total(self, api: AsyncClient) -> None:
        response = await api.get("/api/v1/projects")

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def test_pagination_splits_results(self, api: AsyncClient) -> None:
        for index in range(5):
            await api.post("/api/v1/projects", json={"name": f"Проект {index}"})

        first = (await api.get("/api/v1/projects", params={"limit": 2, "offset": 0})).json()
        second = (await api.get("/api/v1/projects", params={"limit": 2, "offset": 2})).json()

        assert first["total"] == 5
        assert len(first["items"]) == 2
        assert len(second["items"]) == 2
        assert {item["id"] for item in first["items"]}.isdisjoint(
            {item["id"] for item in second["items"]}
        )

    async def test_limit_above_maximum_is_rejected(self, api: AsyncClient) -> None:
        response = await api.get("/api/v1/projects", params={"limit": 100_000})

        assert response.status_code == 422

    async def test_search_matches_cyrillic_substring_case_insensitively(
        self, api: AsyncClient
    ) -> None:
        await api.post("/api/v1/projects", json={"name": "Школа на 1200 мест"})
        await api.post("/api/v1/projects", json={"name": "Котельная"})

        found = (await api.get("/api/v1/projects", params={"search": "школа"})).json()

        assert found["total"] == 1
        assert found["items"][0]["name"] == "Школа на 1200 мест"

    async def test_sort_by_name(self, api: AsyncClient) -> None:
        for name in ("Яблоко", "Берёза", "Астра"):
            await api.post("/api/v1/projects", json={"name": name})

        body = (await api.get("/api/v1/projects", params={"sort": "name"})).json()

        assert [item["name"] for item in body["items"]] == ["Астра", "Берёза", "Яблоко"]

    async def test_counts_documents_and_sheets(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        created = (await api.post("/api/v1/projects", json={"name": "Проект с документами"})).json()
        project = await projects_service.get_project(
            db_session,
            workspace_id=workspace_id,
            project_id=uuid.UUID(created["id"]),
        )
        assert project is not None

        await documents_service.create_document(
            db_session,
            project=project,
            display_name="Раздел АР.pdf",
            document_kind=DocumentKind.PDF,
        )
        await db_session.commit()

        body = (await api.get(f"/api/v1/projects/{created['id']}")).json()

        assert body["document_count"] == 1
        assert body["sheet_count"] == 0


class TestReadAndUpdate:
    async def test_unknown_project_returns_404_with_safe_body(self, api: AsyncClient) -> None:
        response = await api.get(f"/api/v1/projects/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NOT_FOUND"

    async def test_malformed_uuid_returns_422(self, api: AsyncClient) -> None:
        response = await api.get("/api/v1/projects/не-uuid")

        assert response.status_code == 422

    async def test_rename_project(self, api: AsyncClient) -> None:
        created = (await api.post("/api/v1/projects", json={"name": "Старое имя"})).json()

        response = await api.patch(f"/api/v1/projects/{created['id']}", json={"name": "Новое имя"})

        assert response.status_code == 200
        assert response.json()["name"] == "Новое имя"

    async def test_archive_project(self, api: AsyncClient) -> None:
        created = (await api.post("/api/v1/projects", json={"name": "В архив"})).json()

        response = await api.patch(f"/api/v1/projects/{created['id']}", json={"status": "archived"})

        assert response.status_code == 200
        assert response.json()["status"] == "archived"

    async def test_patch_without_fields_keeps_values(self, api: AsyncClient) -> None:
        created = (await api.post("/api/v1/projects", json={"name": "Без изменений"})).json()

        response = await api.patch(f"/api/v1/projects/{created['id']}", json={})

        assert response.status_code == 200
        assert response.json()["name"] == "Без изменений"


class TestWorkspaceBoundary:
    async def test_project_of_another_workspace_is_not_visible(
        self, api: AsyncClient, db_session: AsyncSession, second_workspace: Workspace
    ) -> None:
        foreign = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Чужой проект"
        )
        await db_session.commit()

        listed = (await api.get("/api/v1/projects")).json()
        direct = await api.get(f"/api/v1/projects/{foreign.id}")

        assert listed["total"] == 0
        assert direct.status_code == 404


class TestImportStatusInList:
    """Состояние импорта видно в списке — иначе пришлось бы открывать каждый проект."""

    async def test_project_without_jobs_has_no_last_job(self, api: AsyncClient) -> None:
        await api.post("/api/v1/projects", json={"name": "Без заданий"})

        body = (await api.get("/api/v1/projects")).json()

        assert body["items"][0]["last_job"] is None

    async def test_last_job_is_exposed(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        from app.domain import JobType
        from app.services import jobs as jobs_service

        created = (await api.post("/api/v1/projects", json={"name": "С импортом"})).json()
        project = await projects_service.get_project(
            db_session, workspace_id=workspace_id, project_id=uuid.UUID(created["id"])
        )
        assert project is not None
        job = await jobs_service.enqueue(
            db_session, job_type=JobType.LEGACY_IMPORT, project_id=project.id
        )
        await jobs_service.start(db_session, job=job, stage="regions")
        await jobs_service.report_progress(db_session, job=job, progress=0.64)
        await db_session.commit()

        body = (await api.get(f"/api/v1/projects/{created['id']}")).json()

        assert body["last_job"]["status"] == "running"
        assert body["last_job"]["progress"] == pytest.approx(0.64)
        assert body["last_job"]["stage"] == "regions"

    async def test_only_the_newest_job_is_returned(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        from app.domain import JobType
        from app.services import jobs as jobs_service

        created = (await api.post("/api/v1/projects", json={"name": "Два задания"})).json()
        project = await projects_service.get_project(
            db_session, workspace_id=workspace_id, project_id=uuid.UUID(created["id"])
        )
        assert project is not None

        first = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="first",
        )
        await jobs_service.start(db_session, job=first)
        await jobs_service.fail(db_session, job=first, error_code="IMPORT_FAILED")
        second = await jobs_service.enqueue(
            db_session,
            job_type=JobType.LEGACY_IMPORT,
            project_id=project.id,
            idempotency_key="second",
        )
        await db_session.commit()

        body = (await api.get("/api/v1/projects")).json()

        assert body["items"][0]["last_job"]["id"] == str(second.id)

    async def test_list_of_many_projects_stays_one_query_shaped(self, api: AsyncClient) -> None:
        """Список со счётчиками и заданиями собирается без обхода по проектам."""
        for index in range(10):
            await api.post("/api/v1/projects", json={"name": f"Проект {index}"})

        body = (await api.get("/api/v1/projects", params={"limit": 10})).json()

        assert body["total"] == 10
        assert all("last_job" in item for item in body["items"])


class TestProjectJobs:
    async def test_jobs_of_unknown_project_return_404(self, api: AsyncClient) -> None:
        response = await api.get(f"/api/v1/projects/{uuid.uuid4()}/jobs")

        assert response.status_code == 404

    async def test_new_project_has_no_jobs(self, api: AsyncClient) -> None:
        created = (await api.post("/api/v1/projects", json={"name": "Без заданий"})).json()

        body = (await api.get(f"/api/v1/projects/{created['id']}/jobs")).json()

        assert body["total"] == 0
