"""Модель здания из пакета QMP (ADR-0053): приём версии по частям, этажи, элементы, части.

Маршруты закрыты флагом пространства `model.import` на сервере; доступ - по пространству и
проекту, чужое - 404. Выгрузка: начать (манифест) → загрузить части → зафиксировать; версия
становится кандидатом и ждёт утверждения человеком. В итоги обмера, MEP и calc модель не входит.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    AuthDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    require,
    require_feature,
)
from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.building_models import (
    MAX_ELEMENTS_PAGE,
    ModelApprove,
    ModelElementRead,
    ModelElementsPage,
    ModelImportCreate,
    ModelImportRead,
    ModelPartRead,
    ModelStoreyRead,
    ModelVersionDetail,
    ModelVersionList,
    ModelVersionRead,
    ModelVersionStarted,
)
from app.domain import AuditAction, ModelVersionStatus
from app.errors import DomainError, ErrorCode, not_found
from app.models import BuildingModelVersion
from app.services import audit as audit_service
from app.services import building_models as models_service
from app.services import model_import as import_service
from app.services import model_package as qmp
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/model",
    tags=["building-models"],
    dependencies=[require_feature("model.import")],
)

_IMMUTABLE = "private, max-age=31536000, immutable"


async def _project(session: AsyncSession, context: AuthContext, project_id: uuid.UUID) -> None:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")


async def _version(
    session: AsyncSession,
    context: AuthContext,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    lock: bool = False,
) -> BuildingModelVersion:
    await _project(session, context, project_id)
    version = await models_service.get_version(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        version_id=version_id,
        lock=lock,
    )
    if version is None:
        raise not_found("Версия модели")
    return version


async def _detail(session: AsyncSession, version: BuildingModelVersion) -> ModelVersionDetail:
    storeys = await models_service.storeys_of(session, version.id)
    parts = await models_service.parts_of(session, version.id)
    base = ModelVersionRead.model_validate(version)
    return ModelVersionDetail(
        **base.model_dump(),
        storeys=[ModelStoreyRead.model_validate(storey) for storey in storeys],
        parts=[ModelPartRead.model_validate(part) for part in parts],
    )


async def _audit(
    session: AsyncSession, context: AuthContext, action: AuditAction, version: BuildingModelVersion
) -> None:
    await audit_service.record(
        session,
        context,
        action=action,
        resource_type="building_model_version",
        resource_id=str(version.id),
        after={"number": version.number, "status": version.status.value},
    )


async def _body_chunks(request: Request) -> AsyncIterator[bytes]:
    async for chunk in request.stream():
        if chunk:
            yield chunk


@router.post(
    "/versions",
    response_model=ModelVersionStarted,
    status_code=status.HTTP_201_CREATED,
    summary="Начать выгрузку модели: принять манифест пакета QMP (повтор возобновляет)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_model_version(
    project_id: uuid.UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    tender_version_id: Annotated[uuid.UUID | None, Query()] = None,
    comment: Annotated[str | None, Query(max_length=models_service.MAX_COMMENT)] = None,
) -> ModelVersionStarted:
    await _project(session, context, project_id)
    body = b""
    async for chunk in _body_chunks(request):
        body += chunk
        if len(body) > models_service.MAX_MANIFEST_BYTES:
            raise DomainError(
                ErrorCode.MODEL_PACKAGE_INVALID,
                "Манифест больше 8 МБ",
                issue={"code": "MANIFEST_SIZE", "where": "manifest.json"},
            )
    version, created = await models_service.start_version(
        session,
        storage,
        workspace_id=context.tenant,
        project_id=project_id,
        user_id=context.principal.user_id,
        manifest_bytes=body,
        tender_version_id=tender_version_id,
        comment=comment,
    )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    missing = (
        await models_service.missing_parts(session, storage, version)
        if version.status is ModelVersionStatus.UPLOADING
        else []
    )
    return ModelVersionStarted(
        **ModelVersionRead.model_validate(version).model_dump(),
        created=created,
        missing_parts=missing,
    )


@router.put(
    "/versions/{version_id}/parts/{path:path}",
    response_model=ModelPartRead,
    summary="Принять часть пакета: размер и sha256 сверяются с манифестом",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_model_part(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    path: str,
    request: Request,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> ModelPartRead:
    version = await _version(session, context, project_id, version_id, lock=True)
    if not qmp.part_path_ok(path):
        raise DomainError(
            ErrorCode.MODEL_PACKAGE_INVALID,
            "Недопустимый путь части",
            issue={"code": "PART_PATH", "where": path[: qmp.MAX_PATH]},
        )
    part = await models_service.store_part(session, storage, version, path, _body_chunks(request))
    await session.commit()
    return ModelPartRead.model_validate(part)


@router.post(
    "/versions/{version_id}/commit",
    response_model=ModelVersionDetail,
    summary="Зафиксировать выгрузку: проверить пакет целиком, версия становится кандидатом",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def commit_model_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> ModelVersionDetail:
    version = await _version(session, context, project_id, version_id, lock=True)
    await models_service.commit_version(session, storage, version)
    await _audit(session, context, AuditAction.MODEL_VERSION_COMMITTED, version)
    await session.commit()
    return await _detail(session, version)


@router.post(
    "/versions/{version_id}/approve",
    response_model=ModelVersionDetail,
    summary="Утвердить кандидата: прежняя утверждённая версия становится заменённой",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def approve_model_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ModelApprove,
    session: SessionDep,
    context: AuthDep,
) -> ModelVersionDetail:
    version = await _version(session, context, project_id, version_id, lock=True)
    await models_service.approve_version(
        session, version, user_id=context.principal.user_id, comment=body.comment
    )
    await _audit(session, context, AuditAction.MODEL_VERSION_APPROVED, version)
    await session.commit()
    return await _detail(session, version)


@router.delete(
    "/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отменить выгрузку, не доведённую до фиксации",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_model_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    version = await _version(session, context, project_id, version_id, lock=True)
    await models_service.delete_uploading(session, storage, version)
    await _audit(session, context, AuditAction.MODEL_VERSION_DELETED, version)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/versions",
    response_model=ModelVersionList,
    summary="Версии модели проекта, новые первыми",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_model_versions(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> ModelVersionList:
    await _project(session, context, project_id)
    rows = await models_service.list_versions(
        session, workspace_id=context.tenant, project_id=project_id
    )
    return ModelVersionList(items=[ModelVersionRead.model_validate(row) for row in rows])


@router.get(
    "/versions/{version_id}",
    response_model=ModelVersionDetail,
    summary="Версия модели с этажами и предупреждениями проверки",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_model_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> ModelVersionDetail:
    version = await _version(session, context, project_id, version_id)
    return await _detail(session, version)


@router.get(
    "/versions/{version_id}/storeys/{storey_key}/elements",
    response_model=ModelElementsPage,
    summary="Элементы этажа: отбор по категории, дисциплине и подстроке имени",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_model_elements(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    storey_key: str,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    category: Annotated[str | None, Query(max_length=32)] = None,
    discipline: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_ELEMENTS_PAGE)] = 100,
) -> ModelElementsPage:
    version = await _version(session, context, project_id, version_id)
    total, rows = await models_service.elements_page(
        session,
        storage,
        version,
        storey_key,
        category=category,
        discipline=discipline,
        query=q,
        offset=offset,
        limit=limit,
    )
    return ModelElementsPage(
        total=total,
        offset=offset,
        limit=limit,
        items=[ModelElementRead.model_validate(row) for row in rows],
    )


@router.get(
    "/versions/{version_id}/parts/{path:path}",
    summary="Часть пакета (GLB, элементы, разрезы): неизменяема, кэшируется по sha256",
    dependencies=[require(Permission.DOCUMENT_READ)],
    response_model=None,
)
async def read_model_part(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    path: str,
    request: Request,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    version = await _version(session, context, project_id, version_id)
    part = await models_service.find_part(session, version, path)
    if part is None:
        raise not_found("Часть модели")
    etag = f'"{part.sha256}"'
    headers = {"ETag": etag, "Cache-Control": _IMMUTABLE}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    headers["Content-Length"] = str(part.size_bytes)
    return StreamingResponse(
        storage.iter_stream(part.storage_key),
        media_type=models_service.content_type_of(part.path),
        headers=headers,
    )


@router.post(
    "/imports",
    response_model=ModelImportRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Построить модель из загруженных IFC проекта (задание генератора cad_model)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_model_import(
    project_id: uuid.UUID,
    body: ModelImportCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> ModelImportRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    job = await import_service.schedule_import(
        session,
        project=project,
        user_id=context.principal.user_id,
        revision_ids=body.revision_ids,
        settings=settings,
    )
    await session.commit()
    return ModelImportRead.of(job)


@router.get(
    "/imports/latest",
    response_model=ModelImportRead,
    summary="Новейшее задание импорта модели проекта: ход, отказ, версия",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_latest_model_import(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> ModelImportRead:
    await _project(session, context, project_id)
    job = await import_service.latest_import_job(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if job is None:
        raise not_found("Импорт модели")
    return ModelImportRead.of(job)


# Отдельная группа под общим требованием опознания; флаг пространства - на самом маршруте.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
