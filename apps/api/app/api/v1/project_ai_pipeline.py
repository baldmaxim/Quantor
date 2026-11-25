"""Этапы ИИ-проверки проекта (S3-A): сводка по листам и запуск этапов проверки Claude.

Закрыт флагом пространства `cad.export`. Прогон чертежей (этап 1) здесь только показывается: его
ведут автопайплайн и кнопки CAD.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.v1.deps import (
    SessionDep,
    SettingsDep,
    WorkspaceDep,
    require,
    require_feature,
)
from app.auth.permissions import Permission
from app.contracts.project_ai_pipeline import (
    AiRunnableStage,
    AiRunResult,
    ProjectAiPipelineRead,
)
from app.errors import not_found
from app.models import Project
from app.services import project_ai_pipeline
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/ai-pipeline",
    tags=["cad-ai-pipeline"],
    dependencies=[require_feature("cad.export")],
)


async def _project(session: SessionDep, workspace: WorkspaceDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=workspace.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


@router.get(
    "",
    response_model=ProjectAiPipelineRead,
    summary="Этапы ИИ-проверки проекта: сводка и листы",
    dependencies=[require(Permission.PROJECT_READ)],
)
async def read_project_ai_pipeline(
    project_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep, settings: SettingsDep
) -> ProjectAiPipelineRead:
    project = await _project(session, workspace, project_id)
    return await project_ai_pipeline.build(session, project, settings)


@router.post(
    "/stages/{stage}/run",
    response_model=AiRunResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить этап проверки Claude по всем подходящим видам проекта",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def run_project_ai_stage(
    project_id: uuid.UUID,
    stage: AiRunnableStage,
    session: SessionDep,
    workspace: WorkspaceDep,
    settings: SettingsDep,
) -> AiRunResult:
    project = await _project(session, workspace, project_id)
    result = await project_ai_pipeline.run_stage(session, project, settings, stage)
    await session.commit()
    return result
