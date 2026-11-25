"""Автопайплайн пилотных проектов (S0-A): хуки после геометрии/импорта и после паспортов."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.pipeline_auto import PipelineAutoPilot
from app.core.config import Settings
from app.domain import DocumentKind, JobStatus, JobType
from app.models import Document, DocumentRevision, Job, Project, SheetPassport
from app.services import jobs as jobs_service
from app.services import pipeline_auto
from tests.conftest import DEV_WORKSPACE_ID, clean_settings


def _pilot_json(*project_ids: uuid.UUID, limit: int = 3) -> str:
    return json.dumps(
        {"project_ids": [str(item) for item in project_ids], "max_cad_sheets_per_project": limit}
    )


def _settings(raw: str) -> Settings:
    return clean_settings(environment="test", pipeline_auto=raw)


async def _project(session: AsyncSession) -> Project:
    project = Project(workspace_id=DEV_WORKSPACE_ID, name=f"Авто {uuid.uuid4().hex[:6]}")
    session.add(project)
    await session.commit()
    return project


async def _pdf(session: AsyncSession, project: Project, name: str) -> DocumentRevision:
    document = Document(project_id=project.id, display_name=name, document_kind=DocumentKind.PDF)
    session.add(document)
    await session.flush()
    data = b"%PDF-1.7\n" + name.encode()
    revision = DocumentRevision(
        document_id=document.id,
        source_filename=name,
        source_mime="application/pdf",
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest(),
        storage_key=f"test/{uuid.uuid4()}",
    )
    session.add(revision)
    await session.commit()
    return revision


async def _passport(
    session: AsyncSession,
    revision: DocumentRevision,
    page: int,
    kind: str | None,
    status: str = "candidate",
) -> None:
    session.add(
        SheetPassport(
            project_id=await _project_id(session, revision),
            revision_id=revision.id,
            page_index=page,
            file_name=revision.source_filename,
            sheet_kind=kind,
            status=status,
        )
    )
    await session.commit()


async def _project_id(session: AsyncSession, revision: DocumentRevision) -> uuid.UUID:
    document = await session.get(Document, revision.document_id)
    assert document is not None
    return document.project_id


async def _parent(session: AsyncSession, project: Project, job_type: JobType) -> Job:
    job = await jobs_service.enqueue(
        session,
        job_type=job_type,
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )
    await session.commit()
    return job


async def _count(session: AsyncSession, project: Project, job_type: JobType) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.project_id == project.id, Job.job_type == job_type)
        )
        or 0
    )


async def _converted(session: AsyncSession, project: Project) -> list[tuple[str, int]]:
    payloads = await session.scalars(
        select(Job.payload)
        .where(Job.project_id == project.id, Job.job_type == JobType.CAD_PDF_CONVERT)
        .order_by(Job.created_at)
    )
    return [(p["revision_id"], p["params"]["pages"][0]) for p in payloads]


def test_pilot_contract_and_settings() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    assert pipeline_auto.pilot(_settings("")) is None
    assert pipeline_auto.pilot(_settings("{не json")) is None
    assert pipeline_auto.pilot(_settings(json.dumps({"project_ids": []}))) is None
    assert pipeline_auto.pilot(_settings(_pilot_json(first, first))) is None
    assert pipeline_auto.pilot(_settings(_pilot_json(first, limit=201))) is None
    pilot = pipeline_auto.pilot(_settings(json.dumps({"project_ids": [str(first)]})))
    assert pilot == PipelineAutoPilot(project_ids=[first], max_cad_sheets_per_project=3)
    assert pipeline_auto.enabled_for(first, _settings(_pilot_json(first)))
    assert not pipeline_auto.enabled_for(second, _settings(_pilot_json(first)))
    assert not pipeline_auto.enabled_for(None, _settings(_pilot_json(first)))


@pytest.mark.parametrize("job_type", [JobType.PDF_GEOMETRY_EXTRACT, JobType.LEGACY_IMPORT])
async def test_revision_ready_queues_passports_for_pilot_only(
    db_session: AsyncSession, job_type: JobType
) -> None:
    pilot_project, other = await _project(db_session), await _project(db_session)
    settings = _settings(_pilot_json(pilot_project.id))

    parent = await _parent(db_session, pilot_project, job_type)
    await pipeline_auto.after_revision_ready(db_session, parent, settings)
    await pipeline_auto.after_revision_ready(db_session, parent, settings)
    assert await _count(db_session, pilot_project, JobType.SHEET_PASSPORT_EXTRACT) == 1

    foreign = await _parent(db_session, other, job_type)
    await pipeline_auto.after_revision_ready(db_session, foreign, settings)
    await pipeline_auto.after_revision_ready(db_session, parent, _settings(""))
    assert await _count(db_session, other, JobType.SHEET_PASSPORT_EXTRACT) == 0
    assert await _count(db_session, pilot_project, JobType.SHEET_PASSPORT_EXTRACT) == 1


async def test_after_passports_searches_and_converts_only_floor_plans_within_limit(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    first = await _pdf(db_session, project, "А-план.pdf")
    second = await _pdf(db_session, project, "Б-план.pdf")
    await _passport(db_session, first, 0, "section")
    await _passport(db_session, first, 1, "floor_plan")
    await _passport(db_session, first, 2, "floor_plan", status="rejected")
    await _passport(db_session, first, 3, "floor_plan")
    await _passport(db_session, second, 0, "floor_plan")
    await _passport(db_session, second, 1, None)
    settings = _settings(_pilot_json(project.id, limit=3))
    parent = await _parent(db_session, project, JobType.SHEET_PASSPORT_EXTRACT)

    await pipeline_auto.after_passports(db_session, parent, settings)
    await pipeline_auto.after_passports(db_session, parent, settings)

    assert await _count(db_session, project, JobType.DOC_QUESTIONS_SEARCH) == 1
    assert await _converted(db_session, project) == [
        (str(first.id), 1),
        (str(first.id), 3),
        (str(second.id), 0),
    ]
    job = await db_session.scalar(
        select(Job).where(Job.project_id == project.id, Job.job_type == JobType.CAD_PDF_CONVERT)
    )
    assert job is not None
    assert job.payload["params"]["scales"]["1"] == {"auto": True} or job.payload["params"]["scales"]


async def test_after_passports_skips_sheets_with_existing_convert_and_counts_them(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    revision = await _pdf(db_session, project, "А-план.pdf")
    for page in (0, 1, 2):
        await _passport(db_session, revision, page, "floor_plan")
    settings = _settings(_pilot_json(project.id, limit=2))
    parent = await _parent(db_session, project, JobType.SHEET_PASSPORT_EXTRACT)

    await pipeline_auto.after_passports(
        db_session, parent, _settings(_pilot_json(project.id, limit=1))
    )
    assert await _converted(db_session, project) == [(str(revision.id), 0)]
    # Любой статус задания листа считается: упавший лист заново не ставится.
    existing = await db_session.scalar(
        select(Job).where(Job.project_id == project.id, Job.job_type == JobType.CAD_PDF_CONVERT)
    )
    assert existing is not None
    existing.status = JobStatus.FAILED
    await db_session.commit()

    await pipeline_auto.after_passports(db_session, parent, settings)
    assert await _converted(db_session, project) == [(str(revision.id), 0), (str(revision.id), 1)]


async def test_after_passports_does_nothing_outside_pilot_or_with_zero_limit(
    db_session: AsyncSession,
) -> None:
    project, other = await _project(db_session), await _project(db_session)
    revision = await _pdf(db_session, project, "А-план.pdf")
    await _passport(db_session, revision, 0, "floor_plan")
    parent = await _parent(db_session, project, JobType.SHEET_PASSPORT_EXTRACT)

    await pipeline_auto.after_passports(db_session, parent, _settings(""))
    await pipeline_auto.after_passports(db_session, parent, _settings(_pilot_json(other.id)))
    assert await _count(db_session, project, JobType.DOC_QUESTIONS_SEARCH) == 0
    assert await _converted(db_session, project) == []

    await pipeline_auto.after_passports(
        db_session, parent, _settings(_pilot_json(project.id, limit=0))
    )
    assert await _count(db_session, project, JobType.DOC_QUESTIONS_SEARCH) == 1
    assert await _converted(db_session, project) == []


async def test_enqueue_failure_does_not_break_parent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = await _project(db_session)
    revision = await _pdf(db_session, project, "А-план.pdf")
    await _passport(db_session, revision, 0, "floor_plan")
    await _passport(db_session, revision, 1, "floor_plan")
    settings = _settings(_pilot_json(project.id))
    parent = await _parent(db_session, project, JobType.SHEET_PASSPORT_EXTRACT)

    async def boom(*_args: object, **_kwargs: object) -> Job:
        raise SQLAlchemyError("сбой постановки")

    monkeypatch.setattr("app.services.doc_questions.schedule_search", boom)
    monkeypatch.setattr("app.services.cad.schedule_convert", boom)
    monkeypatch.setattr("app.services.sheet_passports.schedule_extract", boom)

    await pipeline_auto.after_passports(db_session, parent, settings)
    await pipeline_auto.after_revision_ready(db_session, parent, settings)
    assert await _converted(db_session, project) == []
    assert parent.status is JobStatus.QUEUED
