"""Профиль оформления проектировщика в пилоте CAD (ADR-0049, решения 1, 2, 5, 6).

Один профиль на том (документ проекта), неизменяемые версии. Маршруты закрыты флагом пространства
`cad.export` на сервере; чтение - право на чтение документов, запись версии - то же право, что у
записи параметров конструкций CAD (`DOCUMENT_UPLOAD`). Чужое пространство, проект или документ -
404.
API профиль не разбирает и ничего в него не подставляет: снимает подписи и применяет профиль движок.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_style_profiles import (
    MAX_INT32,
    CadStyleProfileRead,
    CadStyleSamplesSource,
    CadStyleVersionRead,
    CadStyleVersionWrite,
)
from app.errors import DomainError, ErrorCode, not_found
from app.models import Document
from app.services import cad_style_profiles as service
from app.services import documents as documents_service
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/documents/{document_id}/cad/style-profile",
    tags=["cad-style-profile"],
    dependencies=[require_feature("cad.export")],
)


async def _document(
    session: SessionDep, context: AuthDep, project_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    document = await documents_service.get_document(
        session, workspace_id=context.tenant, document_id=document_id
    )
    if document is None or document.project_id != project.id:
        raise not_found("Документ")
    return document


@router.get(
    "",
    response_model=CadStyleProfileRead,
    summary="Профиль оформления тома: текущая версия и список версий",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_style_profile(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CadStyleProfileRead:
    await _document(session, context, project_id, document_id)
    profile = await service.get_profile(
        session, workspace_id=context.tenant, document_id=document_id
    )
    if profile is None:
        raise not_found("Профиль оформления")
    return profile


@router.get(
    "/versions/{version}",
    response_model=CadStyleVersionRead,
    summary="Версия профиля оформления: объект для движка, хеш, происхождение",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_style_profile_version(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version: Annotated[int, Path(ge=1, le=MAX_INT32)],
    session: SessionDep,
    context: AuthDep,
) -> CadStyleVersionRead:
    await _document(session, context, project_id, document_id)
    found = await service.get_version(
        session, workspace_id=context.tenant, document_id=document_id, version=version
    )
    if found is None:
        raise not_found("Версия профиля оформления")
    return found


@router.post(
    "/versions",
    response_model=CadStyleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать следующую версию профиля оформления (профиль создаётся при первой)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_style_profile_version(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: CadStyleVersionWrite,
    session: SessionDep,
    context: AuthDep,
) -> CadStyleVersionRead:
    document = await _document(session, context, project_id, document_id)
    if isinstance(body.source, CadStyleSamplesSource):
        revision = await documents_service.get_revision(
            session, workspace_id=context.tenant, revision_id=body.source.revision_id
        )
        if revision is None or revision.document_id != document.id:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, "Ревизия не принадлежит документу профиля"
            )
    created = await service.create_version(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        document_id=document_id,
        body=body,
        created_by=context.principal.user_id,
    )
    await session.commit()
    return created


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
