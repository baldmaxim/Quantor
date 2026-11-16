"""Состояние асинхронных заданий."""

from __future__ import annotations

import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.v1.deps import SessionDep, StorageDep, WorkspaceDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.cad_outline_review import OutlineReviewRead, SourceRole
from app.domain import JobType
from app.errors import not_found
from app.models import Job
from app.schemas import JobRead
from app.services import jobs as jobs_service
from app.storage import ObjectNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Состояние задания",
    dependencies=[require(Permission.JOBS_READ)],
)
async def read_job(job_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep) -> JobRead:
    job = await jobs_service.get_job(session, workspace_id=workspace.tenant, job_id=job_id)
    if job is None:
        raise not_found("Задание")
    return JobRead.model_validate(job)


@router.get(
    "/{job_id}/cad-outline-review",
    response_model=list[OutlineReviewRead],
    summary="Проверки качества обводки по заданию конструкций",
    dependencies=[require(Permission.JOBS_READ), require_feature("cad.export")],
)
async def read_cad_outline_reviews(
    job_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> list[OutlineReviewRead]:
    walls = await jobs_service.get_job(session, workspace_id=workspace.tenant, job_id=job_id)
    if walls is None or walls.job_type != JobType.CAD_WALLS:
        raise not_found("Задание конструкций")
    reviews = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_OUTLINE_REVIEW,
            Job.workspace_id == workspace.tenant,
            Job.project_id == walls.project_id,
            Job.payload["walls_job_id"].astext == str(walls.id),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    return [
        OutlineReviewRead(
            job_id=job.id,
            status=job.status,
            error_message=job.error_message,
            result=job.payload.get("outline_review"),
        )
        for job in reviews
    ]


@router.get(
    "/{job_id}/cad-outline-source/{role}",
    summary="Копия источника, использованного при проверке",
    dependencies=[require(Permission.JOBS_READ), require_feature("cad.export")],
)
async def read_cad_outline_source(
    job_id: uuid.UUID, role: SourceRole, session: SessionDep, workspace: WorkspaceDep,
    storage: StorageDep,
) -> StreamingResponse:
    job = await jobs_service.get_job(session, workspace_id=workspace.tenant, job_id=job_id)
    if job is None or job.job_type != JobType.CAD_OUTLINE_REVIEW:
        raise not_found("Источник проверки")
    source = (job.payload.get("outline_review") or {}).get("sources", {}).get(role, {})
    sha256 = source.get("sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise not_found("Источник проверки")
    key = f"cad/outline-review/sources/{sha256}.md"
    try:
        await storage.stat(key)
    except ObjectNotFoundError as error:
        raise not_found("Копия источника проверки") from error
    filename = quote(source.get("filename", f"{role}.md"), safe="")
    return StreamingResponse(
        storage.iter_stream(key),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
