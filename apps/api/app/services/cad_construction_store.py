"""Хранение данных человека в контуре «Конструкции CAD»: параметры конструкций и высоты листа.

Привязка — к листу (ревизия, страница, вид), а не к заданию `cad_walls` (ADR-0038 п. 4). Модуль
не знает про walls.json: проверку существования конструкции делает вызывающий.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadSheetLevelsRead,
    CadSheetLevelsWrite,
    WallsConstruction,
    WallsDocument,
)
from app.core.logging import get_logger
from app.models import CadConstructionProps as CadConstructionPropsRow
from app.models import CadProjectLevels, CadSheetLevels
from app.services.cad_constructions import SLAB_ID, ProjectSlab, match_orphan_props

log = get_logger(__name__)

PropsEntry = tuple[CadConstructionProps, bool]
# Прежние результаты `cad_walls` вида, от нового к старому; читаются лениво, по одному.
OlderWalls = Callable[[], AsyncGenerator[WallsDocument]]


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


@dataclass(frozen=True, slots=True)
class PropsLoad:
    """Параметры листа после переноса сирот: сами параметры и счётчики для итога."""

    props: dict[str, PropsEntry]
    # Не нашли конструкцию в текущем файле и по геометрии: в расчёт не входят.
    orphaned: int
    # Перенесены на новый адрес в этом запросе.
    carried_over: int


async def reconcile_orphan_props(
    session: AsyncSession,
    *,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    current: Sequence[WallsConstruction],
    has_slab: bool,
    older: OlderWalls,
) -> PropsLoad:
    """Загружает параметры листа, перенося осиротевшие на конструкции текущего файла.

    Адрес конструкции — хеш её геометрии, после пересчёта он меняется, и запись перестаёт
    находиться. Сирота ищется в прежних файлах вида (`older`), затем сопоставляется с текущими
    конструкциями по геометрии (`match_orphan_props`); перенос — смена `construction_key` в
    той же транзакции (`updated_by` не меняется). Без сирот прежние файлы не читаются.
    """
    props = await load_props(session, revision_id=revision_id, page_index=page_index, view=view)
    known = {c.id for c in current}
    if has_slab:
        known.add(SLAB_ID)
    orphan_keys = {key for key in props if key not in known}
    if not orphan_keys:
        return PropsLoad(props, 0, 0)
    old_items: dict[str, WallsConstruction] = {}
    async with aclosing(older()) as documents:
        async for document in documents:
            for item in (*document.constructions, *document.frame_partitions):
                if item.id in orphan_keys and item.id not in old_items:
                    old_items[item.id] = item
            if len(old_items) == len(orphan_keys):
                break
    moves = match_orphan_props(
        old_items,
        {key: props[key] for key in old_items},
        current,
        occupied={key for key in props if key in known},
    )
    if not moves:
        return PropsLoad(props, len(orphan_keys), 0)
    by_target: dict[str, list[str]] = {}
    for old_key, new_key in moves.items():
        by_target.setdefault(new_key, []).append(old_key)
    sheet = (
        CadConstructionPropsRow.revision_id == revision_id,
        CadConstructionPropsRow.page_index == page_index,
        CadConstructionPropsRow.view == view,
    )
    carried = 0
    for new_key, old_keys in by_target.items():
        # Слияние: параметры одинаковы (проверил `match_orphan_props`), лишние записи удаляются.
        keep, *extra = old_keys
        try:
            # Гонка с записью на тот же адрес: сирота остаётся сиротой до следующего чтения.
            async with session.begin_nested():
                if extra:
                    await session.execute(
                        delete(CadConstructionPropsRow).where(
                            *sheet, CadConstructionPropsRow.construction_key.in_(extra)
                        )
                    )
                await session.execute(
                    update(CadConstructionPropsRow)
                    .where(*sheet, CadConstructionPropsRow.construction_key == keep)
                    .values(construction_key=new_key)
                )
        except IntegrityError:
            continue
        props[new_key] = props[keep]
        for old_key in old_keys:
            del props[old_key]
        carried += len(old_keys)
        log.info(
            "cad_props_carried_over",
            revision_id=str(revision_id),
            page_index=page_index,
            view=view,
            old_keys=old_keys,
            new_key=new_key,
        )
    return PropsLoad(props, len(orphan_keys) - carried, carried)


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


EMPTY_LEVELS = CadSheetLevelsRead(
    floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=None
)


async def load_levels_many(
    session: AsyncSession, *, revision_ids: Sequence[uuid.UUID]
) -> dict[tuple[uuid.UUID, int, int], CadSheetLevelsRead]:
    """Высоты всех листов ревизий одним запросом: (ревизия, страница, вид) -> значения.

    Листа нет в ответе - высоты не заданы (`EMPTY_LEVELS`), как у `load_levels`.
    """
    if not revision_ids:
        return {}
    rows = await session.scalars(
        select(CadSheetLevels)
        .where(CadSheetLevels.revision_id.in_(set(revision_ids)))
        .execution_options(populate_existing=True)
    )
    return {
        (row.revision_id, row.page_index, row.view): CadSheetLevelsRead(
            floor_height_mm=row.floor_height_mm,
            slab_thickness_mm=row.slab_thickness_mm,
            door_height_mm=row.door_height_mm,
            floor_elevation_mm=row.floor_elevation_mm,
        )
        for row in rows
    }


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
