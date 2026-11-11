"""Хранение данных человека в контуре «Конструкции CAD»: параметры конструкций и высоты листа.

Привязка — к листу (ревизия, страница, вид), а не к заданию `cad_walls` (ADR-0038 п. 4). Модуль
не знает про walls.json: проверку существования конструкции делает вызывающий.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadSheetLevelsRead,
    CadSheetLevelsWrite,
)
from app.models import CadConstructionProps as CadConstructionPropsRow
from app.models import CadProjectLevels, CadSheetLevels
from app.services.cad_constructions import ProjectSlab

PropsEntry = tuple[CadConstructionProps, bool]


def dump_props(props: CadConstructionProps) -> dict[str, Any]:
    """Только заданные поля: пустые не хранятся."""
    return props.model_dump(mode="json", exclude_none=True)


def merge_props(current: CadConstructionProps, patch: CadConstructionProps) -> CadConstructionProps:
    """Слияние: применяются только переданные поля патча; переданное как null снимает значение."""
    data = dump_props(current)
    for name, value in patch.model_dump(mode="json", include=patch.model_fields_set).items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    return CadConstructionProps.model_validate(data)


async def load_props(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int, view: int
) -> dict[str, PropsEntry]:
    # populate_existing: записи пишутся Core-вставкой с обновлением, объекты сессии не отстают.
    rows = await session.scalars(
        select(CadConstructionPropsRow)
        .where(
            CadConstructionPropsRow.revision_id == revision_id,
            CadConstructionPropsRow.page_index == page_index,
            CadConstructionPropsRow.view == view,
        )
        .execution_options(populate_existing=True)
    )
    return {
        row.construction_key: (CadConstructionProps.model_validate(row.props), row.accepted)
        for row in rows
    }


async def save_props(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    entries: Mapping[str, PropsEntry],
    user_id: uuid.UUID | None,
) -> None:
    """Создаёт или заменяет параметры перечисленных конструкций одним запросом."""
    if not entries:
        return
    statement = insert(CadConstructionPropsRow).values(
        [
            {
                "id": uuid.uuid4(),
                "workspace_id": workspace_id,
                "revision_id": revision_id,
                "page_index": page_index,
                "view": view,
                "construction_key": key,
                "props": dump_props(props),
                "accepted": accepted,
                "updated_by": user_id,
            }
            for key, (props, accepted) in entries.items()
        ]
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_cad_construction_props_sheet_key",
            set_={
                "props": statement.excluded.props,
                "accepted": statement.excluded.accepted,
                "updated_by": statement.excluded.updated_by,
                "updated_at": func.now(),
            },
        )
    )


async def load_levels(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int, view: int
) -> CadSheetLevelsRead:
    row = await session.scalar(
        select(CadSheetLevels)
        .where(
            CadSheetLevels.revision_id == revision_id,
            CadSheetLevels.page_index == page_index,
            CadSheetLevels.view == view,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        return CadSheetLevelsRead(
            floor_height_mm=None,
            slab_thickness_mm=None,
            door_height_mm=None,
            floor_elevation_mm=None,
        )
    return CadSheetLevelsRead(
        floor_height_mm=row.floor_height_mm,
        slab_thickness_mm=row.slab_thickness_mm,
        door_height_mm=row.door_height_mm,
        floor_elevation_mm=row.floor_elevation_mm,
    )


async def load_project_slab(session: AsyncSession, *, project_id: uuid.UUID) -> ProjectSlab | None:
    """Толщина плиты проекта из разреза (ввод человека); не введена — `None`."""
    row = await session.scalar(
        select(CadProjectLevels)
        .where(CadProjectLevels.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if row is None or row.slab_thickness_mm is None:
        return None
    return ProjectSlab(row.slab_thickness_mm, row.slab_source_ref)


async def save_levels(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    levels: CadSheetLevelsWrite,
    user_id: uuid.UUID | None,
) -> CadSheetLevelsRead:
    """Высоты листа заменяются целиком: пустое поле возвращает значение из walls.json."""
    values = {
        "floor_height_mm": levels.floor_height_mm,
        "slab_thickness_mm": levels.slab_thickness_mm,
        "door_height_mm": levels.door_height_mm,
        "floor_elevation_mm": levels.floor_elevation_mm,
        "updated_by": user_id,
    }
    statement = insert(CadSheetLevels).values(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        **values,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_cad_sheet_levels_sheet", set_={**values, "updated_at": func.now()}
        )
    )
    return CadSheetLevelsRead(
        floor_height_mm=levels.floor_height_mm,
        slab_thickness_mm=levels.slab_thickness_mm,
        door_height_mm=levels.door_height_mm,
        floor_elevation_mm=levels.floor_elevation_mm,
    )
