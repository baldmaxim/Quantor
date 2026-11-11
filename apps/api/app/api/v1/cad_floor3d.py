"""3D-вид этажа во вкладке CAD (ADR-0039): уровень проекта, модель этажа, решения по отверстиям.

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ — по пространству, проекту и
ревизии, чужое — 404. Модель собирает сервер по последнему успешному `cad_walls` вида и данным
человека; вид только показывает: в итоги обмера, таблицы MEP и calc она не входит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from pydantic import ValidationError

from app.api.v1.cad import _read_artifact_json
from app.api.v1.cad_constructions import _load_walls, _Sheet, _sheet, _Walls
from app.api.v1.deps import AuthDep, SessionDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_constructions import CadWallsJobRead
from app.contracts.cad_floor3d import (
    HOLE_KEY_MAX,
    CadFloor3dHolePut,
    CadFloor3dRead,
    CadFloor3dWarningRead,
    CadProjectLevelsRead,
    CadProjectLevelsWrite,
    WallsFloorExtras,
)
from app.errors import DomainError, ErrorCode, not_found
from app.services import cad as cad_service
from app.services import cad_construction_store as construction_store
from app.services import cad_floor3d, cad_floor3d_dxf, cad_views, cad_zones
from app.services import cad_floor3d_store as store
from app.services import projects as projects_service

router = APIRouter(tags=["cad-floor3d"], dependencies=[require_feature("cad.export")])

SHEET_PREFIX = "/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}"
HoleKey = Annotated[str, Path(min_length=1, max_length=HOLE_KEY_MAX)]


async def _require_project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> None:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")


def _extras(walls: _Walls) -> WallsFloorExtras:
    try:
        return WallsFloorExtras.model_validate(walls.raw)
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "walls.json вне контракта") from error


async def _door_zones(
    session: SessionDep, storage: StorageDep, sheet: _Sheet
) -> tuple[list[cad_floor3d.DoorZoneMm], list[CadFloor3dWarningRead]]:
    """Зоны двери страницы в мм DXF по кадру вида; не удалось перевести — предупреждение."""
    zones = [
        zone
        for zone in await cad_zones.list_zones(
            session, revision_id=sheet.revision_id, page_index=sheet.page_index
        )
        if zone.kind == "door" and zone.door_height_mm is not None
    ]
    if not zones:
        return [], []
    reason: str | None = None
    attempt = cad_service.current_result(sheet.parent).get("attempt")
    folder = cad_service.view_folder(sheet.page_index, sheet.view)
    frame = None
    if type(attempt) is int:
        scale = cad_views.scale_from(
            await _read_artifact_json(
                storage, sheet.parent, sheet.revision_id, attempt, f"{folder}/scale.json"
            )
        )
        cad_checks = await _read_artifact_json(
            storage, sheet.parent, sheet.revision_id, attempt, f"{folder}/cad_checks.json"
        )
        frame = cad_views.frame_from(scale, cad_checks)
    page = (
        await cad_zones.page_scales(
            session, revision_id=sheet.revision_id, page_indexes={sheet.page_index}
        )
    ).get(sheet.page_index)
    geometry = None if page is None else page.geometry
    origin = None if frame is None else frame.origin_pt
    factor = None if frame is None else frame.mm_per_pdf_point
    if frame is None or not frame.confirmed:
        reason = frame.reason if frame is not None and frame.reason else "кадр вида не установлен"
    elif geometry is None:
        reason = "нет геометрии страницы"
    if reason is not None or geometry is None or origin is None or factor is None:
        return [], [
            CadFloor3dWarningRead(
                code="door_zones_unmapped",
                message=f"Зоны двери не сопоставлены с проёмами: {reason or 'кадр неполон'}.",
            )
        ]
    mapped = cad_floor3d.door_zones_to_mm(
        [
            cad_floor3d.DoorZoneNormalized(
                [list(point) for point in zone.points], int(zone.door_height_mm or 0)
            )
            for zone in zones
        ],
        page_width_pt=float(geometry.display_width_pt),
        page_height_pt=float(geometry.display_height_pt),
        origin_pt=origin,
        mm_per_pdf_point=factor,
    )
    return mapped, []


async def _floor3d(
    session: SessionDep, storage: StorageDep, sheet: _Sheet, walls: _Walls
) -> CadFloor3dRead:
    overrides = await construction_store.load_levels(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    props = await construction_store.load_props(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    project_slab = await construction_store.load_project_slab(session, project_id=sheet.project_id)
    decisions = await store.load_hole_decisions(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    zones, zone_warnings = await _door_zones(session, storage, sheet)
    return cad_floor3d.build_floor3d(
        walls.document,
        _extras(walls),
        props_by_key=props,
        overrides=overrides,
        project_slab=project_slab,
        hole_decisions=decisions,
        door_zones=zones,
        extra_warnings=zone_warnings,
    )


@router.get(
    "/projects/{project_id}/cad/levels",
    response_model=CadProjectLevelsRead,
    summary="Уровни проекта: толщина плиты из разрезов и лист-источник",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_project_levels(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CadProjectLevelsRead:
    await _require_project(session, context, project_id)
    return await store.load_project_levels(session, project_id=project_id)


@router.put(
    "/projects/{project_id}/cad/levels",
    response_model=CadProjectLevelsRead,
    summary="Задать толщину плиты проекта из разрезов (применяется ко всем листам проекта)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_project_levels(
    project_id: uuid.UUID, body: CadProjectLevelsWrite, session: SessionDep, context: AuthDep
) -> CadProjectLevelsRead:
    await _require_project(session, context, project_id)
    response = await store.save_project_levels(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        levels=body,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return response


@router.get(
    SHEET_PREFIX + "/floor3d",
    response_model=CadFloor3dRead,
    summary="Модель этажа для 3D-вида: плита, отверстия, стены, перемычки, высоты с источниками",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_floor3d(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadFloor3dRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    return await _floor3d(session, storage, sheet, walls)


@router.post(
    SHEET_PREFIX + "/floor3d/dxf",
    response_model=CadWallsJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Выгрузить 3D-модель этажа в 3D DXF для AutoCAD: поставить задание cad_floor3d_dxf",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_floor3d_dxf(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadWallsJobRead:
    """Модель собирается тем же сервисом, что у GET floor3d; DXF - файл `floor3d.dxf` задания."""
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    model = await _floor3d(session, storage, sheet, walls)
    job = await cad_floor3d_dxf.schedule(
        session, storage, parent=sheet.parent, page_index=page_index, view=view, model=model
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


@router.put(
    SHEET_PREFIX + "/floor3d/holes/{hole_key}",
    response_model=CadFloor3dRead,
    summary="Включить или выключить отверстие плиты; ответ — обновлённая модель этажа",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_floor3d_hole(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    hole_key: HoleKey,
    body: CadFloor3dHolePut,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadFloor3dRead:
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    walls = await _load_walls(session, storage, sheet)
    if hole_key not in cad_floor3d.hole_keys(_extras(walls)):
        raise not_found("Отверстие")
    await store.save_hole_decision(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=sheet.revision_id,
        page_index=page_index,
        view=view,
        hole_key=hole_key,
        enabled=body.enabled,
        user_id=context.principal.user_id,
    )
    response = await _floor3d(session, storage, sheet, walls)
    await session.commit()
    return response


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
