"""Конструкции кладки и монолита во вкладке CAD (ADR-0038): величины, параметры, высоты листа.

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ — по пространству, проекту и
ревизии, чужое — 404. Адрес вида — по заданию `cad_pdf_convert` (`job_id`), страница и вид — как у
остальных маршрутов CAD. Величины считает сервер по последнему успешному `cad_walls` вида и
данным человека; в итоги обмера, таблицы MEP и calc они не входят.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status
from pydantic import ValidationError

from app.api.v1.cad import _job, _read_artifact_json
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
from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadConstructionPropsBulk,
    CadConstructionPropsPut,
    CadConstructionRead,
    CadConstructionsBulkRead,
    CadConstructionsRead,
    CadConstructionsTotalsRead,
    CadLatestWallsJobRead,
    CadSheetLevelsRead,
    CadSheetLevelsWrite,
    CadWallsJobRead,
    CadWallsWarningRead,
    WallsDocument,
)
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_construction_store as store
from app.services import cad_constructions, cad_walls
from app.services import jobs as jobs_service

router = APIRouter(
    prefix="/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}",
    tags=["cad-constructions"],
    dependencies=[require_feature("cad.export")],
)

ConstructionKey = Annotated[str, Path(min_length=1, max_length=32)]


@dataclass(frozen=True, slots=True)
class _Sheet:
    """Лист, на который указывает адрес: родитель, ревизия, страница и вид."""

    parent: Job
    revision_id: uuid.UUID
    page_index: int
    view: int
    project_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class _Walls:
    """Последний успешный результат `cad_walls` вида."""

    job: Job
    sha256: str
    document: WallsDocument
    # Файл как прочитан: 3D-вид берёт из него поля, которых нет в `WallsDocument` (ADR-0039).
    raw: Any
    # Самое свежее задание вида (может быть новее `job`: пересчёт идёт или упал).
    latest: Job


async def _sheet(
    session: SessionDep,
    context: AuthContext,
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
) -> _Sheet:
    """Родитель `cad_pdf_convert` своего пространства и проекта; вид существует в его итоге."""
    found = await jobs_service.get_job(session, workspace_id=context.tenant, job_id=job_id)
    raw_revision = None if found is None else found.payload.get("revision_id")
    try:
        revision_id = uuid.UUID(str(raw_revision))
    except ValueError as error:
        raise not_found("Задание") from error
    parent = await _job(session, context, project_id, revision_id, job_id)
    if parent.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    if cad_walls.view_has_dxf(parent, page_index, view) is None:
        raise not_found("Вид")
    return _Sheet(parent, revision_id, page_index, view, project_id)


async def _load_walls(session: SessionDep, storage: StorageDep, sheet: _Sheet) -> _Walls:
    """walls.json последнего успешного задания вида; нет результата — 404 CAD_WALLS_NOT_READY."""
    jobs = await cad_walls.walls_jobs_of_view(
        session, parent=sheet.parent, page_index=sheet.page_index, view=sheet.view
    )
    ready = next((job for job in jobs if job.status is JobStatus.SUCCEEDED), None)
    if ready is None:
        issue: dict[str, str | int | None] | None = None
        if jobs:
            issue = {"job_status": jobs[0].status.value, "job_id": str(jobs[0].id)}
        raise DomainError(ErrorCode.CAD_WALLS_NOT_READY, issue=issue)
    result = cad_service.result_of(ready)
    attempt = result.get("attempt")
    folder = cad_service.view_folder(sheet.page_index, sheet.view)
    name = f"{folder}/{cad_walls.WALLS_JSON}"
    artifact = cad_service.find_artifact(ready, name)
    raw = (
        await _read_artifact_json(storage, ready, sheet.revision_id, attempt, name)
        if type(attempt) is int and artifact is not None
        else None
    )
    if raw is None or artifact is None:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "walls.json задания не найден")
    try:
        document = WallsDocument.model_validate(raw)
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "walls.json вне контракта") from error
    return _Walls(ready, str(artifact["sha256"]), document, raw, jobs[0])


async def _totals(
    session: SessionDep, sheet: _Sheet, walls: _Walls
) -> tuple[cad_constructions.SheetResult, CadSheetLevelsRead]:
    levels = await store.load_levels(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    props = await store.load_props(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    # Толщина плиты проекта из разреза (ADR-0039) сильнее walls.json, слабее переопределения листа.
    project_slab = await store.load_project_slab(session, project_id=sheet.project_id)
    return cad_constructions.compute_sheet(walls.document, props, levels, project_slab), levels


def _totals_read(
    result: cad_constructions.SheetResult, levels: CadSheetLevelsRead
) -> CadConstructionsTotalsRead:
    return CadConstructionsTotalsRead(
        heights=result.heights,
        sheet_levels=levels,
        totals=result.totals,
        summary=result.summary,
    )


@router.get(
    "/constructions",
    response_model=CadConstructionsRead,
    summary="Конструкции вида: геометрия, вычисленные величины, параметры и итоги",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_constructions(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadConstructionsRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    result, levels = await _totals(session, sheet, walls)
    document = walls.document
    return CadConstructionsRead(
        **_totals_read(result, levels).model_dump(),
        job_id=sheet.parent.id,
        page_index=page_index,
        view=view,
        walls_job_id=walls.job.id,
        walls_sha256=walls.sha256,
        latest_walls_job=CadLatestWallsJobRead(
            id=walls.latest.id,
            status=walls.latest.status,
            error_code=walls.latest.error_code,
            error_message=walls.latest.error_message,
            created_at=walls.latest.created_at,
        ),
        generator=document.generator,
        params_version=document.params_version,
        params_sha256=document.params_sha256,
        dxf_sha256=document.dxf_sha256,
        constructions=result.constructions,
        openings=result.openings,
        warnings=[
            CadWallsWarningRead(code=w.code, message=w.message) for w in document.checks.warnings
        ],
    )


@router.put(
    "/constructions/props:bulk",
    response_model=CadConstructionsBulkRead,
    summary="Применить параметры к нескольким конструкциям (слияние переданных полей)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def bulk_cad_construction_props(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    body: CadConstructionPropsBulk,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadConstructionsBulkRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    keys = list(dict.fromkeys(body.keys))
    known = {c.id for c in (*walls.document.constructions, *walls.document.frame_partitions)}
    unknown = [key for key in keys if key not in known]
    if unknown:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, f"Конструкции не найдены в результате вида: {len(unknown)}"
        )
    current = await store.load_props(
        session, revision_id=sheet.revision_id, page_index=page_index, view=view
    )
    updates: dict[str, store.PropsEntry] = {}
    for key in keys:
        old_props, old_accepted = current.get(key, (CadConstructionProps(), False))
        new_props = store.merge_props(old_props, body.props_patch)
        new_accepted = old_accepted if body.accepted is None else body.accepted
        if new_props != old_props or new_accepted != old_accepted:
            updates[key] = (new_props, new_accepted)
    await store.save_props(
        session,
        workspace_id=context.tenant,
        revision_id=sheet.revision_id,
        page_index=page_index,
        view=view,
        entries=updates,
        user_id=context.principal.user_id,
    )
    result, levels = await _totals(session, sheet, walls)
    response = CadConstructionsBulkRead(
        **_totals_read(result, levels).model_dump(), changed=len(updates)
    )
    await session.commit()
    return response


@router.put(
    "/constructions/{construction_key}/props",
    response_model=CadConstructionRead,
    summary="Заменить параметры конструкции; ответ — конструкция с пересчётом",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_construction_props(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    construction_key: ConstructionKey,
    body: CadConstructionPropsPut,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadConstructionRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    if construction_key not in {
        c.id for c in (*walls.document.constructions, *walls.document.frame_partitions)
    }:
        raise not_found("Конструкция")
    current = await store.load_props(
        session, revision_id=sheet.revision_id, page_index=page_index, view=view
    )
    existing = current.get(construction_key)
    accepted = body.accepted if body.accepted is not None else (existing[1] if existing else False)
    await store.save_props(
        session,
        workspace_id=context.tenant,
        revision_id=sheet.revision_id,
        page_index=page_index,
        view=view,
        entries={construction_key: (body.props, accepted)},
        user_id=context.principal.user_id,
    )
    result, _levels = await _totals(session, sheet, walls)
    updated = next(c for c in result.constructions if c.id == construction_key)
    await session.commit()
    return updated


@router.put(
    "/levels",
    response_model=CadConstructionsTotalsRead,
    summary="Задать высоты листа (этаж, плита, дверь); пустое поле — значение из walls.json",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_sheet_levels(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    body: CadSheetLevelsWrite,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadConstructionsTotalsRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    levels = await store.save_levels(
        session,
        workspace_id=context.tenant,
        revision_id=sheet.revision_id,
        page_index=page_index,
        view=view,
        levels=body,
        user_id=context.principal.user_id,
    )
    props = await store.load_props(
        session, revision_id=sheet.revision_id, page_index=page_index, view=view
    )
    project_slab = await store.load_project_slab(session, project_id=sheet.project_id)
    result = cad_constructions.compute_sheet(walls.document, props, levels, project_slab)
    response = _totals_read(result, levels)
    await session.commit()
    return response


@router.post(
    "/walls",
    response_model=CadWallsJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Пересчитать конструкции вида: поставить задание cad_walls",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def recompute_cad_walls(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CadWallsJobRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    job = await cad_walls.schedule_recompute(
        session, storage, parent=sheet.parent, page_index=page_index, view=view, settings=settings
    )
    response = CadWallsJobRead(
        job_id=job.id,
        parent_job_id=sheet.parent.id,
        page_index=page_index,
        view=view,
        status=job.status,
        attempt=job.attempt,
        created_at=job.created_at,
    )
    await session.commit()
    return response


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
