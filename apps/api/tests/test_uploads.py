"""Приём файлов: типы, проверка содержимого, пределы, идемпотентность.

Проверки классификации и сигнатур обходятся без базы. Полный путь загрузки требует
PostgreSQL и пропускается там, где его нет.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.domain import DocumentKind, ProcessingStatus
from app.errors import DomainError, ErrorCode
from app.services import uploads as uploads_service
from app.services.uploads import RAW_PDF, RECOGNIZED_PACKAGE, classify, verify_signature
from tests.conftest import FakeObjectStorage

PDF_BYTES = b"%PDF-1.7\n" + b"0" * 512
RUSSIAN_PDF_NAME = "01-03-00-01-12_ПД-00260560-АР.pdf"
RUSSIAN_ZIP_NAME = "01-03-00-01-12_ПД-00260560-АР.zip"


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("документ.pdf", PDF_BYTES)
        archive.writestr("документ_blocks.json", '{"schema_version": 1}')
    return buffer.getvalue()


class TestClassification:
    @pytest.mark.parametrize(
        ("filename", "kind"),
        [
            ("пакет.zip", DocumentKind.RECOGNIZED_PACKAGE),
            ("чертёж.PDF", DocumentKind.PDF),
            ("модель.rvt", DocumentKind.REVIT),
            ("сводная.nwd", DocumentKind.NAVISWORKS),
            ("кэш.nwc", DocumentKind.NAVISWORKS),
            ("обмен.ifc", DocumentKind.IFC),
        ],
    )
    def test_supported_extensions(self, filename: str, kind: DocumentKind) -> None:
        assert classify(filename).document_kind is kind

    @pytest.mark.parametrize(
        "filename", ["скрипт.exe", "архив.rar", "таблица.xlsx", "без_расширения", "план.dwg"]
    )
    def test_unsupported_extensions_are_rejected(self, filename: str) -> None:
        with pytest.raises(DomainError) as error:
            classify(filename)

        assert error.value.code is ErrorCode.UNSUPPORTED_FILE_TYPE
        assert error.value.status_code == 415

    def test_bim_models_are_stored_without_processing(self) -> None:
        kind = classify("корпус3.nwd")

        assert kind.processing_status is ProcessingStatus.PROCESSOR_UNAVAILABLE
        assert kind.schedules_import is False

    def test_only_recognized_package_schedules_import(self) -> None:
        assert classify("пакет.zip").schedules_import is True
        assert classify("чертёж.pdf").schedules_import is False


class TestSignature:
    def test_renamed_executable_is_caught(self) -> None:
        """Расширение подделывается переименованием, поэтому решает содержимое."""
        with pytest.raises(DomainError) as error:
            verify_signature(b"MZ\x90\x00", RECOGNIZED_PACKAGE)

        assert error.value.code is ErrorCode.MIME_MISMATCH

    def test_pdf_signature_is_checked(self) -> None:
        verify_signature(PDF_BYTES[:8], RAW_PDF)

        with pytest.raises(DomainError):
            verify_signature(b"PK\x03\x04abcd", RAW_PDF)

    def test_empty_archive_is_rejected_as_corrupt(self) -> None:
        with pytest.raises(DomainError) as error:
            verify_signature(b"PK\x05\x06\x00\x00\x00\x00", RECOGNIZED_PACKAGE)

        assert error.value.code is ErrorCode.CORRUPT_ARCHIVE

    def test_valid_zip_passes(self) -> None:
        verify_signature(_zip_bytes()[:8], RECOGNIZED_PACKAGE)


class TestSizeLimit:
    async def test_stream_is_cut_off_at_the_limit(self) -> None:
        async def chunks() -> AsyncIterator[bytes]:
            for _ in range(10):
                yield b"x" * 1024

        with pytest.raises(DomainError) as error:
            async for _ in uploads_service.limit_stream(chunks(), max_size=4096):
                pass

        assert error.value.code is ErrorCode.UPLOAD_TOO_LARGE
        assert error.value.status_code == 413

    async def test_stream_within_limit_passes_through(self) -> None:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"a" * 100
            yield b"b" * 100

        received = b""
        async for chunk in uploads_service.limit_stream(chunks(), max_size=1000):
            received += chunk

        assert len(received) == 200


class TestUploadEndpoint:
    async def _project(self, api: AsyncClient, name: str = "Проект загрузки") -> str:
        response = await api.post("/api/v1/projects", json={"name": name})
        return str(response.json()["id"])

    async def test_recognized_package_is_queued_for_import(
        self, api: AsyncClient, fake_storage: FakeObjectStorage
    ) -> None:
        project_id = await self._project(api)

        response = await api.post(
            f"/api/v1/projects/{project_id}/uploads",
            files={"file": (RUSSIAN_ZIP_NAME, _zip_bytes(), "application/zip")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["document"]["document_kind"] == "recognized_package"
        assert body["revision"]["processing_status"] == "pending"
        assert body["job"]["status"] == "queued"
        assert body["job"]["job_type"] == "legacy_import"
        assert body["is_duplicate"] is False
        assert len(fake_storage.objects) == 1

    async def test_russian_filename_survives_round_trip(
        self, api: AsyncClient, fake_storage: FakeObjectStorage
    ) -> None:
        project_id = await self._project(api)

        response = await api.post(
            f"/api/v1/projects/{project_id}/uploads",
            files={"file": (RUSSIAN_PDF_NAME, PDF_BYTES, "application/pdf")},
        )

        body = response.json()
        assert body["revision"]["source_filename"] == RUSSIAN_PDF_NAME
        key = next(iter(fake_storage.objects))
        # Имя пользователя в ключ объекта не попадает, но сохраняется метаданными.
        assert "ПД" not in key
        assert fake_storage.metadata[key]["original-filename"] == RUSSIAN_PDF_NAME

    async def test_raw_pdf_schedules_geometry_but_stays_unprocessed(
        self, api: AsyncClient
    ) -> None:
        """Распознавание и геометрия независимы: PDF ждёт AI, но геометрию уже извлекаем."""
        project_id = await self._project(api)

        body = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": ("чертёж.pdf", PDF_BYTES, "application/pdf")},
            )
        ).json()

        assert body["revision"]["processing_status"] == "unprocessed"
        assert body["job"] is not None
        assert body["job"]["job_type"] == "pdf_geometry_extract"

    async def test_bim_model_is_stored_with_honest_status(self, api: AsyncClient) -> None:
        project_id = await self._project(api)

        body = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": ("корпус3.nwd", b"\x00\x01\x02" * 100, "application/octet-stream")},
            )
        ).json()

        assert body["revision"]["processing_status"] == "processor_unavailable"
        assert body["job"] is None

    async def test_repeated_upload_does_not_create_second_revision(
        self, api: AsyncClient, fake_storage: FakeObjectStorage
    ) -> None:
        project_id = await self._project(api)
        payload = _zip_bytes()

        first = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": (RUSSIAN_ZIP_NAME, payload, "application/zip")},
            )
        ).json()
        second = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": (RUSSIAN_ZIP_NAME, payload, "application/zip")},
            )
        ).json()

        assert second["is_duplicate"] is True
        assert second["revision"]["id"] == first["revision"]["id"]
        assert second["job"]["id"] == first["job"]["id"]
        # Лишний объект удалён, а не оставлен мусором в хранилище.
        assert len(fake_storage.objects) == 1
        assert len(fake_storage.deleted) == 1

        documents = (await api.get(f"/api/v1/projects/{project_id}/documents")).json()
        assert documents["total"] == 1

    async def test_renamed_executable_is_rejected(
        self, api: AsyncClient, fake_storage: FakeObjectStorage
    ) -> None:
        project_id = await self._project(api)

        response = await api.post(
            f"/api/v1/projects/{project_id}/uploads",
            files={"file": ("вирус.zip", b"MZ\x90\x00" + b"\x00" * 100, "application/zip")},
        )

        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "MIME_MISMATCH"

    async def test_unsupported_type_is_rejected(self, api: AsyncClient) -> None:
        project_id = await self._project(api)

        response = await api.post(
            f"/api/v1/projects/{project_id}/uploads",
            files={"file": ("смета.xlsx", b"PK\x03\x04data", "application/vnd.ms-excel")},
        )

        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_empty_file_is_rejected(
        self, api: AsyncClient, fake_storage: FakeObjectStorage
    ) -> None:
        project_id = await self._project(api)

        response = await api.post(
            f"/api/v1/projects/{project_id}/uploads",
            files={"file": ("пустой.pdf", b"", "application/pdf")},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "EMPTY_FILE"
        assert fake_storage.objects == {}

    async def test_upload_into_unknown_project_returns_404(self, api: AsyncClient) -> None:
        response = await api.post(
            f"/api/v1/projects/{uuid.uuid4()}/uploads",
            files={"file": ("чертёж.pdf", PDF_BYTES, "application/pdf")},
        )

        assert response.status_code == 404

    async def test_second_file_becomes_new_revision_of_same_document(
        self, api: AsyncClient
    ) -> None:
        project_id = await self._project(api)
        first = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": ("узлы.pdf", PDF_BYTES, "application/pdf")},
            )
        ).json()

        second = (
            await api.post(
                f"/api/v1/projects/{project_id}/uploads",
                files={"file": ("узлы.pdf", PDF_BYTES + b"revision two", "application/pdf")},
                data={"document_id": first["document"]["id"]},
            )
        ).json()

        assert second["document"]["id"] == first["document"]["id"]
        assert second["revision"]["id"] != first["revision"]["id"]

        revisions = (await api.get(f"/api/v1/documents/{first['document']['id']}/revisions")).json()
        assert revisions["total"] == 2


class TestCapabilities:
    async def test_capabilities_describe_every_supported_type(self, api: AsyncClient) -> None:
        response = await api.post("/api/v1/projects", json={"name": "Возможности"})
        project_id = response.json()["id"]

        body = (await api.get(f"/api/v1/projects/{project_id}/upload-capabilities")).json()

        extensions = {item["extension"] for item in body}
        assert extensions == {"zip", "pdf", "rvt", "nwd", "nwc", "ifc"}
        for item in body:
            assert item["capability"]
            assert item["max_size_bytes"] > 0
