"""Заполнение ВОР Заказчика (ADR-0055, п. 7): сравнение количеств и выгрузка копии формы.

Объекты сверки собираются по последним успешным конструкциям листов проекта и ведомостям отделки
зон МОП; количества - только от движка, количества Заказчика ни во что не подставляются. Маршруты
закрыты флагом пространства `cad.export` (флаг наследуется от роутера `cad_vor`); чтение -
DOCUMENT_READ, выгрузка - DOCUMENT_UPLOAD. Цен в выгрузке нет.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Final
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.v1.cad_constructions import _load_walls, _sheet, _totals
from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, StorageDep, require
from app.auth.permissions import Permission
from app.cad_worker import ai_vor_map
from app.contracts.ai_vor_map import (
    AiVorMapObjectRead,
    AiVorMapObjectRef,
    AiVorMapRead,
    AiVorMapResult,
    AiVorMapSuggestionRead,
    AiVorMapUnmatchedRead,
)
from app.contracts.cad_vor import CadVorSheetColumnsRead
from app.contracts.vor_fill import VorFillExportRead, VorFillRead, VorObjectKind, VorObjectRead
from app.domain import JobStatus
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadVorDocument, CadVorItem, Job, Project
from app.services import (
    cad_building3d,
    cad_finish_templates,
    cad_finishes,
    cad_partitions,
    cad_zones,
    cad_zones_review,
    vor_fill,
    vor_fill_export,
)
from app.services import cad_vor as vor_service
from app.services import projects as projects_service
from app.services.cad_walls_version import current_walls_generator
from app.storage.base import ObjectNotFoundError, StorageUnavailableError

XLSX_CONTENT_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STAMP_PATTERN: Final = r"^\d{8}T\d{6}Z$"

router = APIRouter(tags=["cad-vor"])

StampPath = Annotated[str, Path(pattern=STAMP_PATTERN)]


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


def _floors_count(floor_from: int | None, floor_to: int | None) -> int:
    """Число этажей типового листа по паспорту; диапазон не задан или перевёрнут - 1."""
    if floor_from is not None and floor_to is not None and floor_to >= floor_from:
        return floor_to - floor_from + 1
    return 1


def _floors_note(floor_from: int | None, floor_to: int | None) -> str | None:
    floors = _floors_count(floor_from, floor_to)
    if floors > 1:
        return f"типовой лист: этажи {floor_from}–{floor_to}, ×{floors}"
    return None


def _reason(error: DomainError | HTTPException) -> str:
    if isinstance(error, HTTPException):
        detail: object = error.detail
        return str(detail.get("message")) if isinstance(detail, dict) else str(detail)
    return str(error)


class _Collected:
    """Объекты проекта и что при сборе пропущено."""

    def __init__(self) -> None:
        self.sheets: list[vor_fill.SheetObjects] = []
        self.finishes: list[vor_fill.FinishObjects] = []
        self.skipped: list[str] = []
        self.mop_zones = 0
        self.typical_sheets = 0


async def _collect(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    context: AuthDep,
    project: Project,
) -> _Collected:
    """Листы проекта читаются строго по очереди (сессия не конкурентна); сбой листа - пропуск."""
    collected = _Collected()
    refs, _warnings, _slab = await cad_building3d.collect_sheets(
        session, workspace_id=context.tenant, project_id=project.id
    )
    generator = current_walls_generator(settings)
    without_finish = await cad_partitions.apartment_without_finish(session, project_id=project.id)
    templates = [
        cad_finish_templates.template_read(row)
        for row in await cad_finish_templates.list_templates(session, project_id=project.id)
    ]
    pages_done: set[tuple[uuid.UUID, int]] = set()
    for ref in refs:
        if ref.walls_key is None:
            collected.skipped.append(f"{ref.label}: конструкций нет")
            continue
        try:
            sheet = await _sheet(session, context, project.id, ref.job_id, ref.page_index, ref.view)
            walls = await _load_walls(session, storage, sheet)
            problem = cad_building3d.plan_problem(walls.document, ref.passport_kind)
            if problem is not None:
                collected.skipped.append(f"{ref.label}: {problem}")
                continue
            result, _levels = await _totals(session, storage, sheet, walls)
            floors = _floors_count(ref.passport_floor_from, ref.passport_floor_to)
            note = _floors_note(ref.passport_floor_from, ref.passport_floor_to)
            collected.typical_sheets += 1 if floors > 1 else 0
            source = vor_fill.SheetSource(
                ref.label, ref.job_id, ref.page_index, ref.view, note, floors
            )
            collected.sheets.append(
                vor_fill.SheetObjects(
                    source, result.totals, result.openings, result.heights.door_height.value_mm
                )
            )
            page = (ref.revision_id, ref.page_index)
            if page in pages_done:
                continue
            pages_done.add(page)
            zones = cad_zones_review.usable(
                await cad_zones.list_zones(
                    session, revision_id=ref.revision_id, page_index=ref.page_index
                )
            )
            mop = [zone for zone in zones if zone.kind == "room_mop"]
            collected.mop_zones += len(mop)
            if not mop:
                continue
            finish_context = await cad_finishes.load_finish_context(
                session,
                storage,
                workspace_id=context.tenant,
                project_id=project.id,
                revision_id=ref.revision_id,
                page_index=ref.page_index,
                current_generator=generator,
            )
            statement = cad_finishes.build_finish_sheet(
                revision_id=ref.revision_id,
                page_index=ref.page_index,
                zones=await cad_zones.zones_read(session, zones),
                templates=templates,
                levels_wall_height_mm=finish_context.wall_height_mm,
                walls=finish_context.walls,
                apartment_without_finish=without_finish,
            )
            collected.finishes.append(vor_fill.FinishObjects(source, statement.zones))
        except (DomainError, HTTPException) as error:
            collected.skipped.append(f"{ref.label}: {_reason(error)}")
    return collected


async def _build(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    context: AuthDep,
    project: Project,
) -> tuple[VorFillRead, CadVorDocument | None]:
    collected = await _collect(session, storage, settings, context, project)
    objects = vor_fill.build_objects(collected.sheets, collected.finishes)
    by_key = {obj.group_key: obj for obj in objects}
    document = await vor_service.current_document(session, project_id=project.id)
    links = [
        link
        for link in await vor_service.load_links(session, project_id=project.id)
        if document is not None and link.item.document_id == document.id
    ]
    linked_keys = {link.group_key for link in links}
    warnings: list[str] = []
    if collected.typical_sheets:
        warnings.append(
            f"Типовых листов: {collected.typical_sheets}, "
            "количества умножены на число этажей по паспорту листа."
        )
    incomplete = sum(1 for obj in objects if obj.incomplete)
    if incomplete:
        warnings.append(
            f"Объектов с неполным количеством (часть величин не определена): {incomplete}."
        )
    read = VorFillRead(
        document_id=None if document is None else document.id,
        has_vor=document is not None,
        items=vor_fill.compare(links, by_key),
        unlinked=[obj for obj in objects if obj.group_key not in linked_keys],
        objects=objects,
        unavailable=vor_fill.unavailable_kinds(
            objects, sheets_count=len(collected.sheets), mop_zones_count=collected.mop_zones
        ),
        warnings=warnings,
        skipped_sheets=collected.skipped,
    )
    return read, document


@router.get(
    "/projects/{project_id}/vor/fill",
    response_model=VorFillRead,
    summary="Заполнение ВОР: количества Заказчика и Quantor по связанным позициям",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_vor_fill(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> VorFillRead:
    """Количества Quantor - только от движка; количества Заказчика не подставляются никуда."""
    project = await _project(session, context, project_id)
    read, _document = await _build(session, storage, settings, context, project)
    return read


async def _read_all(storage: StorageDep, key: str) -> bytes:
    return b"".join([chunk async for chunk in storage.iter_stream(key)])


@router.post(
    "/projects/{project_id}/vor/fill/export",
    response_model=VorFillExportRead,
    summary="Выгрузить копию ВОР Заказчика с колонками Quantor и блоком «Нет в ВОР»",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def export_vor_fill(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> VorFillExportRead:
    """Оригинал в хранилище `cad-vor/...` не меняется; копия кладётся в `vor-fill/...`."""
    project = await _project(session, context, project_id)
    read, document = await _build(session, storage, settings, context, project)
    if document is None:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "ВОР Заказчика не загружен")
    try:
        source = await _read_all(storage, document.storage_key)
    except ObjectNotFoundError as error:
        raise not_found("Файл ВОР") from error
    except StorageUnavailableError as error:
        raise DomainError(ErrorCode.STORAGE_UNAVAILABLE) from error
    sheets = [CadVorSheetColumnsRead.model_validate(entry) for entry in document.columns]
    data = await asyncio.to_thread(
        vor_fill_export.fill_workbook, source, sheets, read.items, read.unlinked
    )
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    await storage.put_bytes(
        f"vor-fill/{project.id}/{stamp}.xlsx",
        data,
        content_type=XLSX_CONTENT_TYPE,
        original_filename=_export_name(document.file_name),
        metadata={"project-id": str(project.id)},
    )
    return VorFillExportRead(
        file_name=_export_name(document.file_name),
        size=len(data),
        created_at=now,
        download_url=f"/api/v1/projects/{project.id}/vor/fill/files/{stamp}",
    )


def _export_name(source_name: str) -> str:
    return f"{PurePosixPath(source_name).stem}_Quantor.xlsx"


@router.get(
    "/projects/{project_id}/vor/fill/files/{stamp}",
    summary="Скачать выгруженный заполненный ВОР (XLSX)",
    dependencies=[require(Permission.DOCUMENT_READ)],
    response_class=StreamingResponse,
)
async def download_vor_fill(
    project_id: uuid.UUID,
    stamp: StampPath,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> StreamingResponse:
    project = await _project(session, context, project_id)
    key = f"vor-fill/{project.id}/{stamp}.xlsx"
    try:
        await storage.stat(key)
    except ObjectNotFoundError as error:
        raise not_found("Файл выгрузки") from error
    except StorageUnavailableError as error:
        raise DomainError(ErrorCode.STORAGE_UNAVAILABLE) from error
    document = await vor_service.current_document(session, project_id=project.id)
    name = _export_name(document.file_name if document else "VOR.xlsx")
    return StreamingResponse(
        storage.iter_stream(key),
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


# --------------------------------------------------------------------------- ИИ-сопоставление


def _object_kind(key: str) -> VorObjectKind:
    if key.startswith("door|"):
        return "door"
    return "finish" if key.startswith("finish|") else "construction"


async def _project_objects(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    context: AuthDep,
    project: Project,
) -> list[VorObjectRead]:
    """Объекты проекта тем же расчётом, что у `GET /vor/fill`."""
    collected = await _collect(session, storage, settings, context, project)
    return vor_fill.build_objects(collected.sheets, collected.finishes)


@router.post(
    "/projects/{project_id}/vor/ai-map",
    response_model=AiVorMapRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Предложить сопоставление позиций ВОР с объектами Quantor (Claude)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_vor_ai_map(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> AiVorMapRead:
    """Количества модели не даются: в пакет идут описания позиций и объектов. Связи - вручную."""
    project = await _project(session, context, project_id)
    if ai_vor_map.pilot_for_project(project.id, settings) is None:
        raise DomainError(
            ErrorCode.CAD_RESULT_NOT_READY, "ИИ-сопоставление недоступно для этого проекта"
        )
    last = await ai_vor_map.latest_job(session, project.id)
    if last is None or last.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        objects = await _project_objects(session, storage, settings, context, project)
        document = await vor_service.current_document(session, project_id=project.id)
        await ai_vor_map.enqueue_for_project(
            session,
            workspace_id=context.tenant,
            project_id=project.id,
            settings=settings,
            document=document,
            objects=objects,
        )
        await session.commit()
    return await _ai_map_read(session, settings, project)


def _object_ref(raw: object, key: str) -> AiVorMapObjectRef:
    title = key
    if isinstance(raw, dict):
        title = str(raw.get("description") or key)
    return AiVorMapObjectRef(group_key=key, kind=_object_kind(key), title=title)


async def _ai_map_read(
    session: SessionDep, settings: SettingsDep, project: Project
) -> AiVorMapRead:
    document = await vor_service.current_document(session, project_id=project.id)
    available = ai_vor_map.pilot_for_project(project.id, settings) is not None and (
        document is not None
    )
    job: Job | None = await ai_vor_map.latest_job(session, project.id)
    empty = AiVorMapRead(
        available=available,
        job_id=None,
        status=None,
        error_message=None,
        stale=False,
        model=None,
        prompt_version=None,
        suggestions=[],
        unmatched=[],
        limitations=[],
    )
    if job is None:
        return empty
    empty.job_id, empty.status, empty.error_message = job.id, job.status, job.error_message
    raw_result = job.payload.get("ai_vor_map")
    if job.status is not JobStatus.SUCCEEDED or raw_result is None:
        return empty
    result = AiVorMapResult.model_validate(raw_result)
    empty.model, empty.prompt_version = result.model, result.prompt_version
    empty.limitations = [*result.report.limitations, *result.dropped]
    if document is None or document.id != result.document_id:
        empty.stale = True
        return empty
    snapshot = {
        str(row["group_key"]): row
        for row in job.payload.get("objects", [])
        if isinstance(row, dict)
    }
    links = await vor_service.load_links(session, project_id=project.id)
    linked = {(link.item.id, link.group_key) for link in links}
    item_ids = [uuid.UUID(match.vor_item_id) for match in result.report.matches]
    rows = await session.scalars(
        select(CadVorItem).where(CadVorItem.document_id == document.id, CadVorItem.id.in_(item_ids))
    )
    items = {item.id: item for item in rows}
    for match in result.report.matches:
        item = items.get(uuid.UUID(match.vor_item_id))
        if item is None:
            continue
        empty.suggestions.append(
            AiVorMapSuggestionRead(
                item=vor_service.item_read(item),
                objects=[
                    AiVorMapObjectRead(
                        **_object_ref(snapshot.get(key), key).model_dump(),
                        linked=(item.id, key) in linked,
                    )
                    for key in match.group_keys
                ],
                confidence=match.confidence,
                rationale=match.rationale,
            )
        )
    empty.unmatched = [
        AiVorMapUnmatchedRead(
            object=_object_ref(snapshot.get(row.group_key), row.group_key), reason=row.reason
        )
        for row in result.report.unmatched_objects
    ]
    return empty


@router.get(
    "/projects/{project_id}/vor/ai-map",
    response_model=AiVorMapRead,
    summary="Последнее ИИ-сопоставление ВОР: статус и предложения связей",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_vor_ai_map(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep, settings: SettingsDep
) -> AiVorMapRead:
    project = await _project(session, context, project_id)
    return await _ai_map_read(session, settings, project)
