"""Прикрепление распознанного пакета к ранее загруженному PDF (ADR-0037).

Требует PostgreSQL; хранилище в памяти. Все данные синтетические.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.domain import JobStatus, ProcessingStatus
from app.models import (
    Document,
    DocumentRevision,
    Job,
    Project,
    RecognitionArtifact,
    Region,
    Sheet,
)
from app.services import job_runner
from app.services.legacy import importer
from app.services.uploads import normalize_pdf_stem
from tests.conftest import FakeObjectStorage
from tests.test_legacy_archive import BASE_NAME, PDF_BYTES, blocks_payload, build_package


@pytest.fixture
def settings() -> Settings:
    return get_settings()


async def _new_project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": "Прикрепление пакета"})
    return str(response.json()["id"])


async def _upload_file(
    api: AsyncClient, project_id: str, name: str, payload: bytes, mime: str
) -> dict[str, Any]:
    response = await api.post(
        f"/api/v1/projects/{project_id}/uploads", files={"file": (name, payload, mime)}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _upload_pdf(api: AsyncClient, project_id: str) -> dict[str, Any]:
    return await _upload_file(api, project_id, f"{BASE_NAME}.pdf", PDF_BYTES, "application/pdf")


async def _upload_zip(api: AsyncClient, project_id: str, **kwargs: Any) -> dict[str, Any]:
    payload = build_package(blocks=blocks_payload(), **kwargs)
    return await _upload_file(api, project_id, f"{BASE_NAME}.zip", payload, "application/zip")


async def _run_import(
    session: AsyncSession, storage: FakeObjectStorage, job_id: str, settings: Settings
) -> Job:
    job = await session.get(Job, uuid.UUID(job_id))
    assert job is not None
    result = await job_runner.execute_legacy_import(
        session, job, storage=storage, settings=settings
    )
    await session.commit()
    return result


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


class TestAttachToLoadedPdf:
    async def test_regions_attach_to_existing_revision(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id, with_html=True)
        pdf_revision_id = uuid.UUID(pdf["revision"]["id"])
        pdf_revision = await db_session.get(DocumentRevision, pdf_revision_id)
        assert pdf_revision is not None
        metadata_before = dict(pdf_revision.source_metadata)
        assert pdf_revision.processing_status is ProcessingStatus.UNPROCESSED
        objects_before = set(fake_storage.objects)

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["attached_to_existing"] is True
        assert job.payload["imported_revision_id"] == str(pdf_revision_id)
        assert job.payload["document_id"] == pdf["document"]["id"]
        assert job.payload["sheet_count"] == 2
        assert job.payload["region_count"] == 2
        assert job.payload["artifact_count"] == 3

        # Второго документа нет: PDF-документ и документ ZIP.
        assert await _count(db_session, Document) == 2
        assert await _count(db_session, DocumentRevision) == 2

        sheets = (
            (await db_session.execute(select(Sheet).where(Sheet.revision_id == pdf_revision_id)))
            .scalars()
            .all()
        )
        assert {sheet.page_index for sheet in sheets} == {0, 1}
        assert all(sheet.width_px == 2481 and sheet.height_px == 3509 for sheet in sheets)

        regions = (await db_session.execute(select(Region))).scalars().all()
        assert {region.sheet_id for region in regions} <= {sheet.id for sheet in sheets}
        assert len(regions) == 2

        artifacts = (
            (
                await db_session.execute(
                    select(RecognitionArtifact).where(
                        RecognitionArtifact.revision_id == pdf_revision_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(artifacts) == 3

        # PDF повторно в хранилище не клали, метаданные ревизии (ADR-0003) не менялись.
        new_objects = set(fake_storage.objects) - objects_before
        assert all("/artifacts/" in key for key in new_objects)
        await db_session.refresh(pdf_revision)
        assert pdf_revision.source_metadata == metadata_before

        package_revision = await db_session.get(
            DocumentRevision, uuid.UUID(archive["revision"]["id"])
        )
        assert package_revision is not None
        assert package_revision.processing_status is ProcessingStatus.READY
        # Прикреплённое распознавание делает «готовой» и саму PDF-ревизию.
        assert pdf_revision.processing_status is ProcessingStatus.READY

    async def test_existing_sheets_keep_their_raster_size(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id)
        pdf_revision_id = uuid.UUID(pdf["revision"]["id"])
        db_session.add(Sheet(revision_id=pdf_revision_id, page_index=0, width_px=100))
        db_session.add(Sheet(revision_id=pdf_revision_id, page_index=1))
        await db_session.commit()

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        sheets = {
            sheet.page_index: sheet
            for sheet in (
                await db_session.execute(select(Sheet).where(Sheet.revision_id == pdf_revision_id))
            ).scalars()
        }
        assert sheets[0].width_px == 100  # заданное не перезаписывается
        assert sheets[0].height_px == 3509
        assert sheets[1].width_px == 2481

    async def test_repeat_is_already_imported(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id)
        await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        package_revision = await db_session.get(
            DocumentRevision, uuid.UUID(archive["revision"]["id"])
        )
        project = await db_session.get(Project, uuid.UUID(project_id))
        assert package_revision is not None and project is not None

        result = await importer.import_package(
            db_session,
            fake_storage,
            package_revision=package_revision,
            project=project,
            settings=settings,
        )

        assert result.already_imported is True
        assert result.attached_to_existing is True
        assert (result.sheet_count, result.region_count, result.artifact_count) == (2, 2, 2)
        assert await _count(db_session, Region) == 2
        assert await _count(db_session, Sheet) == 2
        assert await _count(db_session, RecognitionArtifact) == 2


class TestAttachFailures:
    async def test_page_count_mismatch_writes_nothing(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id)
        pdf_revision_id = uuid.UUID(pdf["revision"]["id"])
        for index in range(3):
            db_session.add(Sheet(revision_id=pdf_revision_id, page_index=index))
        await db_session.commit()

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_code == "PDF_PAGE_COUNT_MISMATCH"
        assert await _count(db_session, Region) == 0
        assert await _count(db_session, RecognitionArtifact) == 0
        assert await _count(db_session, Sheet) == 3
        assert await _count(db_session, Document) == 2


class TestOldPathUnchanged:
    async def test_without_matching_pdf_creates_own_document(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        # Другой PDF в проекте: хеш не совпадает с PDF из пакета.
        other = await _upload_file(
            api, project_id, "other.pdf", PDF_BYTES + b"other", "application/pdf"
        )
        archive = await _upload_zip(api, project_id)

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["attached_to_existing"] is False
        assert await _count(db_session, Document) == 3
        revision = await db_session.get(
            DocumentRevision, uuid.UUID(str(job.payload["imported_revision_id"]))
        )
        assert revision is not None
        assert revision.source_metadata["imported_from_revision_id"] == archive["revision"]["id"]
        # Загруженный PDF без пакета остаётся нераспознанным.
        other_revision = await db_session.get(DocumentRevision, uuid.UUID(other["revision"]["id"]))
        assert other_revision is not None
        assert other_revision.processing_status is ProcessingStatus.UNPROCESSED


class TestPackageWithoutPdf:
    async def test_attaches_to_pdf_with_same_stem_any_case(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_file(
            api, project_id, f"{BASE_NAME.upper()}.PDF", PDF_BYTES, "application/pdf"
        )
        archive = await _upload_zip(api, project_id, omit_pdf=True, with_html=True)
        pdf_revision_id = uuid.UUID(pdf["revision"]["id"])

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["attached_to_existing"] is True
        assert job.payload["attached_by"] == "filename"
        assert job.payload["imported_revision_id"] == str(pdf_revision_id)
        assert job.payload["document_id"] == pdf["document"]["id"]
        assert job.payload["artifact_count"] == 3
        # Новых документов нет: PDF и ZIP.
        assert await _count(db_session, Document) == 2
        assert await _count(db_session, DocumentRevision) == 2
        assert await _count(db_session, Region) == 2

    async def test_recognition_with_underscores_attaches_to_pdf_with_spaces(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_file(
            api, project_id, "КР2 (Часть 1)_ver3.pdf", PDF_BYTES, "application/pdf"
        )
        stem = "КР2_(Часть_1)_ver3"
        payload = build_package(
            blocks=None,
            with_md=False,
            omit_pdf=True,
            extra={
                f"{stem}_blocks.json": json.dumps(
                    blocks_payload(document_name="КР2 (Часть 1)_ver3.pdf"), ensure_ascii=False
                ).encode("utf-8"),
                f"{stem}_results.md": b"### BLOCK #1 [TEXT]: blk_text_1\n",
                f"{stem}_results.html": "<html><body>отчёт</body></html>".encode(),
            },
        )
        archive = await _upload_file(api, project_id, f"{stem}.zip", payload, "application/zip")

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["attached_to_existing"] is True
        assert job.payload["attached_by"] == "filename"
        assert job.payload["imported_revision_id"] == pdf["revision"]["id"]

    async def test_falls_back_to_document_name(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_file(api, project_id, "Другое имя.pdf", PDF_BYTES, "application/pdf")
        payload = build_package(
            blocks=blocks_payload(document_name="Другое имя.pdf"), omit_pdf=True
        )
        archive = await _upload_file(
            api, project_id, f"{BASE_NAME}.zip", payload, "application/zip"
        )

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["attached_by"] == "filename"
        assert job.payload["imported_revision_id"] == pdf["revision"]["id"]

    async def test_package_with_pdf_is_attached_by_sha256(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id)

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.payload["attached_by"] == "sha256"

    async def test_no_pdf_in_project_fails(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        await _upload_file(api, project_id, "other.pdf", PDF_BYTES, "application/pdf")
        archive = await _upload_zip(api, project_id, omit_pdf=True)

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_code == "LEGACY_PDF_MISSING"
        assert BASE_NAME in str(job.error_message)
        assert await _count(db_session, Region) == 0
        # Нового документа нет: other.pdf и ZIP.
        assert await _count(db_session, Document) == 2

    async def test_two_pdfs_with_same_stem_fail(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        await _upload_file(api, project_id, f"{BASE_NAME}.pdf", PDF_BYTES, "application/pdf")
        await _upload_file(
            api, project_id, f"{BASE_NAME.upper()}.pdf", PDF_BYTES + b"2", "application/pdf"
        )
        archive = await _upload_zip(api, project_id, omit_pdf=True)

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_code == "LEGACY_PDF_MISSING"
        assert "несколько PDF" in str(job.error_message)
        assert await _count(db_session, Region) == 0

    async def test_page_count_mismatch_fails(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        project_id = await _new_project(api)
        pdf = await _upload_pdf(api, project_id)
        archive = await _upload_zip(api, project_id, omit_pdf=True)
        for index in range(3):
            db_session.add(Sheet(revision_id=uuid.UUID(pdf["revision"]["id"]), page_index=index))
        await db_session.commit()

        job = await _run_import(db_session, fake_storage, archive["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_code == "PDF_PAGE_COUNT_MISMATCH"
        assert await _count(db_session, Region) == 0
        assert await _count(db_session, Document) == 2


class TestNormalizePdfStem:
    def test_recognition_stem_matches_pdf_name_with_spaces(self) -> None:
        assert normalize_pdf_stem("КР2 (Часть 1)_ver3.pdf") == normalize_pdf_stem(
            "кр2_(часть_1)_ver3"
        )
