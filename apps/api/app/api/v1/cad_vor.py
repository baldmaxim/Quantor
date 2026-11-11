"""ВОР Заказчика во вкладке CAD (ADR-0038 п. 5): загрузка, выбор из документов проекта, строки,
связи с группами, сверка листа.

ВОР - только объект сверки: количества строк показываются справочно и на подсчёт конструкций не
влияют, в Facts Registry, calc и таблицы обмера ничего не пишется, во внешние сервисы файл не
уходит. Маршруты закрыты флагом пространства `cad.export` на сервере; доступ - по пространству и
проекту, чужое - 404. ВОР один на проект.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import uuid
from collections.abc import AsyncIterator
from tempfile import SpooledTemporaryFile
from typing import IO, Annotated, Final

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status

from app.api.v1.cad_constructions import _load_walls, _sheet, _totals
from app.api.v1.deps import AuthDep, SessionDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_vor import (
    GROUP_KEY_PATTERN,
    CadVorCoverageRead,
    CadVorDocumentRead,
    CadVorFromRevisionWrite,
    CadVorItemRead,
    CadVorItemsRead,
    CadVorKindHint,
    CadVorLinkRead,
    CadVorLinksWrite,
    CadVorSuggestionRead,
)
from app.errors import DomainError, ErrorCode, not_found
from app.models import Project
from app.services import cad_vor as vor_service
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.cad_vor_import import MAX_FILE_BYTES, VorParseError, parse_workbook
from app.services.uploads import CHUNK_SIZE, ZIP_MAGIC, limit_stream
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError
from app.storage.keys import display_filename, extension_of

XLSX_CONTENT_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(tags=["cad-vor"], dependencies=[require_feature("cad.export")])

GroupKeyPath = Annotated[str, Path(pattern=GROUP_KEY_PATTERN)]
GroupKeyQuery = Annotated[str, Query(pattern=GROUP_KEY_PATTERN)]


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


async def _upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(CHUNK_SIZE):
        yield chunk


async def _file_chunks(source: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := source.read(CHUNK_SIZE):
        yield chunk


async def _import_vor(
    session: SessionDep,
    storage: ObjectStorage,
    context: AuthDep,
    *,
    project: Project,
    name: str,
    chunks: AsyncIterator[bytes],
) -> CadVorDocumentRead:
    """Общий путь импорта ВОР: поток во временный файл, разбор, копия в хранилище, записи в базе.

    Оригинал всегда кладётся в собственный ключ `cad-vor/...`: удаление или замена ВОР не должны
    задевать файл документа проекта, из которого он взят.
    """
    digest = hashlib.sha256()
    size = 0
    document_id = uuid.uuid4()
    key = f"cad-vor/{project.id}/{document_id}.xlsx"
    with SpooledTemporaryFile(max_size=CHUNK_SIZE * 4) as spool:
        async for chunk in limit_stream(chunks, max_size=MAX_FILE_BYTES):
            digest.update(chunk)
            size += len(chunk)
            spool.write(chunk)
        if size == 0:
            raise DomainError(ErrorCode.EMPTY_FILE)
        spool.seek(0)
        if spool.read(len(ZIP_MAGIC)) != ZIP_MAGIC:
            raise DomainError(ErrorCode.CAD_VOR_PARSE_FAILED, "Файл не является книгой XLSX")
        spool.seek(0)
        try:
            parsed = await asyncio.to_thread(parse_workbook, spool)
        except VorParseError as error:
            raise DomainError(ErrorCode.CAD_VOR_PARSE_FAILED, str(error)) from error
        spool.seek(0)
        await storage.put_stream(
            key,
            _file_chunks(spool),
            content_type=XLSX_CONTENT_TYPE,
            original_filename=name,
            metadata={"project-id": str(project.id)},
        )
    try:
        document = await vor_service.create_document(
            session,
            document_id=document_id,
            workspace_id=context.tenant,
            project_id=project.id,
            file_name=name,
            storage_key=key,
            sha256=digest.hexdigest(),
            size=size,
            parsed=parsed,
            user_id=context.principal.user_id,
        )
        response = vor_service.document_read(document)
        await session.commit()
    except Exception:
        # Запись в базе не состоялась - оригинал без документа в хранилище не нужен.
        with contextlib.suppress(StorageUnavailableError):
            await storage.delete(key)
        raise
    return response


@router.post(
    "/projects/{project_id}/cad/vor",
    response_model=CadVorDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить ВОР Заказчика (XLSX) на проект",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def upload_cad_vor(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File(description="Книга Excel .xlsx с ВОР")],
) -> CadVorDocumentRead:
    """Читает файл потоково во временный файл на диске, разбирает и кладёт оригинал в хранилище."""
    project = await _project(session, context, project_id)
    if not file.filename:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Имя файла не передано")
    name = display_filename(file.filename)
    if extension_of(name) != "xlsx":
        raise DomainError(ErrorCode.CAD_VOR_PARSE_FAILED, "ВОР принимается книгой Excel .xlsx")
    return await _import_vor(
        session, storage, context, project=project, name=name, chunks=_upload_chunks(file)
    )


@router.post(
    "/projects/{project_id}/cad/vor/from-revision",
    response_model=CadVorDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Взять ВОР Заказчика из ревизии документа проекта (книга XLSX)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def import_cad_vor_from_revision(
    project_id: uuid.UUID,
    body: CadVorFromRevisionWrite,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadVorDocumentRead:
    """Файл ревизии читается из хранилища потоком; ВОР получает собственную копию файла."""
    project = await _project(session, context, project_id)
    revision = await documents_service.get_revision(
        session, workspace_id=context.tenant, revision_id=body.revision_id
    )
    if revision is None:
        raise not_found("Ревизия")
    document = await documents_service.get_document(
        session, workspace_id=context.tenant, document_id=revision.document_id
    )
    if document is None or document.project_id != project.id:
        raise not_found("Ревизия")
    name = display_filename(revision.source_filename)
    if extension_of(name) != "xlsx":
        raise DomainError(ErrorCode.CAD_VOR_PARSE_FAILED, "ВОР принимается книгой Excel .xlsx")
    try:
        return await _import_vor(
            session,
            storage,
            context,
            project=project,
            name=name,
            chunks=storage.iter_stream(revision.storage_key),
        )
    except ObjectNotFoundError as error:
        raise not_found("Файл ревизии") from error


@router.get(
    "/projects/{project_id}/cad/vor",
    response_model=list[CadVorDocumentRead],
    summary="Документы ВОР проекта; текущий - первый (самый поздний)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_vor_documents(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CadVorDocumentRead]:
    project = await _project(session, context, project_id)
    documents = await vor_service.list_documents(session, project_id=project.id)
    return [vor_service.document_read(document) for document in documents]


@router.get(
    "/projects/{project_id}/cad/vor/links",
    response_model=list[CadVorLinkRead],
    summary="Связи групп конструкций со строками ВОР",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_vor_links(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CadVorLinkRead]:
    project = await _project(session, context, project_id)
    return await vor_service.load_links(session, project_id=project.id)


@router.get(
    "/projects/{project_id}/cad/vor/suggest",
    response_model=list[CadVorSuggestionRead],
    summary="Подсказка: до 10 строк ВОР для группы конструкций (по толщине, виду и материалу)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def suggest_cad_vor_items(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    group_key: GroupKeyQuery,
    document_id: Annotated[
        uuid.UUID | None, Query(description="Документ; по умолчанию - текущий")
    ] = None,
) -> list[CadVorSuggestionRead]:
    """Детерминированное ранжирование без моделей: связь ставит человек."""
    project = await _project(session, context, project_id)
    parts = vor_service.parse_group_key(group_key)
    if parts is None:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Ключ группы вне формата")
    document = (
        await vor_service.current_document(session, project_id=project.id)
        if document_id is None
        else await vor_service.get_document(session, project_id=project.id, document_id=document_id)
    )
    if document is None:
        if document_id is not None:
            raise not_found("Документ ВОР")
        return []
    return await vor_service.suggest(session, document_id=document.id, parts=parts)


@router.put(
    "/projects/{project_id}/cad/vor/links/{group_key}",
    response_model=list[CadVorItemRead],
    summary="Заменить набор строк ВОР, связанных с группой конструкций",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_vor_links(
    project_id: uuid.UUID,
    group_key: GroupKeyPath,
    body: CadVorLinksWrite,
    session: SessionDep,
    context: AuthDep,
) -> list[CadVorItemRead]:
    project = await _project(session, context, project_id)
    wanted = list(dict.fromkeys(body.vor_item_ids))
    known = await vor_service.project_item_ids(session, project_id=project.id, item_ids=wanted)
    if len(known) != len(wanted):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Строки ВОР не найдены в проекте: {len(wanted) - len(known)}",
        )
    await vor_service.replace_links(
        session,
        workspace_id=context.tenant,
        project_id=project.id,
        key=group_key,
        item_ids=wanted,
        user_id=context.principal.user_id,
    )
    links = await vor_service.load_links(session, project_id=project.id)
    response = vor_service.links_by_group(links).get(group_key, [])
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/cad/vor/{document_id}/items",
    response_model=CadVorItemsRead,
    summary="Строки документа ВОР: поиск по наименованию, фильтры по виду и толщине",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_vor_items(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    q: Annotated[str | None, Query(max_length=200, description="Слова наименования")] = None,
    kind: Annotated[CadVorKindHint | None, Query()] = None,
    thickness: Annotated[int | None, Query(ge=1, le=9999, description="Толщина, мм")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CadVorItemsRead:
    project = await _project(session, context, project_id)
    document = await vor_service.get_document(
        session, project_id=project.id, document_id=document_id
    )
    if document is None:
        raise not_found("Документ ВОР")
    total, items = await vor_service.list_items(
        session,
        document_id=document.id,
        q=q,
        kind=kind,
        thickness=thickness,
        limit=limit,
        offset=offset,
    )
    return CadVorItemsRead(total=total, items=[vor_service.item_read(item) for item in items])


@router.delete(
    "/projects/{project_id}/cad/vor/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить документ ВОР вместе со строками и связями",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_cad_vor_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> Response:
    project = await _project(session, context, project_id)
    document = await vor_service.get_document(
        session, project_id=project.id, document_id=document_id
    )
    if document is None:
        raise not_found("Документ ВОР")
    key = document.storage_key
    await vor_service.delete_document(session, document=document)
    await session.commit()
    # Объект без записи в базе безвреден: недоступное хранилище удаление не откатывает.
    with contextlib.suppress(StorageUnavailableError):
        await storage.delete(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/vor-coverage",
    response_model=CadVorCoverageRead,
    summary="Сверка листа с ВОР: какие группы конструкций в ВОР не вошли",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_vor_coverage(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadVorCoverageRead:
    """Количества ВОР с количествами CAD не сравниваются: ВОР на объект, лист - его часть."""
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    result, _levels = await _totals(session, sheet, walls)
    document = await vor_service.current_document(session, project_id=project_id)
    links = await vor_service.load_links(session, project_id=project_id)
    thicknesses = (
        []
        if document is None
        else await vor_service.vor_thicknesses(session, document_id=document.id)
    )
    coverage = vor_service.build_coverage(
        totals=result.totals,
        constructions=result.constructions,
        linked=vor_service.links_by_group(links),
        thicknesses=thicknesses,
        has_vor=document is not None,
    )
    return CadVorCoverageRead(
        job_id=sheet.parent.id,
        page_index=page_index,
        view=view,
        has_vor=document is not None,
        groups=coverage.groups,
        not_in_vor_keys=coverage.not_in_vor_keys,
        vor_thicknesses=thicknesses,
        thickness_not_in_vor=coverage.thickness_not_in_vor,
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
