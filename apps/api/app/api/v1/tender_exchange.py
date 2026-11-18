"""Обмен расчётами с TENDER: выпуск базы объекта, загрузка и чтение расчётов (ADR-0051).

Маршрутизатор целиком закрыт пилотным флагом `tender.exchange` на сервере (ADR-0023). Доступ - по
пространству и проекту, чужое - 404. Выпуск базы и отзыв - право координатора (администратора
пространства); загрузка расчёта - инженеру, в том числе по персональному токену `qtk_…`; чтение -
всем, кто видит проект. Выпуск и версия расчёта неизменяемы, отзыв оставляет запись.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, StorageDep, require, require_feature
from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.contracts.tender_exchange import (
    TenderBaseCandidatesRead,
    TenderBaseReleaseCreate,
    TenderBaseReleaseRead,
    TenderBuildingLayersRead,
    TenderCalcsRead,
    TenderCalcVersionRead,
    TenderCalcVersionsRead,
    TenderCalcVersionSummaryRead,
    TenderCalcViewRead,
    TenderViewLayersRead,
    make_view_key,
)
from app.domain import AuditAction
from app.errors import ErrorCode, http_error, not_found
from app.models import Project, TenderBaseRelease, TenderCalc, TenderCalcVersion
from app.services import audit as audit_service
from app.services import projects as projects_service
from app.services import tender_base, tender_calc, tender_calc_import
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

router = APIRouter(
    prefix="/projects/{project_id}/tender",
    tags=["tender-exchange"],
    dependencies=[require_feature("tender.exchange")],
)


async def _project(session: SessionDep, context: AuthContext, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


async def _release(
    session: SessionDep, context: AuthContext, project_id: uuid.UUID, release_id: uuid.UUID
) -> TenderBaseRelease:
    release = await tender_base.get_release(
        session, workspace_id=context.tenant, project_id=project_id, release_id=release_id
    )
    if release is None:
        raise not_found("Выпуск базы")
    return release


async def _version(
    session: SessionDep, context: AuthContext, project_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[TenderCalcVersion, TenderCalc]:
    found = await tender_calc.get_version(
        session, workspace_id=context.tenant, project_id=project_id, version_id=version_id
    )
    if found is None:
        raise not_found("Версия расчёта")
    return found


async def _stream_package(storage: ObjectStorage, key: str, filename: str, sha256: str) -> Response:
    try:
        await storage.stat(key)
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    return StreamingResponse(
        storage.iter_stream(key),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-SHA256": sha256,
        },
    )


# --------------------------------------------------------------------------- база объекта


@router.get(
    "/base/candidates",
    response_model=TenderBaseCandidatesRead,
    summary="Виды проекта, которые можно включить в выпуск базы (этажи «Здания»)",
    dependencies=[require(Permission.TENDER_BASE_RELEASE)],
)
async def list_tender_base_candidates(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep, storage: StorageDep
) -> TenderBaseCandidatesRead:
    project = await _project(session, context, project_id)
    return await tender_base.list_candidates(
        session, storage, workspace_id=project.workspace_id, project_id=project.id
    )


@router.post(
    "/base/releases",
    response_model=TenderBaseReleaseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Выпустить базу объекта: неизменяемый ZIP для TENDER",
    dependencies=[require(Permission.TENDER_BASE_RELEASE)],
)
async def create_tender_base_release(
    project_id: uuid.UUID,
    body: TenderBaseReleaseCreate,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> TenderBaseReleaseRead:
    project = await _project(session, context, project_id)
    release, _author = await tender_base.create_release(
        session, storage, settings, context=context, project=project, body=body
    )
    try:
        await audit_service.record(
            session,
            context,
            action=AuditAction.TENDER_BASE_RELEASED,
            resource_type="tender_base_release",
            resource_id=str(release.id),
            after={
                "project_id": project.id,
                "number": release.number,
                "views": len(release.views),
                "include_dxf": release.include_dxf,
                "manifest_sha256": release.manifest_sha256,
                "package_sha256": release.package_sha256,
            },
        )
        await session.commit()
    except Exception:
        # Строки выпуска не будет: пакет в хранилище никому не нужен.
        await storage.delete(release.package_key)
        raise
    names = await tender_base.user_names(session, [release.released_by])
    return tender_base.release_read(release, names)


@router.get(
    "/base/releases",
    response_model=list[TenderBaseReleaseRead],
    summary="Выпуски базы объекта проекта, новые сверху",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def list_tender_base_releases(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[TenderBaseReleaseRead]:
    project = await _project(session, context, project_id)
    releases = await tender_base.list_releases(
        session, workspace_id=project.workspace_id, project_id=project.id
    )
    names = await tender_base.user_names(
        session, [r.released_by for r in releases] + [r.revoked_by for r in releases]
    )
    return [tender_base.release_read(release, names) for release in releases]


@router.get(
    "/base/coordination.{fmt}",
    summary="Координационный файл (сетка осей и этажи) последнего действующего выпуска базы",
    dependencies=[require(Permission.TENDER_CALC_READ)],
    response_class=Response,
)
async def read_latest_coordination(
    project_id: uuid.UUID,
    fmt: Literal["json", "ifc"],
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    """Для агентов: один запрос вместо «список выпусков -> ZIP -> распаковка». Номер выпуска - в
    заголовке `X-Quantor-Base-Release`; отозванные выпуски пропускаются."""
    project = await _project(session, context, project_id)
    releases = await tender_base.list_releases(
        session, workspace_id=project.workspace_id, project_id=project.id
    )
    live = next((r for r in releases if r.revoked_at is None), None)
    if live is None:
        raise not_found("Действующий выпуск базы")
    try:
        data = await tender_base.read_package_member(
            storage, live.package_key, f"coordination.{fmt}"
        )
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    if data is None:
        raise http_error(
            ErrorCode.NOT_FOUND,
            message="В последнем выпуске нет координационного файла: выпустите базу заново",
        )
    filename = f"coordination-{live.number}.{fmt}"
    return Response(
        content=data,
        media_type="application/json" if fmt == "json" else "application/x-step",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Quantor-Base-Release": str(live.number),
        },
    )


@router.get(
    "/base/releases/{release_id}",
    response_model=TenderBaseReleaseRead,
    summary="Выпуск базы объекта",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def read_tender_base_release(
    project_id: uuid.UUID, release_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderBaseReleaseRead:
    await _project(session, context, project_id)
    release = await _release(session, context, project_id, release_id)
    names = await tender_base.user_names(session, [release.released_by, release.revoked_by])
    return tender_base.release_read(release, names)


@router.get(
    "/base/releases/{release_id}/download",
    summary="Скачать ZIP выпуска базы объекта",
    dependencies=[require(Permission.TENDER_CALC_READ)],
    response_class=StreamingResponse,
)
async def download_tender_base_release(
    project_id: uuid.UUID,
    release_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    await _project(session, context, project_id)
    release = await _release(session, context, project_id, release_id)
    filename = f"quantor-base-{release.number}-{release.released_at.date().isoformat()}.zip"
    return await _stream_package(storage, release.package_key, filename, release.package_sha256)


@router.post(
    "/base/releases/{release_id}/revoke",
    response_model=TenderBaseReleaseRead,
    summary="Отозвать выпуск базы: новые расчёты по нему не принимаются",
    dependencies=[require(Permission.TENDER_BASE_RELEASE)],
)
async def revoke_tender_base_release(
    project_id: uuid.UUID, release_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderBaseReleaseRead:
    await _project(session, context, project_id)
    release = await tender_base.get_release(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        release_id=release_id,
        lock=True,
    )
    if release is None:
        raise not_found("Выпуск базы")
    if await tender_base.revoke_release(session, release, user_id=context.principal.user_id):
        await audit_service.record(
            session,
            context,
            action=AuditAction.TENDER_BASE_REVOKED,
            resource_type="tender_base_release",
            resource_id=str(release.id),
            after={"project_id": project_id, "number": release.number},
        )
    await session.commit()
    names = await tender_base.user_names(session, [release.released_by, release.revoked_by])
    return tender_base.release_read(release, names)


# --------------------------------------------------------------------------- расчёты


@router.post(
    "/calcs/upload",
    response_model=TenderCalcVersionSummaryRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": TenderCalcVersionSummaryRead}},
    summary="Загрузить пакет расчёта: новая версия репозитория или существующая (тот же пакет)",
    dependencies=[require(Permission.TENDER_CALC_UPLOAD)],
)
async def upload_tender_calc(
    project_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="ZIP пакета quantor.tender_calc.v1")],
    response: Response,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> TenderCalcVersionSummaryRead:
    project = await _project(session, context, project_id)
    with tender_calc_import.spool() as target:
        package = await tender_calc_import.receive(file, target)
        result = await tender_calc_import.import_package(
            session, storage, context=context, project=project, package=package
        )
    version, calc = result.version, result.calc
    if result.created:
        await audit_service.record(
            session,
            context,
            action=AuditAction.TENDER_CALC_UPLOADED,
            resource_type="tender_calc_version",
            resource_id=str(version.id),
            after={
                "project_id": project.id,
                "calc_id": calc.id,
                "discipline": calc.discipline,
                "system": calc.system,
                "title": calc.title,
                "number": version.number,
                "label": version.label,
                "package_sha256": version.package_sha256,
                "warnings": len(version.warnings),
            },
        )
        await session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    releases = {version.base_release_id: await _release_number(session, version)}
    names = await tender_base.user_names(session, [version.uploaded_by])
    return tender_calc.summary(version, releases, names)


async def _release_number(session: SessionDep, version: TenderCalcVersion) -> int:
    release = await session.get(TenderBaseRelease, version.base_release_id)
    return release.number if release is not None else 0


@router.get(
    "/calcs",
    response_model=TenderCalcsRead,
    summary="Репозитории расчётов проекта и их действующие версии",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def list_tender_calcs(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderCalcsRead:
    project = await _project(session, context, project_id)
    return TenderCalcsRead(
        calcs=await tender_calc.list_calcs(
            session, workspace_id=project.workspace_id, project_id=project.id
        )
    )


@router.get(
    "/calcs/{calc_id}/versions",
    response_model=TenderCalcVersionsRead,
    summary="Версии репозитория расчёта, новые сверху",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def list_tender_calc_versions(
    project_id: uuid.UUID, calc_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderCalcVersionsRead:
    project = await _project(session, context, project_id)
    calc = await tender_calc.get_calc(
        session, workspace_id=project.workspace_id, project_id=project.id, calc_id=calc_id
    )
    if calc is None:
        raise not_found("Репозиторий расчёта")
    return TenderCalcVersionsRead(versions=await tender_calc.list_versions(session, calc=calc))


@router.get(
    "/calc-versions/{version_id}",
    response_model=TenderCalcVersionRead,
    summary="Версия расчёта: манифест, объёмы, вопросы, виды, предупреждения, разница с прошлой",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def read_tender_calc_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderCalcVersionRead:
    await _project(session, context, project_id)
    version, calc = await _version(session, context, project_id, version_id)
    return await tender_calc.version_read(session, version=version, calc=calc)


@router.get(
    "/calc-versions/{version_id}/views/{revision_id}/{page_index}/{view}",
    response_model=TenderCalcViewRead,
    summary="Геометрия версии расчёта на одном виде",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def read_tender_calc_view(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> TenderCalcViewRead:
    await _project(session, context, project_id)
    version, calc = await _version(session, context, project_id, version_id)
    result = await tender_calc.view_read(
        session,
        storage,
        version=version,
        calc=calc,
        view_key=make_view_key(revision_id, page_index, view),
    )
    if result is None:
        raise not_found("Вид версии расчёта")
    return result


@router.get(
    "/calc-versions/{version_id}/package",
    summary="Скачать ZIP загруженного пакета расчёта",
    dependencies=[require(Permission.TENDER_CALC_READ)],
    response_class=StreamingResponse,
)
async def download_tender_calc_package(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    await _project(session, context, project_id)
    version, calc = await _version(session, context, project_id, version_id)
    filename = f"quantor-calc-{calc.system}-v{version.number}.zip"
    return await _stream_package(storage, version.package_key, filename, version.package_sha256)


@router.post(
    "/calc-versions/{version_id}/withdraw",
    response_model=TenderCalcVersionSummaryRead,
    summary="Отозвать версию расчёта: она уходит из показа, запись остаётся",
    dependencies=[require(Permission.TENDER_CALC_WITHDRAW)],
)
async def withdraw_tender_calc_version(
    project_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderCalcVersionSummaryRead:
    await _project(session, context, project_id)
    found = await tender_calc.get_version(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        version_id=version_id,
        lock=True,
    )
    if found is None:
        raise not_found("Версия расчёта")
    version, calc = found
    if await tender_calc.withdraw(session, version, user_id=context.principal.user_id):
        await audit_service.record(
            session,
            context,
            action=AuditAction.TENDER_CALC_WITHDRAWN,
            resource_type="tender_calc_version",
            resource_id=str(version.id),
            after={
                "project_id": project_id,
                "calc_id": calc.id,
                "system": calc.system,
                "title": calc.title,
                "number": version.number,
            },
        )
    await session.commit()
    releases = {version.base_release_id: await _release_number(session, version)}
    names = await tender_base.user_names(session, [version.uploaded_by])
    return tender_calc.summary(version, releases, names)


# --------------------------------------------------------------------------- слои для показа


@router.get(
    "/view-layers",
    response_model=TenderViewLayersRead,
    summary="Слой «Расчёты» вида: геометрия действующих версий с этим видом",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def read_tender_view_layers(
    project_id: uuid.UUID,
    revision_id: Annotated[uuid.UUID, Query()],
    page_index: Annotated[int, Query(ge=0)],
    view: Annotated[int, Query(ge=0)],
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> TenderViewLayersRead:
    project = await _project(session, context, project_id)
    return TenderViewLayersRead(
        layers=await tender_calc.view_layers(
            session,
            storage,
            workspace_id=project.workspace_id,
            project_id=project.id,
            revision_id=revision_id,
            page_index=page_index,
            view=view,
        )
    )


@router.get(
    "/building-layers",
    response_model=TenderBuildingLayersRead,
    summary="Действующие версии расчётов проекта и их виды (слой в 3D здания)",
    dependencies=[require(Permission.TENDER_CALC_READ)],
)
async def read_tender_building_layers(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TenderBuildingLayersRead:
    project = await _project(session, context, project_id)
    return TenderBuildingLayersRead(
        layers=await tender_calc.building_layers(
            session, workspace_id=project.workspace_id, project_id=project.id
        )
    )
