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

from app.api.v1.deps import (
    AuthDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    require,
    require_feature,
)
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_style_profiles import (
    MAX_INT32,
    CadStylePreviewCreate,
    CadStylePreviewCreated,
    CadStylePreviewRead,
    CadStyleProfileRead,
    CadStyleSamplesSource,
    CadStyleVersionFromPreview,
    CadStyleVersionRead,
    CadStyleVersionWrite,
)
from app.errors import DomainError, ErrorCode, not_found
from app.models import Document, Job
from app.services import cad as cad_service
from app.services import cad_style_preview as preview_service
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


@router.post(
    "/previews",
    response_model=CadStylePreviewCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить предпросмотр профиля по образцам на листе (снимает исполнитель CAD)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_style_preview(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: CadStylePreviewCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CadStylePreviewCreated:
    document = await _document(session, context, project_id, document_id)
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    revision = await cad_service.revision_in_project(
        session, project=project, revision_id=body.revision_id
    )
    if revision is None or revision.document_id != document.id:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Ревизия не принадлежит документу профиля")
    # Масштаб определяет сервер: калибровка человека либо проверенный автомасштаб, иначе null.
    mm_per_pt, scale_source = await preview_service.resolve_scale(
        session, storage, project=project, revision=revision, page_index=body.page_index
    )
    job = await preview_service.schedule(
        session,
        project=project,
        revision=revision,
        samples=body.samples,
        page_index=body.page_index,
        mm_per_pt=mm_per_pt,
        scale_source=scale_source,
        base_version=await service.current_version(
            session, workspace_id=context.tenant, document_id=document_id
        ),
        settings=settings,
    )
    created = CadStylePreviewCreated(job_id=job.id)
    await session.commit()
    return created


async def _preview_job(
    session: SessionDep,
    context: AuthDep,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job:
    await _document(session, context, project_id, document_id)
    job = await preview_service.get_preview_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        document_id=document_id,
        job_id=job_id,
    )
    if job is None:
        raise not_found("Предпросмотр профиля")
    return job


@router.get(
    "/previews/{job_id}",
    response_model=CadStylePreviewRead,
    summary="Состояние и результат предпросмотра профиля по образцам",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_style_preview(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
) -> CadStylePreviewRead:
    job = await _preview_job(session, context, project_id, document_id, job_id)
    return preview_service.read_of(job)


@router.post(
    "/versions/from-preview",
    response_model=CadStyleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Принять результат предпросмотра: новая версия профиля тома",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_style_version_from_preview(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: CadStyleVersionFromPreview,
    session: SessionDep,
    context: AuthDep,
) -> CadStyleVersionRead:
    job = await _preview_job(session, context, project_id, document_id, body.job_id)
    created = await preview_service.accept(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        document_id=document_id,
        job=job,
        body=body,
        created_by=context.principal.user_id,
    )
    await session.commit()
    return created


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
