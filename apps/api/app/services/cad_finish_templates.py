"""Шаблоны отделки помещений проекта (ADR-0042): хранение, проверки и массовое назначение зонам.

Шаблон - параметры проекта, вводит человек. Типы помещений шаблонов проекта не пересекаются:
по типу зоны подходит ровно один шаблон, автоназначение однозначно. Доступ к проекту проверяет
вызывающий; шаблон и зона чужого проекта не находятся.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_finishes import (
    CadFinishAssign,
    CadFinishAssignResult,
    CadFinishAssignSkip,
    CadFinishLayer,
    CadFinishTemplatePatch,
    CadFinishTemplateRead,
    CadFinishTemplateWrite,
)
from app.errors import DomainError, ErrorCode
from app.models import CadFinishTemplate, CadZone, Project
from app.services import cad_partitions
from app.services.cad_constructions import APARTMENT_ROOM_KIND
from app.services.cad_zones import ROOM_KINDS


def _dump_layers(layers: Sequence[CadFinishLayer]) -> list[dict[str, object]]:
    return [layer.model_dump(mode="json") for layer in layers]


def template_read(row: CadFinishTemplate) -> CadFinishTemplateRead:
    return CadFinishTemplateRead.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "name": row.name,
            "room_types": row.room_types,
            "wall_height_mm": row.wall_height_mm,
            "walls_include_reveals": row.walls_include_reveals,
            "floor_layers": row.floor_layers,
            "wall_layers": row.wall_layers,
            "ceiling_layers": row.ceiling_layers,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


async def list_templates(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[CadFinishTemplate]:
    rows = await session.scalars(
        select(CadFinishTemplate)
        .where(CadFinishTemplate.project_id == project_id)
        .order_by(CadFinishTemplate.name, CadFinishTemplate.id)
    )
    return list(rows)


async def get_template(
    session: AsyncSession, *, project_id: uuid.UUID, template_id: uuid.UUID
) -> CadFinishTemplate | None:
    """Шаблон своего проекта; чужой не находится."""
    row = await session.get(CadFinishTemplate, template_id)
    if row is None or row.project_id != project_id:
        return None
    return row


async def _check_unique(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    room_types: Sequence[str],
    exclude_id: uuid.UUID | None,
) -> None:
    """Название уникально в проекте, типы помещений не пересекаются с другими шаблонами.

    Строка проекта блокируется до конца транзакции: параллельные запросы проверяют по очереди,
    и гонка не доходит до ограничения базы (500) и не оставляет пересечения типов.
    """
    await session.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    for other in await list_templates(session, project_id=project_id):
        if other.id == exclude_id:
            continue
        if other.name == name:
            raise DomainError(ErrorCode.CAD_FINISH_TEMPLATE_NAME_TAKEN)
        taken = next((code for code in room_types if code in other.room_types), None)
        if taken is not None:
            raise DomainError(
                ErrorCode.CAD_FINISH_ROOM_TYPE_TAKEN,
                issue={"room_type": taken, "template_id": str(other.id)},
            )


async def create_template(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    body: CadFinishTemplateWrite,
    user_id: uuid.UUID | None,
) -> CadFinishTemplate:
    await _check_unique(
        session,
        project_id=project_id,
        name=body.name,
        room_types=body.room_types,
        exclude_id=None,
    )
    row = CadFinishTemplate(
        project_id=project_id,
        name=body.name,
        room_types=list(body.room_types),
        wall_height_mm=body.wall_height_mm,
        walls_include_reveals=body.walls_include_reveals,
        floor_layers=_dump_layers(body.floor_layers),
        wall_layers=_dump_layers(body.wall_layers),
        ceiling_layers=_dump_layers(body.ceiling_layers),
        created_by=user_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_template(
    session: AsyncSession, *, row: CadFinishTemplate, body: CadFinishTemplatePatch
) -> CadFinishTemplate:
    """Переданные поля заменяют хранимые; название и типы проверяются как у нового шаблона."""
    sent = body.model_fields_set
    name = body.name if "name" in sent and body.name is not None else row.name
    room_types: list[str] = (
        list(body.room_types)
        if "room_types" in sent and body.room_types is not None
        else list(row.room_types)
    )
    await _check_unique(
        session, project_id=row.project_id, name=name, room_types=room_types, exclude_id=row.id
    )
    row.name = name
    row.room_types = room_types
    if "wall_height_mm" in sent:
        row.wall_height_mm = body.wall_height_mm
    if "walls_include_reveals" in sent and body.walls_include_reveals is not None:
        row.walls_include_reveals = body.walls_include_reveals
    if "floor_layers" in sent and body.floor_layers is not None:
        row.floor_layers = _dump_layers(body.floor_layers)
    if "wall_layers" in sent and body.wall_layers is not None:
        row.wall_layers = _dump_layers(body.wall_layers)
    if "ceiling_layers" in sent and body.ceiling_layers is not None:
        row.ceiling_layers = _dump_layers(body.ceiling_layers)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_template(session: AsyncSession, *, row: CadFinishTemplate) -> None:
    """Удаляет шаблон; явные назначения зонам снимает внешний ключ (SET NULL)."""
    await session.delete(row)
    await session.flush()


async def assign_template(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    body: CadFinishAssign,
) -> CadFinishAssignResult:
    """Массовое назначение: `template_id=None` снимает явное назначение.

    Двери и машино-места пропускаются с отметкой; чужие и несуществующие зоны - тоже
    («не найдена»), без различия, чтобы не подтверждать существование чужого. При ответе
    «Отделка квартир: без отделки» зоны квартир не получают шаблон (отметка
    `apartment_without_finish`); снятие назначения (`template_id=None`) им разрешено.
    """
    unique_ids = list(dict.fromkeys(body.zone_ids))
    rows = await session.execute(
        select(CadZone.id, CadZone.kind).where(
            CadZone.id.in_(unique_ids),
            CadZone.project_id == project_id,
            CadZone.workspace_id == workspace_id,
        )
    )
    kinds = dict(rows.tuples().all())
    no_finish = body.template_id is not None and await cad_partitions.apartment_without_finish(
        session, project_id=project_id
    )
    skipped: list[CadFinishAssignSkip] = []
    assignable: list[uuid.UUID] = []
    for zone_id in unique_ids:
        kind = kinds.get(zone_id)
        if kind is None:
            skipped.append(CadFinishAssignSkip(zone_id=zone_id, reason="not_found"))
        elif kind == "door":
            skipped.append(CadFinishAssignSkip(zone_id=zone_id, reason="door"))
        elif kind not in ROOM_KINDS:
            skipped.append(CadFinishAssignSkip(zone_id=zone_id, reason="parking_space"))
        elif no_finish and kind == APARTMENT_ROOM_KIND:
            skipped.append(CadFinishAssignSkip(zone_id=zone_id, reason="apartment_without_finish"))
        else:
            assignable.append(zone_id)
    if assignable:
        await session.execute(
            update(CadZone)
            .where(CadZone.id.in_(assignable))
            .values(finish_template_id=body.template_id)
        )
    return CadFinishAssignResult(
        assigned=len(assignable), skipped_count=len(skipped), skipped=skipped
    )
