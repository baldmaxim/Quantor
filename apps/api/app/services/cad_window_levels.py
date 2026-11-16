"""Ручные подоконник и высота окна листа: «применить ко всей секции» (ADR-0048 п. 5).

Секция листа определяется заголовком его плана в walls.json: корпус и секция из текста PDF. Лист
без корпуса или без секции в заголовке секции не имеет - значения достаются только ему самому.
Группа - как у общего вида здания (`cad_building3d.group_of`). Планирование - чистая функция;
чтение заголовков листов и запись - в `apply_to_section`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import (
    CadSheetFloorTitle,
    CadWindowLevelsApplyRead,
    CadWindowLevelsSkippedRead,
)
from app.services import cad_building3d, cad_views
from app.services import cad_construction_store as store
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

READ_CONCURRENCY: Final = 6

SkipReason = Literal["no_walls", "walls_unreadable", "summary_sheet", "other_group"]
SheetKey = tuple[uuid.UUID, int, int]


@dataclass(frozen=True, slots=True)
class SectionSheet:
    """Лист проекта для планирования: адрес, подпись и заголовок плана (`None` - не прочитан)."""

    revision_id: uuid.UUID
    page_index: int
    view: int
    label: str
    title: CadSheetFloorTitle | None
    # Сводный лист (в названии три и больше секций): отдельная группа, как в общем виде здания.
    summary: bool = False
    # walls.json есть, но не прочитан (ошибка хранилища, файл вне контракта).
    unreadable: bool = False

    @property
    def key(self) -> SheetKey:
        return (self.revision_id, self.page_index, self.view)


@dataclass(frozen=True, slots=True)
class SectionPlan:
    group_label: str | None
    targets: list[SectionSheet]
    skipped: list[tuple[SectionSheet, SkipReason]]


def section_group(title: CadSheetFloorTitle | None) -> tuple[str, str] | None:
    """Ключ и подпись секции листа; нет корпуса или секции в заголовке - `None`."""
    if title is None:
        return None
    corps, section = (title.corps or "").strip(), (title.section or "").strip()
    if not corps or not section:
        return None
    return cad_building3d.group_of(corps, section)


def plan_section(source: SectionSheet, sheets: Sequence[SectionSheet]) -> SectionPlan:
    """Листы, которым достанутся значения источника, и пропущенные с причиной.

    Источник - всегда цель. Без корпуса или секции у источника, а также у сводного листа цель
    только он сам, остальные листы не просматриваются. Сводные листы других секций пропускаются.
    """
    group = None if source.summary else section_group(source.title)
    if group is None:
        return SectionPlan(None, [source], [])
    targets: list[SectionSheet] = [source]
    skipped: list[tuple[SectionSheet, SkipReason]] = []
    for sheet in sheets:
        if sheet.key == source.key:
            continue
        if sheet.summary:
            skipped.append((sheet, "summary_sheet"))
        elif sheet.unreadable:
            skipped.append((sheet, "walls_unreadable"))
        elif sheet.title is None:
            skipped.append((sheet, "no_walls"))
        elif (other := section_group(sheet.title)) is not None and other[0] == group[0]:
            targets.append(sheet)
        else:
            skipped.append((sheet, "other_group"))
    return SectionPlan(group[1], targets, skipped)


async def _title_of(
    storage: ObjectStorage, sheet: cad_building3d.SheetRef, gate: asyncio.Semaphore
) -> SectionSheet:
    title: CadSheetFloorTitle | None = None
    unreadable = False
    if sheet.walls_key is not None:
        async with gate:
            try:
                raw: Any = await cad_views.read_json(storage, sheet.walls_key)
            except (
                ObjectNotFoundError,
                StorageUnavailableError,
                cad_views.ArtifactTooLargeError,
                ValueError,
                OSError,
            ):
                raw = None
        heights = raw.get("heights") if isinstance(raw, dict) else None
        raw_title = heights.get("title") if isinstance(heights, dict) else None
        if isinstance(raw_title, dict):
            try:
                title = CadSheetFloorTitle.model_validate(raw_title)
            except ValidationError:
                unreadable = True
        elif isinstance(heights, dict):
            # walls.json читается, заголовка плана в нём нет: лист без секции, не «нет файла».
            title = CadSheetFloorTitle()
        else:
            unreadable = True
    return SectionSheet(
        sheet.revision_id,
        sheet.page_index,
        sheet.view,
        sheet.label,
        title,
        summary=cad_building3d.is_summary_sheet(sheet.stamp_title),
        unreadable=unreadable,
    )


async def apply_to_section(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source: SectionSheet,
    sill_mm: int,
    head_mm: int,
    user_id: uuid.UUID | None,
    dry_run: bool,
) -> CadWindowLevelsApplyRead:
    """Записывает подоконник и верх окна источника всем листам его секции (без `dry_run`).

    Остальные высоты листов не меняются. `updated` - число листов секции, включая источник.
    """
    refs, _warnings, _slab = await cad_building3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    # Сводный лист - отдельная группа: узнаётся по названию из штампа, walls.json не нужен.
    own = next(
        (ref for ref in refs if (ref.revision_id, ref.page_index, ref.view) == source.key), None
    )
    if own is not None and cad_building3d.is_summary_sheet(own.stamp_title):
        source = dataclasses.replace(source, summary=True)
    sheets: list[SectionSheet] = []
    if not source.summary and section_group(source.title) is not None:
        gate = asyncio.Semaphore(READ_CONCURRENCY)
        sheets = list(await asyncio.gather(*(_title_of(storage, ref, gate) for ref in refs)))
    plan = plan_section(source, sheets)
    if not dry_run:
        for target in plan.targets:
            await store.save_window_levels(
                session,
                workspace_id=workspace_id,
                revision_id=target.revision_id,
                page_index=target.page_index,
                view=target.view,
                sill_mm=sill_mm,
                head_mm=head_mm,
                user_id=user_id,
            )
    return CadWindowLevelsApplyRead(
        sill_mm=sill_mm,
        head_mm=head_mm,
        dry_run=dry_run,
        group_label=plan.group_label,
        updated=len(plan.targets),
        skipped=[
            CadWindowLevelsSkippedRead(label=sheet.label, reason=reason)
            for sheet, reason in plan.skipped
        ],
    )
