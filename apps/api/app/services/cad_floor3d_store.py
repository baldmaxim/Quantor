"""Хранение данных человека для 3D-вида этажа: уровень проекта и решения по отверстиям плиты.

Уровень проекта — на проект (толщина плиты из разреза), решения — на лист (ревизия, страница, вид)
и ключ геометрии отверстия (ADR-0039). Модуль не знает про walls.json: проверку существования
отверстия делает вызывающий.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_floor3d import CadProjectLevelsRead, CadProjectLevelsWrite
from app.models import CadProjectLevels, CadSlabHoleDecision


async def load_project_levels(
    session: AsyncSession, *, project_id: uuid.UUID
) -> CadProjectLevelsRead:
    row = await session.scalar(
        select(CadProjectLevels)
        .where(CadProjectLevels.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        return CadProjectLevelsRead(slab_thickness_mm=None, slab_source_ref=None, updated_at=None)
    return CadProjectLevelsRead(
        slab_thickness_mm=row.slab_thickness_mm,
        slab_source_ref=row.slab_source_ref,
        updated_at=row.updated_at,
    )


async def save_project_levels(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    levels: CadProjectLevelsWrite,
    user_id: uuid.UUID | None,
) -> CadProjectLevelsRead:
    """Уровни проекта заменяются целиком; пустая толщина снимает и лист-источник."""
    thickness = levels.slab_thickness_mm
    values = {
        "slab_thickness_mm": thickness,
        "slab_source_ref": None if thickness is None else levels.slab_source_ref,
        "updated_by": user_id,
    }
    statement = insert(CadProjectLevels).values(
        project_id=project_id, workspace_id=workspace_id, **values
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[CadProjectLevels.project_id],
            set_={**values, "updated_at": func.now()},
        )
    )
    return await load_project_levels(session, project_id=project_id)


async def load_hole_decisions(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int, view: int
) -> dict[str, bool]:
    rows = await session.scalars(
        select(CadSlabHoleDecision)
        .where(
            CadSlabHoleDecision.revision_id == revision_id,
            CadSlabHoleDecision.page_index == page_index,
            CadSlabHoleDecision.view == view,
        )
        .execution_options(populate_existing=True)
    )
    return {row.hole_key: row.enabled for row in rows}


async def save_hole_decision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    hole_key: str,
    enabled: bool,
    user_id: uuid.UUID | None,
) -> None:
    statement = insert(CadSlabHoleDecision).values(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        hole_key=hole_key,
        enabled=enabled,
        updated_by=user_id,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_cad_slab_hole_decisions_sheet_key",
            set_={"enabled": enabled, "updated_by": user_id, "updated_at": func.now()},
        )
    )
