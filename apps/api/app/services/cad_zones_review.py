"""Происхождение зон листа и их сверка с экспликацией (ревью движка 2026-11-16).

Авто-зона получает итог сверки при записи: статус считает портал (`cad_quality`) по площади
контура и площади экспликации из zones.json. Отклонённая сверкой зона (`failed`) хранится и
показывается, но в плиту, перегородки и отделку не идёт, пока человек её не примет. Зоны человека
и зоны неизвестного происхождения авторазметка не удаляет никогда.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_zones import (
    CadZonesDeleteScope,
    CadZonesSheetSummaryRead,
    CadZoneUnmatchedMarkRead,
)
from app.contracts.cad_zones_auto import ZonesFile
from app.domain import JobStatus, JobType
from app.models import CadZone, Job
from app.services import cad as cad_service
from app.services import cad_quality
from app.services import cad_zones as cad_zones_service
from app.services.cad_zones import ROOM_KINDS, ZoneOrigin

SOURCE_AUTO: Final = "auto"
QUALITY_FAILED: Final = "failed"
_RESULT_READY: Final = "zones_ready"


def usable(zones: Sequence[CadZone]) -> list[CadZone]:
    """Зоны, участвующие в расчётах: отклонённые сверкой исключены до принятия человеком."""
    return [zone for zone in zones if zone.quality_status != QUALITY_FAILED]


def auto_origins(document: ZonesFile, generator_version: str | None) -> list[ZoneOrigin]:
    """Происхождение и итог сверки зон-помещений файла, в порядке `document.zones`."""
    twins = cad_quality.duplicate_polygons([zone.points for zone in document.zones])
    origins: list[ZoneOrigin] = []
    for index, zone in enumerate(document.zones):
        twin = twins.get(index)
        quality = cad_quality.zone_quality(
            kind=zone.kind,
            name=zone.name,
            room_mark=zone.room_mark,
            area_m2=zone.poly_area_m2,
            expl_area_m2=zone.expl_area_m2,
            has_twin=twin is not None,
            twin_mark=None if twin is None else document.zones[twin].room_mark,
        )
        origins.append(
            ZoneOrigin(
                source="auto",
                generator_version=generator_version,
                expl_area_m2=zone.expl_area_m2,
                generator_area_m2=zone.poly_area_m2,
                notes=tuple(zone.notes),
                quality_status=quality.status,
                quality_reason=quality.reason,
            )
        )
    return origins


async def page_sources(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int
) -> dict[str, int]:
    """Число зон страницы по происхождению; зон нет - пустой словарь."""
    rows = await session.execute(
        select(CadZone.source, func.count())
        .where(CadZone.revision_id == revision_id, CadZone.page_index == page_index)
        .group_by(CadZone.source)
    )
    return {source: int(count) for source, count in rows.tuples()}


def only_auto(sources: dict[str, int]) -> bool:
    """На странице есть зоны, и все они созданы авторазметкой и человеком не тронуты."""
    return bool(sources) and set(sources) == {SOURCE_AUTO}


async def accept_zone(
    session: AsyncSession, *, zone: CadZone, user_id: uuid.UUID | None
) -> CadZone:
    """Человек принял зону вне допуска: она снова участвует в расчётах.

    Принятая зона - решение человека: становится `human`, авторазметка её больше не удалит.
    Причина расхождения остаётся в `quality_reason` как след.
    """
    zone.quality_status = "ok"
    zone.quality_accepted_by = user_id
    zone.quality_accepted_at = datetime.now(UTC)
    zone.source = "human"
    await session.flush()
    await session.refresh(zone)
    return zone


async def delete_page_zones(
    session: AsyncSession,
    *,
    revision_id: uuid.UUID,
    page_index: int,
    scope: CadZonesDeleteScope,
) -> int:
    """Массовое удаление зон страницы под её блокировкой: только авто либо все."""
    await cad_zones_service.lock_page_zones(session, revision_id=revision_id, page_index=page_index)
    query = delete(CadZone).where(
        CadZone.revision_id == revision_id, CadZone.page_index == page_index
    )
    if scope == "auto":
        query = query.where(CadZone.source == SOURCE_AUTO)
    # `returning id` вместо rowcount: у результата в типах SQLAlchemy его нет.
    deleted = await session.scalars(query.returning(CadZone.id))
    return len(deleted.all())


def _unmatched(result: dict[str, Any]) -> list[CadZoneUnmatchedMarkRead]:
    raw = result.get("unmatched_marks")
    marks: list[CadZoneUnmatchedMarkRead] = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("room_mark"), str):
            continue
        name, reason, area = row.get("name"), row.get("reason"), row.get("expl_area_m2")
        marks.append(
            CadZoneUnmatchedMarkRead(
                room_mark=row["room_mark"],
                name=name if isinstance(name, str) else None,
                expl_area_m2=float(area) if isinstance(area, int | float) else None,
                reason=reason if isinstance(reason, str) else None,
            )
        )
    return marks


async def _last_unmatched(
    session: AsyncSession, *, workspace_id: uuid.UUID, revision_id: uuid.UUID, page_index: int
) -> list[CadZoneUnmatchedMarkRead]:
    """Марки без зоны из итога последнего задания разметки, создавшего зоны страницы."""
    jobs = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_ZONES,
            Job.workspace_id == workspace_id,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["revision_id"].astext == str(revision_id),
            Job.payload["page_index"].astext == str(page_index),
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(20)
    )
    for job in jobs:
        result = cad_service.current_result(job)
        if result.get("result_status") == _RESULT_READY:
            return _unmatched(result)
    return []


async def sheet_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, revision_id: uuid.UUID, page_index: int
) -> CadZonesSheetSummaryRead:
    """Сводка сверки зон листа: итоги, происхождение, сумма по квартирам против экспликации."""
    zones = await cad_zones_service.list_zones(
        session, revision_id=revision_id, page_index=page_index
    )
    quality = {"ok": 0, "review": 0, "failed": 0}
    sources = {"auto": 0, "human": 0, "unknown": 0}
    versions: set[str] = set()
    compared = 0
    area = expl = 0.0
    for zone in zones:
        sources[zone.source if zone.source in sources else "unknown"] += 1
        if zone.source == SOURCE_AUTO and zone.generator_version:
            versions.add(zone.generator_version)
        if zone.kind not in ROOM_KINDS:
            continue
        quality[zone.quality_status if zone.quality_status in quality else "ok"] += 1
        if (
            zone.kind == "room_apartment"
            and zone.generator_area_m2 is not None
            and zone.expl_area_m2 is not None
        ):
            compared += 1
            area += zone.generator_area_m2
            expl += zone.expl_area_m2
    unmatched = (
        await _last_unmatched(
            session, workspace_id=workspace_id, revision_id=revision_id, page_index=page_index
        )
        if sources["auto"]
        else []
    )
    return CadZonesSheetSummaryRead(
        revision_id=revision_id,
        page_index=page_index,
        ok=quality["ok"],
        review=quality["review"],
        failed=quality["failed"],
        auto=sources["auto"],
        human=sources["human"],
        unknown=sources["unknown"],
        generator_versions=sorted(versions),
        apartments_compared=compared,
        apartments_area_m2=round(area, 2) if compared else None,
        apartments_expl_area_m2=round(expl, 2) if compared else None,
        apartments_delta_percent=(
            round((area - expl) / expl * 100, 1) if compared and expl > 0 else None
        ),
        unmatched_marks=unmatched,
        recreate_allowed=bool(zones) and sources["human"] == 0 and sources["unknown"] == 0,
    )
