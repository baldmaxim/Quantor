"""API версий тендера (ADR-0035, этап M2).

Версия тендера — замороженный комплект ревизий документов проекта. Чтение — право просмотра
проекта, изменение и заморозка — право редактирования проекта. Все изменения пишутся в журнал
аудита в той же транзакции. Маршрутизатор целиком закрыт пилотным флагом `tender.versions`
на сервере (ADR-0023).

Запись в HUBTender не выполняется: сервер только читает тендер, чтобы сверить его номер с номером
проекта и записать номер версии той стороны.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.v1.deps import (
    AuthDep,
    OptionalTenderHubDep,
    SessionDep,
    require,
    require_feature,
)
from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.contracts.tender_versions import (
    TenderHubCandidateRead,
    TenderVersionCreate,
    TenderVersionDocumentPut,
    TenderVersionRead,
    TenderVersionSummaryRead,
    TenderVersionUpdate,
)
from app.domain import AuditAction
from app.errors import not_found
from app.models import Project, TenderVersion
from app.services import audit as audit_service
from app.services import projects as projects_service
from app.services import tender_versions as versions_service

router = APIRouter(
    prefix="/projects/{project_id}/tender-versions",
    tags=["tender-versions"],
    dependencies=[require_feature("tender.versions")],
)


async def _project(session: SessionDep, context: AuthContext, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


async def _version(
    session: SessionDep, project: Project, version_id: uuid.UUID, *, lock: bool
) -> TenderVersion:
    version = await versions_service.get_version(
        session, project_id=project.id, version_id=version_id, lock=lock
    )
    if version is None:
        raise not_found("Версия")
    return version


async def _audit(
    session: SessionDep,
    context: AuthContext,
    action: AuditAction,
    version: TenderVersion,
    **extra: str | int | bool | None,
) -> None:
    await audit_service.record(
        session,
        context,
        action=action,
        resource_type="tender_version",
        resource_id=str(version.id),
        after={
            "project_id": version.project_id,
            "number": version.number,
            "status": version.status.value,
            "external_tender_id": version.external_tender_id,
            "external_version": version.external_version,
            "manifest_sha256": version.manifest_sha256,
            **extra,
        },
    )


@router.get(
    "",
    response_model=list[TenderVersionSummaryRead],
    summary="Версии тендера проекта",
    dependencies=[require(Permission.PROJECT_READ)],
)
async def list_tender_versions(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[TenderVersionSummaryRead]:
    project = await _project(session, context, project_id)
    return await versions_service.list_versions(session, project_id=project.id)


# Маршрут без параметра пути стоит раньше `/{version_id}`: иначе «hub-candidates» разбирался бы
# как идентификатор версии.
@router.get(
    "/hub-candidates",
    response_model=list[TenderHubCandidateRead],
    summary="Строки HUBTender с номером тендера проекта",
    dependencies=[require(Permission.PROJECT_READ)],
)
async def list_hub_candidates(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    client: OptionalTenderHubDep,
) -> list[TenderHubCandidateRead]:
    project = await _project(session, context, project_id)
    return await versions_service.hub_candidates(project, client)


@router.post(
    "",
    response_model=TenderVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать черновик версии",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def create_tender_version(
    project_id: uuid.UUID,
    payload: TenderVersionCreate,
    session: SessionDep,
    context: AuthDep,
    client: OptionalTenderHubDep,
) -> TenderVersionRead:
    project = await _project(session, context, project_id)
    version = await versions_service.create_draft(
        session,
        project=project,
        author_id=context.principal.user_id,
        label=payload.label,
        external_tender_id=payload.external_tender_id,
        client=client,
    )
    await _audit(session, context, AuditAction.TENDER_VERSION_CREATED, version)
    result = await versions_service.read_version(session, project=project, version=version)
    await session.commit()
    return result


@router.get(
    "/{version_id}",
    response_model=TenderVersionRead,
    summary="Версия тендера с составом",
    dependencies=[require(Permission.PROJECT_READ)],
)
async def read_tender_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderVersionRead:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=False)
    return await versions_service.read_version(session, project=project, version=version)


@router.patch(
    "/{version_id}",
    response_model=TenderVersionRead,
    summary="Изменить черновик версии",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def update_tender_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: TenderVersionUpdate,
    session: SessionDep,
    context: AuthDep,
    client: OptionalTenderHubDep,
) -> TenderVersionRead:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=True)
    await versions_service.update_draft(
        session,
        project=project,
        version=version,
        fields=set(payload.model_fields_set),
        label=payload.label,
        external_tender_id=payload.external_tender_id,
        client=client,
    )
    await _audit(session, context, AuditAction.TENDER_VERSION_UPDATED, version)
    result = await versions_service.read_version(session, project=project, version=version)
    await session.commit()
    return result


@router.delete(
    "/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить черновик версии",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def delete_tender_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> Response:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=True)
    await versions_service.delete_draft(session, version=version)
    await _audit(session, context, AuditAction.TENDER_VERSION_DELETED, version)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{version_id}/documents/{document_id}",
    response_model=TenderVersionRead,
    summary="Выбрать ревизию документа в составе черновика",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def put_tender_version_document(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: TenderVersionDocumentPut,
    session: SessionDep,
    context: AuthDep,
) -> TenderVersionRead:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=True)
    await versions_service.set_document(
        session, project=project, version=version, document_id=document_id, payload=payload
    )
    await _audit(
        session,
        context,
        AuditAction.TENDER_VERSION_DOCUMENT_SET,
        version,
        document_id=str(document_id),
        document_revision_id=str(payload.document_revision_id),
        section=payload.section,
        use_in_model=payload.use_in_model,
    )
    result = await versions_service.read_version(session, project=project, version=version)
    await session.commit()
    return result


@router.delete(
    "/{version_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать документ из состава черновика",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def delete_tender_version_document(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
) -> Response:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=True)
    await versions_service.remove_document(session, version=version, document_id=document_id)
    await _audit(
        session,
        context,
        AuditAction.TENDER_VERSION_DOCUMENT_REMOVED,
        version,
        document_id=str(document_id),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{version_id}/freeze",
    response_model=TenderVersionRead,
    summary="Заморозить версию",
    dependencies=[require(Permission.PROJECT_UPDATE)],
)
async def freeze_tender_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderVersionRead:
    project = await _project(session, context, project_id)
    version = await _version(session, project, version_id, lock=True)
    await versions_service.freeze(
        session, project=project, version=version, actor_id=context.principal.user_id
    )
    await _audit(session, context, AuditAction.TENDER_VERSION_FROZEN, version)
    result = await versions_service.read_version(session, project=project, version=version)
    await session.commit()
    return result
