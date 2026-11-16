"""Черновик копирования реестра стояков с другого листа той же ревизии (ADR-0041).

Записи реестра привязаны к шахте полем `shaft_id` ("S06"), а номера шахт генератор трасс
присваивает на каждом листе заново. Поэтому `shaft_id` переносится по положению шахт: сдвиг
между листами ищется голосованием по парам шахт с одинаковыми системами. Только чтение:
реестр не записывается, сохраняет его человек обычным PUT. Шахты берутся из `candidate.json`
последнего успешного задания трасс листа; PDF и DXF не разбираются.
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_risers import (
    SHAFT_ID_PATTERN,
    CadRiserCopyRow,
    CadRiserEntry,
    CadRisersCopyOut,
    CadRisersSheetOut,
)
from app.models import CadSheetRisers
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_views
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

# Допуски геометрического сопоставления шахт двух листов, мм и доли. Это параметры алгоритма
# поиска совпадающих положений, а не инженерные числа.
BUCKET_MM: Final = 100  # размер корзины голосования за сдвиг
MIN_VOTES: Final = 3  # минимум голосов за лучшую корзину
MIN_VOTES_SHARE: Final = 0.3  # и доля от меньшего из двух наборов шахт
MATCH_RADIUS_MM: Final = 300  # радиус поиска шахты цели вокруг (источник + сдвиг)


@dataclass(frozen=True)
class ShaftPoint:
    id: str
    systems: frozenset[str]
    x: float
    y: float


@dataclass(frozen=True)
class ShaftMatch:
    target_id: str
    distance_mm: int


@dataclass(frozen=True)
class ShaftMapping:
    """`shift` пуст - сдвиг не найден, совпадений нет."""

    shift: tuple[int, int] | None
    matches: dict[str, ShaftMatch]


def _bucket(value: float) -> int:
    # Округление «половина вверх», а не банковское: результат не зависит от чётности.
    return math.floor(value / BUCKET_MM + 0.5)


def _find_shift(source: list[ShaftPoint], target: list[ShaftPoint]) -> tuple[int, int] | None:
    offsets: list[tuple[float, float]] = []
    for s in source:
        if not s.systems:
            continue
        for t in target:
            if t.systems == s.systems:
                offsets.append((t.x - s.x, t.y - s.y))
    if not offsets:
        return None
    votes = Counter((_bucket(dx), _bucket(dy)) for dx, dy in offsets)
    best_key, best_votes = min(votes.items(), key=lambda item: (-item[1], item[0]))
    if best_votes < MIN_VOTES or best_votes < MIN_VOTES_SHARE * min(len(source), len(target)):
        return None
    near = [
        (dx, dy)
        for dx, dy in offsets
        if abs(_bucket(dx) - best_key[0]) <= 1 and abs(_bucket(dy) - best_key[1]) <= 1
    ]
    return (
        round(statistics.median(dx for dx, _ in near)),
        round(statistics.median(dy for _, dy in near)),
    )


def map_shafts(source: list[ShaftPoint], target: list[ShaftPoint]) -> ShaftMapping:
    """Сопоставление шахт источника шахтам цели по положению; детерминировано."""
    shift = _find_shift(source, target)
    if shift is None:
        return ShaftMapping(shift=None, matches={})
    candidates: list[tuple[float, str, ShaftPoint]] = []  # (расстояние, id источника, цель)
    for s in source:
        px, py = s.x + shift[0], s.y + shift[1]
        best: tuple[float, str, ShaftPoint] | None = None
        for t in target:
            if t.systems != s.systems:
                continue
            distance = math.hypot(t.x - px, t.y - py)
            if distance > MATCH_RADIUS_MM:
                continue
            if best is None or (distance, t.id) < (best[0], best[1]):
                best = (distance, t.id, t)
        if best is not None:
            candidates.append((best[0], s.id, best[2]))
    # Две шахты источника в одной цели: совпадение у ближней, при равенстве - у меньшего id.
    matches: dict[str, ShaftMatch] = {}
    taken: set[str] = set()
    for distance, source_id, point in sorted(candidates, key=lambda item: (item[0], item[1])):
        if point.id in taken:
            continue
        taken.add(point.id)
        matches[source_id] = ShaftMatch(target_id=point.id, distance_mm=round(distance))
    return ShaftMapping(shift=shift, matches=matches)


class _CandidateShaft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=SHAFT_ID_PATTERN)
    systems: list[str]
    centroid_dxf_mm: tuple[float, float]


def parse_shafts(raw: object) -> list[ShaftPoint]:
    """Шахты из `candidate.json`; невалидные элементы пропускаются, повтор id - первый."""
    items = raw.get("shafts") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    found: dict[str, ShaftPoint] = {}
    for item in items:
        try:
            shaft = _CandidateShaft.model_validate(item)
        except ValidationError:
            continue
        if not all(math.isfinite(v) for v in shaft.centroid_dxf_mm) or shaft.id in found:
            continue
        found[shaft.id] = ShaftPoint(
            id=shaft.id,
            systems=frozenset(shaft.systems),
            x=shaft.centroid_dxf_mm[0],
            y=shaft.centroid_dxf_mm[1],
        )
    return list(found.values())


async def load_sheet_shafts(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> list[ShaftPoint] | None:
    """Шахты листа; `None` - нет успешного задания трасс, файла или шахт в нём."""
    job = await cad_mep_service.succeeded_route_job(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    if job is None:
        return None
    attempt = cad_service.result_of(job).get("attempt")
    if type(attempt) is not int:
        return None
    try:
        name = f"{cad_service.view_folder(page_index, view)}/{cad_mep_service.CANDIDATE_JSON}"
        artifact = cad_service.find_artifact(job, name, attempt)
        key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
        if artifact is None or artifact.get("key") != key:
            return None
        raw = await cad_views.read_json(storage, key)
    except (
        ValueError,
        ObjectNotFoundError,
        StorageUnavailableError,
        cad_views.ArtifactTooLargeError,
    ):
        return None
    shafts = parse_shafts(raw)
    return shafts or None


async def copy_draft(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    source_page_index: int,
    source_view: int,
    risers: list[CadRiserEntry],
) -> CadRisersCopyOut:
    """Черновик реестра листа-цели из записей `risers` листа-источника."""
    source_shafts = await load_sheet_shafts(
        session,
        storage,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        page_index=source_page_index,
        view=source_view,
    )
    target_shafts = await load_sheet_shafts(
        session,
        storage,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    mapping = (
        map_shafts(source_shafts, target_shafts)
        if source_shafts is not None and target_shafts is not None
        else None
    )
    out_risers: list[CadRiserEntry] = []
    rows: list[CadRiserCopyRow] = []
    shafts: Literal["matched", "unknown"]
    if mapping is None or mapping.shift is None:
        shafts = "unknown"
        for index, entry in enumerate(risers):
            out_risers.append(entry)
            rows.append(
                CadRiserCopyRow(
                    index=index,
                    source_shaft_id=entry.shaft_id,
                    shaft_id=entry.shaft_id,
                    status="unverified",
                    distance_mm=None,
                )
            )
        shift_mm = None
    else:
        shafts = "matched"
        shift_mm = mapping.shift
        for index, entry in enumerate(risers):
            if entry.shaft_id is None:
                out_risers.append(entry)
                rows.append(
                    CadRiserCopyRow(
                        index=index,
                        source_shaft_id=None,
                        shaft_id=None,
                        status="no_shaft",
                        distance_mm=None,
                    )
                )
                continue
            match = mapping.matches.get(entry.shaft_id)
            out_risers.append(
                entry.model_copy(update={"shaft_id": match.target_id if match else None})
            )
            rows.append(
                CadRiserCopyRow(
                    index=index,
                    source_shaft_id=entry.shaft_id,
                    shaft_id=match.target_id if match else None,
                    status="matched" if match else "not_found",
                    distance_mm=match.distance_mm if match else None,
                )
            )
    return CadRisersCopyOut(
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        source_page_index=source_page_index,
        source_view=source_view,
        risers=out_risers,
        shafts=shafts,
        shift_mm=shift_mm,
        rows=rows,
    )


async def list_sheets(session: AsyncSession, *, revision_id: uuid.UUID) -> list[CadRisersSheetOut]:
    """Листы ревизии, у которых в реестре есть хотя бы одна запись."""
    rows = await session.scalars(
        select(CadSheetRisers)
        .where(
            CadSheetRisers.revision_id == revision_id,
            func.jsonb_array_length(CadSheetRisers.risers) > 0,
        )
        .order_by(CadSheetRisers.page_index, CadSheetRisers.view)
        .execution_options(populate_existing=True)
    )
    return [
        CadRisersSheetOut(
            page_index=row.page_index,
            view=row.view,
            risers_count=len(row.risers),
            updated_at=row.updated_at,
        )
        for row in rows
    ]
