"""Чертёж наложением на модель здания (ADR-0053): листы планов этажа и их привязка по осям.

Маршрут закрыт флагом пространства `model.import`; листы берутся из «Здания» (флаг `cad.export`):
без него список пуст с причиной. Доступ - по пространству и проекту, чужое - 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.model_sheets import ModelSheetOverlayList
from app.errors import not_found
from app.services import building_models as models_service
from app.services import feature_flags as flags_service
from app.services import model_sheets as sheets_service
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/model",
    tags=["building-models"],
    dependencies=[require_feature("model.import")],
)


@router.get(
    "/versions/{version_id}/storeys/{storey_key}/sheets",
    response_model=ModelSheetOverlayList,
    summary="Листы планов на отметке этажа и их привязка к сетке осей модели (чертёж наложением)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_storey_sheets(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    storey_key: str,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> ModelSheetOverlayList:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    version = await models_service.get_version(
        session, workspace_id=context.tenant, project_id=project_id, version_id=version_id
    )
    if version is None:
        raise not_found("Версия модели")
    storey = next(
        (
            s
            for s in await models_service.storeys_of(session, version.id)
            if s.storey_key == storey_key
        ),
        None,
    )
    if storey is None:
        raise not_found("Этаж модели")
    flags = await flags_service.evaluate_all(
        session, settings, flags_service.EvaluationContext(workspace_id=context.workspace_id)
    )
    if not flags["cad.export"].value:
        return ModelSheetOverlayList(
            storey_key=storey.storey_key,
            elevation_mm=storey.elevation_mm,
            items=[],
            message="Листы CAD выключены для этого пространства: чертёж наложить не из чего.",
        )
    return await sheets_service.storey_sheets(
        session,
        storage,
        workspace_id=context.tenant,
        project_id=project_id,
        version=version,
        storey=storey,
    )


qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
