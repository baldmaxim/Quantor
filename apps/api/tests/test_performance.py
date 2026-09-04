"""Свойства производительности, которые легко потерять незаметно.

Медленный список проектов выглядит как «портал тормозит», а причина — в лишних запросах,
которых становится больше вместе с данными. Такое ловится только счётчиком: глазами
разница между одним запросом и тридцатью не видна, пока проектов мало.

Требует PostgreSQL и пропускается там, где базы нет.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain import DocumentKind, JobType, ProcessingStatus
from app.models import Region, Sheet
from app.services import documents as documents_service
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.storage.keys import revision_key


@contextmanager
def count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    """Считает SQL-запросы, ушедшие в базу за время блока."""
    statements: list[str] = []

    def before(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def _seed(session: AsyncSession, workspace_id: uuid.UUID, projects: int) -> None:
    """Создаёт проекты с документами, ревизиями, листами и заданиями."""
    for index in range(projects):
        project = await projects_service.create_project(
            session, workspace_id=workspace_id, name=f"Проект {index}"
        )
        document = await documents_service.create_document(
            session,
            project=project,
            display_name=f"документ-{index}.pdf",
            document_kind=DocumentKind.PDF,
        )
        revision_id = uuid.uuid4()
        revision = await documents_service.create_revision(
            session,
            document=document,
            revision_id=revision_id,
            source_filename=f"документ-{index}.pdf",
            source_mime="application/pdf",
            source_size=1024,
            source_sha256=f"{index:064d}",
            storage_key=revision_key(revision_id, "doc.pdf"),
            processing_status=ProcessingStatus.READY,
        )
        sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1")
        session.add(sheet)
        await session.flush()
        session.add(
            Region(
                sheet_id=sheet.id,
                external_block_id=f"blk_{index}",
                block_type="text",
                shape_type="rectangle",
                coords_norm=[0.1, 0.1, 0.9, 0.9],
            )
        )
        await jobs_service.enqueue(session, job_type=JobType.LEGACY_IMPORT, project_id=project.id)
    await session.commit()


class TestNoQueryGrowth:
    """Число запросов не должно расти вместе с числом строк в ответе."""

    async def test_project_list_does_not_grow_with_projects(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        workspace_id: uuid.UUID,
    ) -> None:
        await _seed(db_session, workspace_id, projects=3)
        with count_queries(db_engine) as few:
            await api.get("/api/v1/projects", params={"limit": 50})

        await _seed(db_session, workspace_id, projects=12)
        with count_queries(db_engine) as many:
            response = await api.get("/api/v1/projects", params={"limit": 50})

        assert response.json()["total"] == 15
        # Счётчики документов, листов и последнее задание берутся подзапросами,
        # поэтому запросов столько же, сколько было на трёх проектах.
        assert len(many) == len(few), (
            f"на 15 проектах {len(many)} запросов против {len(few)} на трёх — "
            "появился обход по строкам"
        )

    async def test_sheet_list_does_not_grow_with_sheets(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            session=db_session, workspace_id=workspace_id, name="Многолистовой"
        )
        document = await documents_service.create_document(
            db_session,
            project=project,
            display_name="альбом.pdf",
            document_kind=DocumentKind.PDF,
        )
        revision_id = uuid.uuid4()
        revision = await documents_service.create_revision(
            db_session,
            document=document,
            revision_id=revision_id,
            source_filename="альбом.pdf",
            source_mime="application/pdf",
            source_size=1024,
            source_sha256="b" * 64,
            storage_key=revision_key(revision_id, "album.pdf"),
            processing_status=ProcessingStatus.READY,
        )
        for page_index in range(40):
            db_session.add(Sheet(revision_id=revision.id, page_index=page_index))
        await db_session.commit()

        with count_queries(db_engine) as statements:
            response = await api.get(
                f"/api/v1/revisions/{revision.id}/sheets", params={"limit": 100}
            )

        assert response.json()["total"] == 40
        # Счётчик областей на лист — подзапрос, а не отдельное обращение на каждый лист.
        assert len(statements) <= 4, f"на 40 листов ушло {len(statements)} запросов"


class TestPagination:
    async def test_regions_cannot_be_requested_without_limit(self, api: AsyncClient) -> None:
        """Без предела на выборку одна страница могла бы вернуть тысячи областей."""
        response = await api.get(f"/api/v1/sheets/{uuid.uuid4()}/regions", params={"limit": 10_000})

        assert response.status_code == 422

    @pytest.mark.parametrize("endpoint", ["/api/v1/projects"])
    async def test_default_page_size_is_bounded(self, api: AsyncClient, endpoint: str) -> None:
        body = (await api.get(endpoint)).json()

        assert body["limit"] <= 500


class TestContentDelivery:
    async def test_binary_is_not_proxied_through_api(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """API отдаёт ссылку, а не файл: документ на 50–500 МБ не должен идти через процесс."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Ссылка"
        )
        document = await documents_service.create_document(
            db_session,
            project=project,
            display_name="документ.pdf",
            document_kind=DocumentKind.PDF,
        )
        revision_id = uuid.uuid4()
        revision = await documents_service.create_revision(
            db_session,
            document=document,
            revision_id=revision_id,
            source_filename="документ.pdf",
            source_mime="application/pdf",
            source_size=52_428_800,
            source_sha256="c" * 64,
            storage_key=revision_key(revision_id, "doc.pdf"),
            processing_status=ProcessingStatus.READY,
        )
        await db_session.commit()

        response = await api.get(f"/api/v1/revisions/{revision.id}/content-url")

        # Объекта в хранилище нет — но важно, что ответ в любом случае про ссылку,
        # а не про содержимое файла.
        assert response.status_code in (200, 404)
        assert "application/pdf" not in response.headers.get("content-type", "")
