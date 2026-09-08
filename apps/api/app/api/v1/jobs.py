"""Состояние асинхронных заданий."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.v1.deps import SessionDep, WorkspaceDep, require
from app.auth.permissions import Permission
from app.errors import not_found
from app.schemas import JobRead
from app.services import jobs as jobs_service

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
