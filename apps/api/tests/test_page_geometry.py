"""Извлечение канонической геометрии страниц PDF (ADR-0016).

Синтетические PDF строятся тем же pypdf, который их и читает. Это осознанный компромисс:
проверяется не разбор чужого формата, а собственная логика — отображаемый размер, поворот,
согласованность с листами и откат при расхождении. Совпадение с настоящим отрисовщиком
проверяется отдельно, на эталонной фикстуре.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import DocumentKind, GeometryStatus, JobType, ProcessingStatus
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Project, Sheet
from app.services import documents as documents_service
from app.services import geometry
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.services.geometry.provider import PypdfGeometryProvider
from app.storage.keys import revision_key
from tests.conftest import FakeObjectStorage

# A4 в точках PDF. Числа известны заранее, поэтому проверяется совпадение, а не «похожесть».
A4_WIDTH = Decimal("595.2760")
A4_HEIGHT = Decimal("841.8900")


def build_pdf(pages: list[tuple[float, float, int]]) -> bytes:
    """Собирает PDF из страниц `(ширина, высота, поворот)`."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for width, height, rotation in pages:
        page = writer.add_blank_page(width=width, height=height)
        if rotation:
            page.rotation = rotation

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def write_pdf(tmp_path: Path, pages: list[tuple[float, float, int]]) -> Path:
    path = tmp_path / "sample.pdf"
    path.write_bytes(build_pdf(pages))
    return path


# --------------------------------------------------------------------------- провайдер


class TestProvider:
    """Чтение геометрии из файла. Без базы: это чистая работа с форматом."""

    def test_portrait_page_keeps_its_size(self, tmp_path: Path) -> None:
        path = write_pdf(tmp_path, [(595.276, 841.89, 0)])

        pages = PypdfGeometryProvider().read(path)

        assert len(pages) == 1
        assert pages[0].display_width_pt == A4_WIDTH
        assert pages[0].display_height_pt == A4_HEIGHT
        assert pages[0].rotation == 0

    def test_landscape_is_wider_than_tall(self, tmp_path: Path) -> None:
        path = write_pdf(tmp_path, [(841.89, 595.276, 0)])

        page = PypdfGeometryProvider().read(path)[0]

        assert page.display_width_pt == A4_HEIGHT
        assert page.display_height_pt == A4_WIDTH

    @pytest.mark.parametrize("rotation", [90, 270])
    def test_quarter_turn_swaps_the_sides(self, tmp_path: Path, rotation: int) -> None:
        """Поворот на четверть меняет стороны местами: именно это видит человек."""
        path = write_pdf(tmp_path, [(595.276, 841.89, rotation)])

        page = PypdfGeometryProvider().read(path)[0]

        assert page.display_width_pt == A4_HEIGHT
        assert page.display_height_pt == A4_WIDTH
        assert page.rotation == rotation

    def test_half_turn_keeps_the_sides(self, tmp_path: Path) -> None:
        path = write_pdf(tmp_path, [(595.276, 841.89, 180)])

        page = PypdfGeometryProvider().read(path)[0]

        assert page.display_width_pt == A4_WIDTH
        assert page.display_height_pt == A4_HEIGHT
        assert page.rotation == 180

    def test_pages_keep_their_order(self, tmp_path: Path) -> None:
        path = write_pdf(tmp_path, [(595.276, 841.89, 0), (841.89, 595.276, 0)])

        pages = PypdfGeometryProvider().read(path)

        assert [page.page_index for page in pages] == [0, 1]
        assert pages[0].display_width_pt < pages[1].display_width_pt

    def test_broken_file_is_a_domain_error(self, tmp_path: Path) -> None:
        """Битый файл — отказ по содержимому, а не трассировка библиотеки наружу."""
        path = tmp_path / "broken.pdf"
        # Сигнатура настоящая, содержимое — мусор: проверку по первым байтам такой файл
        # прошёл бы, и отказать обязан именно разбор.
        path.write_bytes(b"%PDF-1.7\nnot a pdf at all\n%%EOF\n")

        with pytest.raises(DomainError) as error:
            PypdfGeometryProvider().read(path)

        assert error.value.code is ErrorCode.PDF_UNREADABLE

    def test_encrypted_file_is_refused(self, tmp_path: Path) -> None:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=595.276, height=841.89)
        writer.encrypt("secret")
        path = tmp_path / "encrypted.pdf"
        with path.open("wb") as stream:
            writer.write(stream)

        with pytest.raises(DomainError) as error:
            PypdfGeometryProvider().read(path)

        assert error.value.code is ErrorCode.PDF_ENCRYPTED

    def test_negative_rotation_is_normalized(self, tmp_path: Path) -> None:
        """В документах встречается -90: спецификация требует кратности 90, но не знака."""
        path = write_pdf(tmp_path, [(595.276, 841.89, -90)])

        page = PypdfGeometryProvider().read(path)[0]

        assert page.rotation == 270
        assert page.display_width_pt == A4_HEIGHT

    def test_version_is_reported(self) -> None:
        provider = PypdfGeometryProvider()

        assert provider.name == "pypdf"
        assert provider.version.count(".") >= 1


class TestFingerprint:
    """Отпечаток отвечает на вопрос «та ли это геометрия»."""

    def test_same_geometry_gives_the_same_fingerprint(self, tmp_path: Path) -> None:
        provider = PypdfGeometryProvider()
        path = write_pdf(tmp_path, [(595.276, 841.89, 0)])

        first = geometry.fingerprint(provider.read(path)[0], provider)
        second = geometry.fingerprint(provider.read(path)[0], provider)

        assert first == second

    def test_different_size_gives_a_different_fingerprint(self, tmp_path: Path) -> None:
        provider = PypdfGeometryProvider()
        portrait = provider.read(write_pdf(tmp_path, [(595.276, 841.89, 0)]))[0]
        other = tmp_path / "other"
        other.mkdir()
        landscape = provider.read(write_pdf(other, [(841.89, 595.276, 0)]))[0]

        assert geometry.fingerprint(portrait, provider) != geometry.fingerprint(landscape, provider)


class TestIdempotencyKey:
    def test_key_includes_the_parser_version(self) -> None:
        """Смена версии парсера обязана порождать новое задание, а не прятаться за прежним."""
        provider = PypdfGeometryProvider()
        revision_id = uuid.uuid4()

        key = geometry.idempotency_key(revision_id, provider)

        assert str(revision_id) in key
        assert provider.version in key


# ------------------------------------------------------------------- извлечение с базой


async def _pdf_revision(
    session: AsyncSession,
    storage: FakeObjectStorage,
    *,
    project: Project,
    pages: list[tuple[float, float, int]],
    sheets: int | None = None,
    page_count_declared: int | None = None,
) -> DocumentRevision:
    """Ревизия PDF с содержимым в хранилище и, при необходимости, готовыми листами."""
    revision_id = uuid.uuid4()
    document = Document(
        project_id=project.id, display_name="Чертёж.pdf", document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()

    key = revision_key(revision_id, "Чертёж.pdf")
    payload = build_pdf(pages)
    stored = await storage.put_bytes(key, payload, content_type="application/pdf")

    metadata: dict[str, object] = {}
    if page_count_declared is not None:
        metadata["page_count"] = page_count_declared

    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=revision_id,
        source_filename="Чертёж.pdf",
        source_mime="application/pdf",
        source_size=stored.size,
        source_sha256=stored.sha256,
        storage_key=key,
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.PENDING,
        source_metadata=metadata,
    )

    for index in range(sheets or 0):
        session.add(
            Sheet(
                id=geometry.sheet_id_for(revision_id, index),
                revision_id=revision_id,
                page_index=index,
                page_label=str(index + 1),
                # Растровые размеры распознавалки: в расчёте не участвуют никогда.
                width_px=2480,
                height_px=3508,
                rotation=0,
            )
        )
    await session.flush()
    return revision


class TestExtraction:
    async def test_direct_pdf_creates_its_sheets(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        """У обычной загрузки листов нет — до извлечения измерять было нечего."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Прямой PDF"
        )
        revision = await _pdf_revision(
            db_session,
            fake_storage,
            project=project,
            pages=[(595.276, 841.89, 0), (841.89, 595.276, 0)],
        )

        result = await geometry.extract_for_revision(
            db_session,
            fake_storage,
            revision=revision,
            provider=PypdfGeometryProvider(),
        )

        assert result.page_count == 2
        assert result.sheets_created == 2
        assert result.sheets_enriched == 0
        assert revision.geometry_status is GeometryStatus.READY

    async def test_existing_sheets_are_enriched_not_duplicated(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        """Импорт пакета уже создал листы: задание их обогащает, а не дублирует."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Из пакета"
        )
        revision = await _pdf_revision(
            db_session,
            fake_storage,
            project=project,
            pages=[(595.276, 841.89, 0), (841.89, 595.276, 0)],
            sheets=2,
        )

        result = await geometry.extract_for_revision(
            db_session,
            fake_storage,
            revision=revision,
            provider=PypdfGeometryProvider(),
        )

        assert result.sheets_created == 0
        assert result.sheets_enriched == 2

        sheets = await documents_service.list_sheets(db_session, revision_id=revision.id)
        assert len(sheets) == 2
        # Растровые метаданные распознавалки не тронуты: это другое свидетельство.
        assert [sheet.width_px for sheet in sheets] == [2480, 2480]

    async def test_geometry_is_stored_for_every_page(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Геометрия"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 90)]
        )

        await geometry.extract_for_revision(
            db_session,
            fake_storage,
            revision=revision,
            provider=PypdfGeometryProvider(),
        )
        await db_session.flush()

        sheet_id = geometry.sheet_id_for(revision.id, 0)
        found = await documents_service.get_page_geometry(
            db_session, workspace_id=workspace_id, sheet_id=sheet_id
        )
        assert found is not None
        assert found.display_width_pt == A4_HEIGHT
        assert found.display_height_pt == A4_WIDTH
        assert found.pdf_rotation == 90
        assert found.coordinate_space == "pdf_display_points_top_left"
        assert found.source_sha256 == revision.source_sha256
        assert len(found.geometry_fingerprint) == 64

    async def test_repeat_replaces_geometry_without_duplicating(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        """Повторное извлечение заменяет строку: у листа одна геометрия."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Повтор"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 0)]
        )
        provider = PypdfGeometryProvider()

        first = await geometry.extract_for_revision(
            db_session, fake_storage, revision=revision, provider=provider
        )
        second = await geometry.extract_for_revision(
            db_session, fake_storage, revision=revision, provider=provider
        )

        assert first.page_count == second.page_count == 1
        assert second.sheets_created == 0

        found = await documents_service.get_page_geometry(
            db_session, workspace_id=workspace_id, sheet_id=geometry.sheet_id_for(revision.id, 0)
        )
        assert found is not None

    async def test_page_count_mismatch_refuses_everything(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        """Расхождение — отказ целиком: половина размеченного документа хуже, чем ничего."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Расхождение"
        )
        revision = await _pdf_revision(
            db_session,
            fake_storage,
            project=project,
            pages=[(595.276, 841.89, 0)],
            sheets=3,
        )

        with pytest.raises(DomainError) as error:
            await geometry.extract_for_revision(
                db_session,
                fake_storage,
                revision=revision,
                provider=PypdfGeometryProvider(),
            )

        assert error.value.code is ErrorCode.PDF_PAGE_COUNT_MISMATCH
        assert revision.geometry_status is not GeometryStatus.READY

    async def test_declared_page_count_is_checked(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        """Пакет объявил число страниц — оно тоже обязано совпасть."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Объявлено иначе"
        )
        revision = await _pdf_revision(
            db_session,
            fake_storage,
            project=project,
            pages=[(595.276, 841.89, 0)],
            sheets=1,
            page_count_declared=5,
        )

        with pytest.raises(DomainError) as error:
            await geometry.extract_for_revision(
                db_session,
                fake_storage,
                revision=revision,
                provider=PypdfGeometryProvider(),
            )

        assert error.value.code is ErrorCode.PDF_PAGE_COUNT_MISMATCH


class TestScheduling:
    async def test_geometry_job_is_project_scoped(
        self, db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
    ) -> None:
        """У задания геометрии всегда есть владелец: общесистемным оно быть не может."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Задание"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 0)]
        )

        job = await geometry.schedule_extract(db_session, project=project, revision=revision)

        assert job.job_type is JobType.PDF_GEOMETRY_EXTRACT
        assert job.workspace_id == workspace_id
        assert job.project_id == project.id
        assert job.payload["revision_id"] == str(revision.id)

    async def test_repeat_scheduling_returns_the_same_job(
        self, db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Повторная постановка"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 0)]
        )

        first = await geometry.schedule_extract(db_session, project=project, revision=revision)
        second = await geometry.schedule_extract(db_session, project=project, revision=revision)

        assert first.id == second.id
        assert (
            await jobs_service.count_jobs(
                db_session, workspace_id=workspace_id, project_id=project.id
            )
            == 1
        )


class TestWorkerRegistry:
    def test_geometry_job_has_a_handler(self) -> None:
        """Тип без обработчика воркер не возьмёт — задание висело бы в очереди вечно."""
        from app.worker.registry import handler_for, supported_types

        assert JobType.PDF_GEOMETRY_EXTRACT.value in supported_types()
        assert handler_for(JobType.PDF_GEOMETRY_EXTRACT) is not None


class TestGeometryApi:
    async def test_geometry_of_a_foreign_sheet_is_not_found(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        build_api,
        second_workspace,
        workspace_id: uuid.UUID,
    ) -> None:
        """Чужой лист не находится, а не запрещается: 403 подтвердил бы его существование."""
        from app.domain import Role
        from tests.conftest import make_context

        foreign = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Соседский"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=foreign, pages=[(595.276, 841.89, 0)]
        )
        await geometry.extract_for_revision(
            db_session, fake_storage, revision=revision, provider=PypdfGeometryProvider()
        )
        await db_session.commit()

        sheet_id = geometry.sheet_id_for(revision.id, 0)
        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet_id}/geometry")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NOT_FOUND"

    async def test_geometry_before_extraction_is_a_conflict(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        build_api,
        workspace_id: uuid.UUID,
    ) -> None:
        """Лист есть, геометрии нет — это не «не найдено», а «ещё не готово»."""
        from app.domain import Role
        from tests.conftest import make_context

        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без геометрии"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 0)], sheets=1
        )
        await db_session.commit()

        sheet_id = geometry.sheet_id_for(revision.id, 0)
        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet_id}/geometry")

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "GEOMETRY_NOT_READY"

    async def test_geometry_is_returned_with_exact_decimals(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        build_api,
        workspace_id: uuid.UUID,
    ) -> None:
        """Размеры уходят строками: JSON.parse превратил бы их в float64 и потерял канон."""
        from app.domain import Role
        from tests.conftest import make_context

        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="С геометрией"
        )
        revision = await _pdf_revision(
            db_session, fake_storage, project=project, pages=[(595.276, 841.89, 90)]
        )
        await geometry.extract_for_revision(
            db_session, fake_storage, revision=revision, provider=PypdfGeometryProvider()
        )
        await db_session.commit()

        sheet_id = geometry.sheet_id_for(revision.id, 0)
        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet_id}/geometry")

        assert response.status_code == 200
        body = response.json()
        assert body["coordinate_space"] == "pdf_display_points_top_left"
        assert body["pdf_rotation"] == 90
        # Поворот на четверть: стороны переставлены, как их видит человек.
        assert Decimal(str(body["display_width_pt"])) == A4_HEIGHT
        assert Decimal(str(body["display_height_pt"])) == A4_WIDTH
        assert body["parser_name"] == "pypdf"
        assert len(body["geometry_fingerprint"]) == 64
