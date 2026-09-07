"""Импорт распознанного пакета от начала до конца.

Требует PostgreSQL и потому пропускается там, где базы нет. Хранилище — в памяти:
поднимать MinIO ради проверки логики импорта незачем.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.domain import ArtifactKind, DocumentKind, JobStatus, ProcessingStatus
from app.models import Document, DocumentRevision, Job, Project, RecognitionArtifact, Region, Sheet
from app.services import job_runner
from app.services.legacy import importer
from tests.conftest import FakeObjectStorage
from tests.test_legacy_archive import BASE_NAME, blocks_payload, build_package

# Ожидаемые значения эталонного архива распознавалки. Это утверждения фикстуры,
# а не константы продукта: в коде портала таких чисел быть не должно.
REAL_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "_prompts"
    / "stage1"
    / "fixtures"
    / "legacy"
    / "01-03-00-01-12_ПД-00260560-АР.zip"
)
EXPECTED_PAGES = 77
EXPECTED_REGIONS = 383
EXPECTED_BY_TYPE = {"text": 230, "image": 90, "stamp": 63}
EXPECTED_MD_SECTIONS = 320


async def _upload(
    api: AsyncClient, payload: bytes, name: str = f"{BASE_NAME}.zip"
) -> dict[str, Any]:
    project = (await api.post("/api/v1/projects", json={"name": "Импорт пакета"})).json()
    response = await api.post(
        f"/api/v1/projects/{project['id']}/uploads",
        files={"file": (name, payload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    body["project_id"] = project["id"]
    return body


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


@pytest.fixture
def settings() -> Settings:
    return get_settings()


class TestSuccessfulImport:
    async def test_creates_full_object_graph(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED
        assert job.progress == pytest.approx(1.0)
        assert job.payload["sheet_count"] == 2
        assert job.payload["region_count"] == 2

        revision_id = uuid.UUID(str(job.payload["imported_revision_id"]))
        revision = await db_session.get(DocumentRevision, revision_id)
        assert revision is not None
        assert revision.processing_status is ProcessingStatus.READY
        assert revision.source_mime == "application/pdf"
        assert revision.source_metadata["coordinate_space"] == "normalized_page_top_left"
        assert revision.source_metadata["imported_from_revision_id"] == upload["revision"]["id"]

        document = await db_session.get(Document, revision.document_id)
        assert document is not None
        assert document.document_kind is DocumentKind.PDF

    async def test_package_revision_becomes_ready(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))

        await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        package_revision = await db_session.get(
            DocumentRevision, uuid.UUID(upload["revision"]["id"])
        )
        assert package_revision is not None
        assert package_revision.processing_status is ProcessingStatus.READY

    async def test_sheets_and_regions_are_visible_through_api(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))
        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)
        revision_id = job.payload["imported_revision_id"]

        sheets = (await api.get(f"/api/v1/revisions/{revision_id}/sheets")).json()
        assert sheets["total"] == 2
        assert sheets["items"][0]["width_px"] == 2481

        regions = (await api.get(f"/api/v1/sheets/{sheets['items'][0]['id']}/regions")).json()
        assert regions["total"] == 1
        region = regions["items"][0]
        assert region["coords_norm"] == [0.1, 0.1, 0.9, 0.4]
        assert "План 3-го этажа" in region["raw_content_md"]

    async def test_stamp_without_markdown_section_survives(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        """Штампы не попадают в results.md, но остаются полноценными областями."""
        upload = await _upload(api, build_package(blocks=blocks_payload()))
        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        stamps = await db_session.execute(select(Region).where(Region.block_type == "stamp"))
        stamp = stamps.scalar_one()

        assert stamp.raw_content_md is None
        assert stamp.ordinal is None
        assert job.payload["region_count"] == 2

    async def test_crop_url_is_stored_but_never_fetched(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))
        await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        regions = await db_session.execute(select(Region).where(Region.block_type == "text"))
        region = regions.scalar_one()

        assert region.legacy_metadata["crop_url"] == "https://example.invalid/api/crops/1"
        # Хранилище знает только о загруженных нами объектах: внешний адрес не скачивался.
        assert all("example.invalid" not in key for key in fake_storage.objects)

    async def test_artifacts_are_stored_with_checksums(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload(), with_html=True))
        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        artifacts = (
            (
                await db_session.execute(
                    select(RecognitionArtifact).where(
                        RecognitionArtifact.revision_id
                        == uuid.UUID(str(job.payload["imported_revision_id"]))
                    )
                )
            )
            .scalars()
            .all()
        )

        kinds = {artifact.artifact_kind for artifact in artifacts}
        assert kinds == {
            ArtifactKind.BLOCKS_JSON,
            ArtifactKind.RESULTS_MD,
            ArtifactKind.RESULTS_HTML,
        }
        assert all(len(artifact.sha256) == 64 for artifact in artifacts)

        html = next(a for a in artifacts if a.artifact_kind is ArtifactKind.RESULTS_HTML)
        # HTML хранится как данные, а не как разметка: иначе его однажды отрисуют как доверенный.
        assert fake_storage.metadata[html.storage_key]["content-type"] != "text/html"

    async def test_pdf_is_available_through_content_url(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))
        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        response = await api.get(
            f"/api/v1/revisions/{job.payload['imported_revision_id']}/content-url"
        )

        assert response.status_code == 200
        assert response.json()["content_type"] == "application/pdf"


class TestIdempotency:
    async def test_second_run_does_not_duplicate_anything(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload()))
        first = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        package_revision = await db_session.get(
            DocumentRevision, uuid.UUID(upload["revision"]["id"])
        )
        assert package_revision is not None
        project = await db_session.get(Project, uuid.UUID(upload["project_id"]))
        assert project is not None

        result = await importer.import_package(
            db_session,
            fake_storage,
            package_revision=package_revision,
            project=project,
            settings=settings,
        )

        assert result.already_imported is True
        assert str(result.revision_id) == first.payload["imported_revision_id"]

        sheets = (await db_session.execute(select(Sheet))).scalars().all()
        regions = (await db_session.execute(select(Region))).scalars().all()
        assert len(sheets) == 2
        assert len(regions) == 2

        # Повторный импорт не должен оставлять пакет «в обработке»: исполнитель ставит
        # ревизии IMPORTING перед запуском, и ранний выход обязан довести её до конца.
        # Иначе на карточке проекта задание успешно, а пакет вечно в очереди.
        await db_session.refresh(package_revision)
        assert package_revision.processing_status is ProcessingStatus.READY


class TestFailures:
    async def test_invalid_blocks_leave_no_half_built_project(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        broken = blocks_payload()
        broken["blocks"][0]["coords_norm"] = [5.0, 0.1, 0.9, 0.4]
        upload = await _upload(api, build_package(blocks=broken))

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_code == "LEGACY_BLOCKS_INVALID"

        # Ни листов, ни областей, ни второго документа появиться не должно.
        assert (await db_session.execute(select(Sheet))).scalars().all() == []
        assert (await db_session.execute(select(Region))).scalars().all() == []
        documents = (await db_session.execute(select(Document))).scalars().all()
        assert len(documents) == 1

    async def test_failed_import_marks_revision(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=None, with_md=False))

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        revision = await db_session.get(DocumentRevision, uuid.UUID(upload["revision"]["id"]))
        assert revision is not None
        assert revision.processing_status is ProcessingStatus.FAILED
        assert revision.processing_error_code == job.error_code

    async def test_unsupported_schema_reports_its_own_code(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks=blocks_payload(schema_version=99)))

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.error_code == "LEGACY_SCHEMA_UNSUPPORTED"

    async def test_error_message_stays_safe(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        upload = await _upload(api, build_package(blocks="{ сломанный json"))

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.status is JobStatus.FAILED
        assert job.error_message is not None
        assert "Traceback" not in job.error_message


@pytest.mark.skipif(
    not REAL_FIXTURE.exists(),
    reason=(
        "нет эталонного архива распознавалки — положите его в "
        "_prompts/stage1/fixtures/legacy/, см. README там же"
    ),
)
class TestRealPackage:
    """Проверка на настоящем пакете. Архив в репозиторий не входит — он весит 47 МБ."""

    async def test_expected_counts(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        payload = REAL_FIXTURE.read_bytes()
        upload = await _upload(api, payload, name=REAL_FIXTURE.name)

        job = await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        assert job.status is JobStatus.SUCCEEDED, job.error_message
        assert job.payload["sheet_count"] == EXPECTED_PAGES
        assert job.payload["region_count"] == EXPECTED_REGIONS

        regions = (await db_session.execute(select(Region))).scalars().all()
        by_type = Counter(region.block_type for region in regions)
        assert dict(by_type) == EXPECTED_BY_TYPE

        with_text = sum(1 for region in regions if region.raw_content_md)
        assert with_text == EXPECTED_MD_SECTIONS

        revision = await db_session.get(
            DocumentRevision, uuid.UUID(str(job.payload["imported_revision_id"]))
        )
        assert revision is not None
        assert revision.source_metadata["coordinate_space"] == "normalized_page_top_left"

    async def test_no_external_addresses_were_contacted(
        self,
        api: AsyncClient,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        settings: Settings,
    ) -> None:
        """В пакете 320 внешних ссылок на вырезы — ни одна не должна быть загружена."""
        payload = REAL_FIXTURE.read_bytes()
        upload = await _upload(api, payload, name=REAL_FIXTURE.name)

        await _run_import(db_session, fake_storage, upload["job"]["id"], settings)

        regions = (await db_session.execute(select(Region))).scalars().all()
        with_crop = [r for r in regions if r.legacy_metadata.get("crop_url")]

        assert len(with_crop) == 320
        assert all(key.startswith("revisions/") for key in fake_storage.objects)


def test_blocks_fixture_matches_expected_shape() -> None:
    """Проверка самой фикстуры: если она сломается, ошибки импорта будут загадочными."""
    payload = json.loads(json.dumps(blocks_payload()))

    assert payload["schema_version"] == 1
    assert {block["block_type"] for block in payload["blocks"]} == {"text", "stamp"}


def test_generated_package_is_readable_zip() -> None:
    with zipfile.ZipFile(io.BytesIO(build_package(blocks=blocks_payload()))) as archive:
        assert archive.testzip() is None
