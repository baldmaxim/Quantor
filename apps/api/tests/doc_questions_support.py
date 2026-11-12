"""Помощники тестов вопросов к документации (В3): проект, PDF, текст страниц, паспорта, поиск."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import DocumentKind, JobType
from app.models import Document, DocumentRevision, Job, RevisionPageText, SheetPassport
from app.services import jobs as jobs_service
from app.services.consistency.page_texts import PageTextWriter, store_page_text_file
from app.worker.registry import handler_for
from tests.conftest import FakeObjectStorage, clean_settings

PARSER = "test.parser"
KR_PDF = "КР ПЗ.pdf"
AR_PDF = "АР ПЗ.pdf"
EMPTY_PDF = "ИОС2 без текста.pdf"
SLAB_TEXT = "Толщина монолитной плиты перекрытия типового этажа 200 мм."
CEILING_TEXT = "Высота подвесного потолка в коридорах 2700 мм от уровня чистого пола."


def doc_settings(*, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test", feature_flags="project.consistency=true" if flag else ""
    )


async def make_project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": f"Вопросы {uuid.uuid4().hex[:6]}"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def add_pdf(
    session: AsyncSession, storage: FakeObjectStorage, project_id: str, name: str
) -> DocumentRevision:
    document = Document(
        project_id=uuid.UUID(project_id), display_name=name, document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()
    payload = b"%PDF-1.7\n" + name.encode()
    key = f"test/{uuid.uuid4()}"
    storage.objects[key] = payload
    revision = DocumentRevision(
        document_id=document.id,
        source_filename=name,
        source_mime="application/pdf",
        source_size=len(payload),
        source_sha256=hashlib.sha256(payload + key.encode()).hexdigest(),
        storage_key=key,
    )
    session.add(revision)
    await session.commit()
    return revision


async def add_text(
    session: AsyncSession,
    storage: FakeObjectStorage,
    tmp_path: Path,
    project_id: str,
    revision: DocumentRevision,
    pages: list[str],
) -> None:
    """Текст страниц ревизии в хранилище и строка-указатель, как после разбора паспортов."""
    path = tmp_path / f"{revision.id}.jsonl.gz"
    with PageTextWriter(path, PARSER) as writer:
        for index, text in enumerate(pages):
            writer.add(index, str(index + 1), text)
    stored = await store_page_text_file(
        storage,
        project_id=uuid.UUID(project_id),
        revision_id=revision.id,
        path=path,
        parser_version=PARSER,
        max_bytes=10 * 1024 * 1024,
    )
    session.add(
        RevisionPageText(
            revision_id=revision.id,
            project_id=uuid.UUID(project_id),
            storage_key=stored.storage_key,
            format=stored.format,
            parser_version=stored.parser_version,
            pages=stored.pages,
            empty_pages=stored.empty_pages,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
    )
    await session.commit()


async def add_passport(
    session: AsyncSession,
    project_id: str,
    revision: DocumentRevision,
    page_index: int,
    *,
    section_mark: str,
    sheet_kind: str = "text",
    building: str | None = None,
    section: str | None = None,
    status: str = "candidate",
) -> None:
    session.add(
        SheetPassport(
            project_id=uuid.UUID(project_id),
            revision_id=revision.id,
            page_index=page_index,
            file_name=revision.source_filename,
            section_mark=section_mark,
            sheet_kind=sheet_kind,
            building=building,
            section=section,
            status=status,
            evidence={},
            versions={},
        )
    )
    await session.commit()


async def run_search_job(session: AsyncSession, storage: FakeObjectStorage) -> Job:
    """Один цикл основного исполнителя: захват задания поиска и его обработчик."""
    job = await jobs_service.claim(
        session,
        worker_id="doc-questions-test",
        job_types=[JobType.DOC_QUESTIONS_SEARCH.value],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None
    handler = handler_for(job.job_type)
    assert handler is not None
    job = await handler(session, job, storage, clean_settings())
    await session.commit()
    return job


async def search(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage, project_id: str
) -> Job:
    response = await api.post(f"/api/v1/projects/{project_id}/doc-questions/search")
    assert response.status_code == 202, response.text
    job = await run_search_job(session, storage)
    assert str(job.id) == response.json()["id"]
    return job


def questions_url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/doc-questions{tail}"


async def standard_project(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    tmp_path: Path,
) -> tuple[str, dict[str, DocumentRevision]]:
    """Проект: КР ПЗ (плита 200 мм), АР ПЗ (потолок 2700 мм, две страницы), PDF без текста."""
    project_id = await make_project(api)
    kr = await add_pdf(session, storage, project_id, KR_PDF)
    ar = await add_pdf(session, storage, project_id, AR_PDF)
    empty = await add_pdf(session, storage, project_id, EMPTY_PDF)
    await add_text(session, storage, tmp_path, project_id, kr, [SLAB_TEXT])
    await add_text(session, storage, tmp_path, project_id, ar, ["Общие данные", CEILING_TEXT])
    await add_passport(session, project_id, kr, 0, section_mark="КР", building="9", section="3")
    await add_passport(session, project_id, ar, 0, section_mark="АР")
    await add_passport(session, project_id, ar, 1, section_mark="АР", building="9", section="3")
    return project_id, {"kr": kr, "ar": ar, "empty": empty}
