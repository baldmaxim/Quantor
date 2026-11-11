"""Общее состояние конвейера CAD ревизии (ADR-0036): один ответ на все листы и виды.

Маршрут закрыт флагом пространства `cad.export`; доступ - по пространству, проекту и ревизии,
чужое - 404. Подключается раньше `cad.qa_router`: путь `/pipeline` не должен попасть под
`/{job_id}`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.v1.cad import _scope
from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_pipeline import CadPipelineRead
from app.services import cad_pipeline

router = APIRouter(
    prefix="/projects/{project_id}/revisions/{revision_id}/cad",
    tags=["cad-pipeline"],
    dependencies=[require_feature("cad.export")],
)


@router.get(
    "/pipeline",
    response_model=CadPipelineRead,
    summary="Состояние конвейера CAD ревизии: этапы по каждому листу и виду",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_pipeline(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
) -> CadPipelineRead:
    await _scope(session, context, project_id, revision_id)
    return await cad_pipeline.build_pipeline(
        session, workspace_id=context.tenant, project_id=project_id, revision_id=revision_id
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
