"""PDF -> CAD (пилот, ADR-0036): постановка, состояние, скачивание артефактов, замечания.

Маршрутизатор подключён всегда; все его эндпоинты (задания, файлы, диагностика и превью вида,
замечания) лежат под одним `router` и закрыты флагом пространства `cad.export` на сервере.
Доступ — по пространству, проекту и ревизии; чужое — 404. Артефакты отдаются только через API
после этой проверки; ключи и presigned-адреса наружу не выходят.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

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
from app.contracts.cad import (
    CadArtifactRead,
    CadConvertCreate,
    CadEventRead,
    CadEventsRead,
    CadJobListRead,
    CadJobRead,
    CadPreviewPathRead,
    CadPreviewRead,
    CadRemarkRead,
    CadRemarksFile,
    CadRemarksImportRead,
    CadRemarkWrite,
    CadViewDiagnosticsRead,
    summary_of,
)
from app.contracts.cad_mep import view_mep_read
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, http_error, not_found
from app.models import CadRemark, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_preview_cache, cad_progress, cad_remarks, cad_views
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

router = APIRouter(
    prefix="/projects/{project_id}/revisions/{revision_id}/cad",
    tags=["cad-qa"],
    dependencies=[require_feature("cad.export")],
)


async def _scope(
    session: SessionDep, context: AuthContext, project_id: uuid.UUID, revision_id: uuid.UUID
) -> tuple[Project, DocumentRevision]:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    revision = await cad_service.revision_in_project(
        session, project=project, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")
    return project, revision


async def _job(
    session: SessionDep,
    context: AuthContext,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job:
    await _scope(session, context, project_id, revision_id)
    job = await cad_service.get_cad_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        job_id=job_id,
    )
    if job is None:
        raise not_found("Задание")
    return job


async def job_read(session: SessionDep, job: Job) -> CadJobRead:
    """Задание вместе с решениями человека и route-заданиями его видов."""
    return CadJobRead.of(job, await cad_mep_service.load_state(session, [job]))


async def _frame_source(
    session: SessionDep,
    context: AuthContext,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job: Job,
    attempt: int,
) -> tuple[Job, int]:
    """Где лежат scale.json и cad_checks.json вида: у route-задания - у его родителя.

    Трассы строятся в тех же координатах (мм), что DXF вида родителя; кадр PDF -> DXF тот же.
    """
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        return job, attempt
    parent_id = cad_mep_service.parent_job_id_of(job)
    parent_attempt = cad_mep_service.payload_int(job, "parent_attempt")
    parent = (
        await cad_service.get_cad_job(
            session,
            workspace_id=context.tenant,
            project_id=project_id,
            revision_id=revision_id,
            job_id=parent_id,
        )
        if parent_id is not None
        else None
    )
    if parent is None or parent_attempt is None:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "родительский результат трасс недоступен")
    return parent, parent_attempt


@router.post(
    "",
    response_model=CadJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить преобразование PDF ревизии в DXF (QA)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_job(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    body: CadConvertCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> CadJobRead:
    project, revision = await _scope(session, context, project_id, revision_id)
    pages = cad_service.validate_request(
        body.pages, finishes=body.finishes, schedules=body.schedules
    )
    job = await cad_service.schedule_convert(
        session,
        project=project,
        revision=revision,
        pages=pages,
        settings=settings,
        auto_scale=body.auto_scale,
    )
    await session.commit()
    return await job_read(session, job)


@router.get(
    "/{job_id}",
    response_model=CadJobRead,
    summary="Состояние преобразования в DXF (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_job(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
) -> CadJobRead:
    return await job_read(session, await _job(session, context, project_id, revision_id, job_id))


@router.get(
    "/{job_id}/artifacts/{name:path}",
    summary="Файл результата преобразования в DXF (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
    response_class=StreamingResponse,
)
async def download_cad_artifact(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    name: str,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    # Прошлая попытка route-задания (после пересчёта) - только просмотр.
    attempt_no: int | None = Query(default=None, ge=1, alias="attempt"),
) -> StreamingResponse:
    await _scope(session, context, project_id, revision_id)
    # Скачивание шире общего доступа к заданию: файлы отдаёт и задание 3D DXF этажа (ADR-0039).
    job = await cad_service.get_cad_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        job_id=job_id,
        job_types=cad_service.CAD_ARTIFACT_JOB_TYPES,
    )
    if job is None:
        raise not_found("Задание")
    if attempt_no is None and job.status is not JobStatus.SUCCEEDED:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    artifact = cad_service.find_artifact(job, name, attempt_no)
    if artifact is None:
        raise not_found("Файл")
    attempt = (
        cad_service.result_of(job).get("attempt")
        if attempt_no is None
        else cad_service.result_for_attempt(job, attempt_no).get("attempt")
    )
    if type(attempt) is not int or attempt < 1:
        raise not_found("Файл")
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    if artifact.get("key") != key:
        raise not_found("Файл")
    # DXF трасс - только после принятия человеком; превью и candidate.json - кандидат для проверки.
    if name.endswith("/" + cad_mep_service.ROUTES_DXF) and not (
        await cad_mep_service.routes_download_allowed(session, job, attempt)
    ):
        raise DomainError(ErrorCode.CAD_ROUTES_NOT_ACCEPTED)
    try:
        await storage.stat(key)
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    filename = name.replace("/", "_")
    return StreamingResponse(
        storage.iter_stream(key),
        media_type=cad_service.content_type_for(name),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-SHA256": str(artifact["sha256"]),
            "X-Quantor-Review-Required": "true",
        },
    )


@router.get(
    "",
    response_model=CadJobListRead,
    summary="Задания PDF -> DXF ревизии: очередь и история (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_jobs(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
) -> CadJobListRead:
    await _scope(session, context, project_id, revision_id)
    jobs = await cad_service.list_cad_jobs(
        session, workspace_id=context.tenant, project_id=project_id, revision_id=revision_id
    )
    return CadJobListRead(items=[summary_of(job) for job in jobs], server_time=_now())


@router.post(
    "/{job_id}/retry",
    response_model=CadJobRead,
    summary="Повторить отказавшее преобразование новой попыткой того же задания (QA)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def retry_cad_job(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> CadJobRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    # Строка под блокировкой: два одновременных нажатия не ставят задание дважды.
    await session.refresh(job, with_for_update=True)
    retryable, reason = cad_service.retry_state(job)
    if not retryable:
        raise DomainError(ErrorCode.JOB_NOT_RETRYABLE, reason or "Повтор недоступен")
    if job.job_type is JobType.CAD_PDF_CONVERT:
        cad_service.refresh_limits(job, settings)
    await jobs_service.retry(session, job=job)
    await session.commit()
    return await job_read(session, job)


@router.get(
    "/{job_id}/events",
    response_model=CadEventsRead,
    summary="События попытки по порядку номеров, после курсора (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_events(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    attempt: int | None = Query(default=None, ge=1),
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
) -> CadEventsRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    records = cad_progress.attempts_of(job.payload)
    number = attempt if attempt is not None else (records[-1]["attempt"] if records else 0)
    record = cad_progress.attempt_record(job.payload, number) if number else None
    if record is None:
        if attempt is not None and attempt != job.attempt:
            raise not_found("Попытка")
        return CadEventsRead(job_id=job.id, attempt=number, events=[], last_seq=0, finished=False)
    events = [
        CadEventRead.model_validate(event)
        for event in record.get("events", [])
        if isinstance(event, dict) and int(event.get("seq", 0)) > after_seq
    ][:limit]
    live = job.status is JobStatus.RUNNING and job.attempt == number
    return CadEventsRead(
        job_id=job.id,
        attempt=number,
        events=events,
        last_seq=int(record.get("last_seq", 0)),
        finished=record.get("finished_at") is not None or not live,
    )


def _now() -> datetime:
    return cad_progress.now()


def _succeeded_view(
    job: Job, page_index: int, view: int, attempt: int | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Итог и вид текущей успешной попытки.

    Прошлая попытка берётся только по явному номеру (просмотр после пересчёта трасс) и только
    если у неё есть успешный итог.
    """
    if attempt is None:
        if job.status is not JobStatus.SUCCEEDED:
            raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
        result = cad_service.current_result(job)
    else:
        result = cad_service.result_for_attempt(job, attempt)
        if not result or result.get("result_status") == "failed":
            raise not_found("Попытка")
    for page in result.get("pages", []):
        if page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if row.get("view") == view:
                return result, row
    raise not_found("Вид")


async def _read_artifact_json(
    storage: ObjectStorage, job: Job, revision_id: uuid.UUID, attempt: int, name: str
) -> Any:
    artifact = cad_service.find_artifact(job, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    if artifact.get("key") != key:
        raise not_found("Файл")
    try:
        return await cad_views.read_json(storage, key)
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (cad_views.ArtifactTooLargeError, ValueError) as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "файл диагностики не читается") from error


@router.get(
    "/{job_id}/views/{page_index}/{view}",
    response_model=CadViewDiagnosticsRead,
    summary="Диагностика вида: масштаб, кадр координат, проверки и файлы (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_view(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    attempt_no: int | None = Query(default=None, ge=1, alias="attempt"),
) -> CadViewDiagnosticsRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    result, row = _succeeded_view(job, page_index, view, attempt_no)
    attempt = int(result["attempt"])
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise not_found("Вид") from error
    is_route = job.job_type is JobType.CAD_MEP_ROUTE
    files = [
        CadArtifactRead(name=a["name"], sha256=a["sha256"], size=a["size"])
        for a in result.get("artifacts", [])
        if str(a.get("name", "")).startswith(folder + "/")
    ]
    # Масштаб и кадр координат у route-задания - родительские (те же мм, что в DXF вида).
    source, source_attempt = await _frame_source(
        session, context, project_id, revision_id, job, attempt
    )
    scale = cad_views.scale_from(
        await _read_artifact_json(
            storage, source, revision_id, source_attempt, f"{folder}/scale.json"
        )
    )
    cad_checks = await _read_artifact_json(
        storage, source, revision_id, source_attempt, f"{folder}/cad_checks.json"
    )
    checks = (
        None
        if is_route
        else await _read_artifact_json(storage, job, revision_id, attempt, f"{folder}/checks.json")
    )
    dxf_name = f"{folder}/{cad_mep_service.ROUTES_DXF if is_route else 'plan_candidates.dxf'}"
    mep = view_mep_read(
        job, attempt, page_index, view, await cad_mep_service.load_state(session, [job])
    )
    return CadViewDiagnosticsRead(
        job_id=job.id,
        attempt=attempt,
        page_index=page_index,
        legacy_pdf_page=page_index + 1,
        view=view,
        status=str(row.get("status")),
        scale_status=row.get("scale_status"),
        result_status=result.get("result_status"),
        files=files,
        dxf=next((f for f in files if f.name == dxf_name), None),
        preview_available=any(f.name == f"{folder}/preview.json" for f in files),
        scale=scale,
        frame=cad_views.frame_from(scale, cad_checks),
        checks=None if is_route else cad_views.checks_from(cad_checks, checks),
        review_required=True,
        engineering_acceptance="not_accepted",
        approval=mep.approval,
        acceptance=mep.acceptance,
        route_jobs=mep.route_jobs,
        revoked_decisions=mep.revoked_decisions,
    )


# Неизменяемый ответ: браузер каждый раз сверяет по ETag (дешёвый 304), без устаревших копий.
PREVIEW_CACHE_CONTROL = "private, no-cache"


@router.get(
    "/{job_id}/views/{page_index}/{view}/preview",
    response_model=CadPreviewRead,
    summary="Геометрия выпущенного DXF вида для просмотра поверх PDF (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_preview(
    request: Request,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    attempt_no: int | None = Query(default=None, ge=1, alias="attempt"),
) -> Response:
    job = await _job(session, context, project_id, revision_id, job_id)
    result, _row = _succeeded_view(job, page_index, view, attempt_no)
    attempt = int(result["attempt"])
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise not_found("Вид") from error
    is_route = job.job_type is JobType.CAD_MEP_ROUTE
    dxf_name = f"{folder}/{cad_mep_service.ROUTES_DXF if is_route else 'plan_candidates.dxf'}"
    dxf = cad_service.find_artifact(job, dxf_name, attempt)
    preview_name = f"{folder}/preview.json"
    preview_file = cad_service.find_artifact(job, preview_name, attempt)
    # Завершённое задание неизменяемо (DXF и preview.json привязаны хешем): ответ кешируется
    # в процессе и отдаётся с ETag. Доступ к заданию проверен выше, до обращения к кешу.
    cache_key = (
        cad_preview_cache.make_key(
            job.id,
            attempt,
            page_index,
            view,
            str(dxf.get("sha256")),
            str(preview_file.get("sha256")),
        )
        if job.status is JobStatus.SUCCEEDED and dxf is not None and preview_file is not None
        else None
    )
    headers: dict[str, str] = {}
    if cache_key is not None:
        etag = cad_preview_cache.etag_of(cache_key)
        headers = {"ETag": etag, "Cache-Control": PREVIEW_CACHE_CONTROL}
        if cad_preview_cache.etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
        cached = cad_preview_cache.preview_cache.get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="application/json", headers=headers)
    raw = await _read_artifact_json(storage, job, revision_id, attempt, preview_name)
    if dxf is None or raw is None:
        raise not_found("Предпросмотр")
    # Предпросмотр обязан описывать ровно тот DXF, что выпущен этой попыткой. У трасс генератор
    # может не указывать DXF в превью: тогда оно привязано к заданию, но уж если указал -
    # сверяется так же строго.
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != "quantor.cad_engine.preview.v1"
        or raw.get("units") != "mm"
        or (("dxf" in raw or not is_route) and raw.get("dxf") != dxf_name)
        or (("dxf_sha256" in raw or not is_route) and raw.get("dxf_sha256") != dxf.get("sha256"))
    ):
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "предпросмотр не относится к DXF попытки")
    layers = [str(name)[:64] for name in raw.get("layers", []) if isinstance(name, str)]
    try:
        paths = [CadPreviewPathRead.model_validate(path) for path in raw.get("paths", [])]
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "предпросмотр вне контракта") from error
    if any(p.layer >= len(layers) or len(p.points) % 2 or len(p.points) < 4 for p in paths):
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "предпросмотр вне контракта")
    source, source_attempt = await _frame_source(
        session, context, project_id, revision_id, job, attempt
    )
    scale = cad_views.scale_from(
        await _read_artifact_json(
            storage, source, revision_id, source_attempt, f"{folder}/scale.json"
        )
    )
    cad_checks = await _read_artifact_json(
        storage, source, revision_id, source_attempt, f"{folder}/cad_checks.json"
    )
    bbox = raw.get("bbox")
    body = (
        CadPreviewRead(
            job_id=job.id,
            attempt=attempt,
            page_index=page_index,
            view=view,
            units="mm",
            dxf_sha256=str(dxf["sha256"]),
            layers=layers,
            paths=paths,
            point_count=sum(len(p.points) // 2 for p in paths),
            truncated=raw.get("truncated") is True,
            flatten_mm=float(raw.get("flatten_mm") or 0),
            bbox=tuple(bbox) if isinstance(bbox, list) and len(bbox) == 4 else None,
            frame=cad_views.frame_from(scale, cad_checks),
        )
        .model_dump_json()
        .encode()
    )
    if cache_key is not None:
        cad_preview_cache.preview_cache.put(cache_key, body)
    return Response(content=body, media_type="application/json", headers=headers)


# ------------------------------------------------------------------ замечания проверяющего

RemarkKey = Path(min_length=1, max_length=64)


def _remark_read(row: CadRemark) -> CadRemarkRead:
    # Через разбор словаря: тип и статус из базы проверяются по тем же Literal, что в контракте.
    return CadRemarkRead.model_validate(
        {
            "id": row.remark_key,
            "type": row.type,
            "comment": row.comment,
            "reviewer": row.reviewer or "",
            "status": row.status,
            "bbox_pt": (row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def _require_attempt(job: Job, attempt: int) -> None:
    if not cad_remarks.attempt_in_range(job, attempt):
        raise not_found("Попытка")


@router.get(
    "/{job_id}/remarks",
    response_model=list[CadRemarkRead],
    summary="Замечания проверяющего к виду результата (QA)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_remarks(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    attempt: int = Query(ge=1),
    page_index: int = Query(ge=0),
    view: int = Query(ge=0),
) -> list[CadRemarkRead]:
    job = await _job(session, context, project_id, revision_id, job_id)
    _require_attempt(job, attempt)
    rows = await cad_remarks.list_remarks(
        session, job=job, attempt=attempt, page_index=page_index, view=view
    )
    return [_remark_read(row) for row in rows]


@router.post(
    "/{job_id}/remarks/import",
    response_model=CadRemarksImportRead,
    summary="Импорт файла quantor.cad-remarks.v1: слияние по ключу замечания (QA)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def import_cad_remarks(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    body: CadRemarksFile,
    session: SessionDep,
    context: AuthDep,
) -> CadRemarksImportRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    cad_remarks.check_file_binding(job, body)
    _require_attempt(job, body.attempt)
    cad_remarks.check_dxf(
        job,
        attempt=body.attempt,
        page_index=body.page_index,
        view=body.view,
        dxf_sha256=body.dxf_sha256,
    )
    imported, updated = await cad_remarks.import_remarks(
        session, job=job, file=body, user_id=context.principal.user_id
    )
    await session.commit()
    return CadRemarksImportRead(imported=imported, updated=updated)


@router.put(
    "/{job_id}/remarks/{remark_key}",
    response_model=CadRemarkRead,
    summary="Создать или изменить замечание к виду результата (QA)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_remark(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    body: CadRemarkWrite,
    session: SessionDep,
    context: AuthDep,
    remark_key: str = RemarkKey,
    attempt: int = Query(ge=1),
    page_index: int = Query(ge=0),
    view: int = Query(ge=0),
) -> CadRemarkRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    _require_attempt(job, attempt)
    row = await cad_remarks.upsert_remark(
        session,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        remark_key=remark_key,
        body=body,
        user_id=context.principal.user_id,
    )
    result = _remark_read(row)
    await session.commit()
    return result


@router.delete(
    "/{job_id}/remarks/{remark_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить замечание к виду результата (QA)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_cad_remark(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    remark_key: str = RemarkKey,
    attempt: int = Query(ge=1),
    page_index: int = Query(ge=0),
    view: int = Query(ge=0),
) -> Response:
    job = await _job(session, context, project_id, revision_id, job_id)
    _require_attempt(job, attempt)
    deleted = await cad_remarks.delete_remark(
        session,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        remark_key=remark_key,
    )
    if not deleted:
        raise not_found("Замечание")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Отдельная группа под общим требованием опознания; флаг пространства — на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
