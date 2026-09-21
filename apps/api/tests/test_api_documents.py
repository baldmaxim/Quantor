"""API документов, ревизий, листов и областей.

Данные собираются через сервисный слой: загрузки файлов ещё нет, она появится в промте 05.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    COORDINATE_SPACE_NORMALIZED_TOP_LEFT,
    DocumentKind,
    GeometryStatus,
    ProcessingStatus,
)
from app.models import Document, DocumentRevision, Project, Region, Sheet, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.storage.keys import revision_key
from tests.conftest import FakeObjectStorage

RUSSIAN_FILENAME = "01-03-00-01-12_ПД-00260560-АР.pdf"
FAKE_SHA = "a" * 64


@dataclass(frozen=True, slots=True)
class Fixture:
    project: Project
    document: Document
    revision: DocumentRevision
    sheet: Sheet


async def _build(session: AsyncSession, workspace_id: uuid.UUID) -> Fixture:
    project = await projects_service.create_project(
        session, workspace_id=workspace_id, name="ЖК «Северный», корпус 3"
    )
    document = await documents_service.create_document(
        session,
        project=project,
        display_name=RUSSIAN_FILENAME,
        document_kind=DocumentKind.RECOGNIZED_PACKAGE,
        discipline="АР",
    )
    revision_id = uuid.uuid4()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=revision_id,
        source_filename=RUSSIAN_FILENAME,
        source_mime="application/pdf",
        source_size=49_871_389,
        source_sha256=FAKE_SHA,
        storage_key=revision_key(revision_id, RUSSIAN_FILENAME),
        processing_status=ProcessingStatus.READY,
        source_metadata={
            "coordinate_space": COORDINATE_SPACE_NORMALIZED_TOP_LEFT,
            "schema_version": 1,
            "page_count": 2,
        },
    )
    sheet = Sheet(
        revision_id=revision.id, page_index=0, page_label="1", width_px=2481, height_px=3509
    )
    other = Sheet(revision_id=revision.id, page_index=1, page_label="2")
    session.add_all([sheet, other])
    await session.flush()

    session.add_all(
        [
            Region(
                sheet_id=sheet.id,
                external_block_id="blk_text_1",
                ordinal=1,
                block_type="text",
                shape_type="rectangle",
                coords_norm=[0.1, 0.1, 0.9, 0.4],
                recognition_status="recognized",
                raw_content_md="### BLOCK #1 [TEXT]: blk_text_1\n\n**Summary:** План 3 этажа",
                legacy_metadata={"crop_url": "https://example.invalid/api/crops/1"},
            ),
            Region(
                sheet_id=sheet.id,
                external_block_id="blk_image_2",
                ordinal=2,
                block_type="image",
                shape_type="rectangle",
                coords_norm=[0.1, 0.45, 0.9, 0.8],
                recognition_status="recognized",
            ),
            Region(
                sheet_id=sheet.id,
                external_block_id="blk_stamp_3",
                ordinal=None,
                block_type="stamp",
                shape_type="rectangle",
                coords_norm=[0.7, 0.9, 0.98, 0.99],
                recognition_status="recognized",
            ),
        ]
    )
    await session.commit()
    return Fixture(project=project, document=document, revision=revision, sheet=sheet)


async def _raw_pdf(
    session: AsyncSession, *, project: Project, sheets: int
) -> tuple[Document, DocumentRevision]:
    """Обычный PDF: распознавание к нему не применялось и применяться не будет."""
    document = await documents_service.create_document(
        session,
        project=project,
        display_name="чертёж.pdf",
        document_kind=DocumentKind.PDF,
    )
    revision = await _revision(session, document=document, index=1, sheets=sheets)
    return document, revision


async def _revision(
    session: AsyncSession, *, document: Document, index: int, sheets: int
) -> DocumentRevision:
    revision_id = uuid.uuid4()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=revision_id,
        source_filename=f"чертёж-{index}.pdf",
        source_mime="application/pdf",
        source_size=1_024 * index,
        source_sha256=f"{index:064d}",
        storage_key=revision_key(revision_id, "чертёж.pdf"),
        processing_status=ProcessingStatus.UNPROCESSED,
        geometry_status=GeometryStatus.PENDING,
    )
    session.add_all([Sheet(revision_id=revision.id, page_index=page) for page in range(sheets)])
    await session.commit()
    return revision


class TestDocuments:
    async def test_project_documents_are_listed(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (await api.get(f"/api/v1/projects/{data.project.id}/documents")).json()

        assert body["total"] == 1
        assert body["items"][0]["display_name"] == RUSSIAN_FILENAME
        assert body["items"][0]["document_kind"] == "recognized_package"

    async def test_unknown_document_returns_404(self, api: AsyncClient) -> None:
        response = await api.get(f"/api/v1/documents/{uuid.uuid4()}")

        assert response.status_code == 404


class TestRevisions:
    async def test_revision_exposes_source_metadata(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (await api.get(f"/api/v1/revisions/{data.revision.id}")).json()

        assert body["source_filename"] == RUSSIAN_FILENAME
        assert body["source_sha256"] == FAKE_SHA
        assert body["processing_status"] == "ready"
        assert body["source_metadata"]["coordinate_space"] == "normalized_page_top_left"

    async def test_revisions_of_document_are_listed(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (await api.get(f"/api/v1/documents/{data.document.id}/revisions")).json()

        assert body["total"] == 1

    async def test_same_file_cannot_create_second_revision(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Повторная загрузка того же файла не должна плодить ревизии (ADR-0003)."""
        data = await _build(db_session, workspace_id)
        duplicate_id = uuid.uuid4()

        with pytest.raises(IntegrityError):
            await documents_service.create_revision(
                db_session,
                document=data.document,
                revision_id=duplicate_id,
                source_filename=RUSSIAN_FILENAME,
                source_mime="application/pdf",
                source_size=49_871_389,
                source_sha256=FAKE_SHA,
                storage_key=revision_key(duplicate_id, RUSSIAN_FILENAME),
                processing_status=ProcessingStatus.PENDING,
            )
        await db_session.rollback()

    async def test_existing_revision_is_found_by_hash(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        found = await documents_service.find_revision_by_hash(
            db_session, document_id=data.document.id, source_sha256=FAKE_SHA
        )

        assert found is not None
        assert found.id == data.revision.id


class TestOpenability:
    """То, по чему клиент решает, можно ли открыть ревизию в рабочей области.

    Признаков три: вид документа, готовность геометрии и наличие листов. Распознавание в
    их число не входит — у обычного PDF его не бывает вовсе (ADR-0016).
    """

    async def test_revision_carries_its_sheet_count(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Иначе решение «показывать ли кнопку» требовало бы запроса листов каждой ревизии."""
        data = await _build(db_session, workspace_id)

        listed = (await api.get(f"/api/v1/documents/{data.document.id}/revisions")).json()
        single = (await api.get(f"/api/v1/revisions/{data.revision.id}")).json()

        assert listed["items"][0]["sheet_count"] == 2
        assert single["sheet_count"] == 2

    async def test_raw_pdf_is_openable_while_still_unrecognised(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Главный сценарий промта: распознавания нет и не будет, а открыть надо."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Обычный PDF"
        )
        document, revision = await _raw_pdf(db_session, project=project, sheets=3)
        revision.geometry_status = GeometryStatus.READY
        await db_session.commit()

        body = (await api.get(f"/api/v1/documents/{document.id}/revisions")).json()
        item = body["items"][0]

        assert item["processing_status"] == "unprocessed"
        assert item["geometry_status"] == "ready"
        assert item["sheet_count"] == 3

    async def test_revision_without_geometry_has_no_sheets(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Ещё не готов"
        )
        document, _ = await _raw_pdf(db_session, project=project, sheets=0)

        item = (await api.get(f"/api/v1/documents/{document.id}/revisions")).json()["items"][0]

        assert item["geometry_status"] == "pending"
        assert item["sheet_count"] == 0

    async def test_revisions_are_listed_from_oldest_to_newest(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Гарантия порядка, на которую опирается клиент, выбирая последнюю открываемую.

        Без неё «самая свежая ревизия» на карточке проекта зависела бы от порядка выдачи.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Три ревизии"
        )
        document, first = await _raw_pdf(db_session, project=project, sheets=1)
        second = await _revision(db_session, document=document, index=2, sheets=1)
        third = await _revision(db_session, document=document, index=3, sheets=1)

        # Порядок вставки нарочно нарушен относительно времени создания: выдача обязана
        # опираться на created_at, а не на порядок строк в таблице.
        first.created_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
        second.created_at = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
        third.created_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
        await db_session.commit()

        items = (await api.get(f"/api/v1/documents/{document.id}/revisions")).json()["items"]

        assert [item["id"] for item in items] == [str(first.id), str(third.id), str(second.id)]
        assert items[-1]["id"] == str(second.id)


class TestContentUrl:
    async def test_returns_presigned_url_with_original_filename(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        fake_storage: FakeObjectStorage,
    ) -> None:
        data = await _build(db_session, workspace_id)
        await fake_storage.put_bytes(
            data.revision.storage_key,
            b"%PDF-1.7",
            content_type="application/pdf",
            original_filename=RUSSIAN_FILENAME,
        )

        body = (await api.get(f"/api/v1/revisions/{data.revision.id}/content-url")).json()

        assert body["url"].startswith("https://storage.test/")
        assert body["filename"] == RUSSIAN_FILENAME
        assert body["content_type"] == "application/pdf"
        assert body["expires_in"] > 0

    async def test_missing_object_reports_safe_code(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        response = await api.get(f"/api/v1/revisions/{data.revision.id}/content-url")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "CONTENT_NOT_AVAILABLE"


class TestSheetsAndRegions:
    async def test_sheets_are_ordered_and_counted(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (await api.get(f"/api/v1/revisions/{data.revision.id}/sheets")).json()

        assert body["total"] == 2
        assert [item["page_index"] for item in body["items"]] == [0, 1]
        assert body["items"][0]["region_count"] == 3
        assert body["items"][0]["width_px"] == 2481

    async def test_regions_expose_normalized_coordinates(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (await api.get(f"/api/v1/sheets/{data.sheet.id}/regions")).json()

        assert body["total"] == 3
        first = body["items"][0]
        assert first["coords_norm"] == [0.1, 0.1, 0.9, 0.4]
        assert first["shape_type"] == "rectangle"
        assert "Summary" in first["raw_content_md"]

    async def test_regions_can_be_filtered_by_type(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (
            await api.get(f"/api/v1/sheets/{data.sheet.id}/regions", params={"block_type": "stamp"})
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["block_type"] == "stamp"
        assert body["items"][0]["ordinal"] is None

    async def test_crop_url_stays_metadata_only(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Внешняя ссылка отдаётся как метаданные и никогда не загружается сервером."""
        data = await _build(db_session, workspace_id)

        body = (
            await api.get(f"/api/v1/sheets/{data.sheet.id}/regions", params={"block_type": "text"})
        ).json()

        assert body["items"][0]["legacy_metadata"]["crop_url"].startswith("https://")

    async def test_regions_pagination(
        self, api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        data = await _build(db_session, workspace_id)

        body = (
            await api.get(f"/api/v1/sheets/{data.sheet.id}/regions", params={"limit": 2})
        ).json()

        assert body["total"] == 3
        assert len(body["items"]) == 2

    async def test_unknown_sheet_returns_404(self, api: AsyncClient) -> None:
        response = await api.get(f"/api/v1/sheets/{uuid.uuid4()}/regions")

        assert response.status_code == 404


class TestCrossProjectAccess:
    async def test_sheet_of_foreign_workspace_is_hidden(
        self, api: AsyncClient, db_session: AsyncSession, second_workspace: Workspace
    ) -> None:
        data = await _build(db_session, second_workspace.id)

        for path in (
            f"/api/v1/documents/{data.document.id}",
            f"/api/v1/revisions/{data.revision.id}",
            f"/api/v1/revisions/{data.revision.id}/sheets",
            f"/api/v1/sheets/{data.sheet.id}/regions",
        ):
            assert (await api.get(path)).status_code == 404, path
