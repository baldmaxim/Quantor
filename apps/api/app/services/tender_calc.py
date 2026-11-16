"""Чтение репозиториев расчётов TENDER и их версий (ADR-0051).

Версия неизменяема; меняются только статус (`active` → `superseded`, `withdrawn`) и отметка отзыва.
Геометрия видов лежит в хранилище и читается по требованию; в базе — свод объёмов, вопросы,
предупреждения приёма и ключи файлов. Признак `base_stale` не хранится: он зависит от того, что
движок перестроил вид уже после выпуска базы, и вычисляется при чтении.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.tender_exchange import (
    CalcDiscipline,
    CalcViewFile,
    DiffStatus,
    TenderBuildingLayerRead,
    TenderCalcRead,
    TenderCalcVersionRead,
    TenderCalcVersionSummaryRead,
    TenderCalcViewRead,
    TenderQuantityDiffRead,
    TenderQuantityRowRead,
    TenderQuestionRead,
    TenderViewInfoRead,
    TenderViewLayerRead,
    TenderWarningRead,
    VersionStatus,
    make_view_key,
)
from app.errors import DomainError, ErrorCode, http_error
from app.models import TenderBaseRelease, TenderCalc, TenderCalcVersion
from app.services import tender_base
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

READ_CONCURRENCY: Final = 6
_EPS: Final = 1e-9
_DISCIPLINE: Final[TypeAdapter[CalcDiscipline]] = TypeAdapter(CalcDiscipline)
_STATUS: Final[TypeAdapter[VersionStatus]] = TypeAdapter(VersionStatus)


async def list_calcs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[TenderCalcRead]:
    """Репозитории проекта и их последняя действующая версия."""
    calcs = list(
        await session.scalars(
            select(TenderCalc)
            .where(TenderCalc.workspace_id == workspace_id, TenderCalc.project_id == project_id)
            .order_by(TenderCalc.discipline, TenderCalc.system, TenderCalc.title)
        )
    )
    if not calcs:
        return []
    ids = [calc.id for calc in calcs]
    counts = dict(
        (
            await session.execute(
                select(TenderCalcVersion.calc_id, func.count())
                .where(TenderCalcVersion.calc_id.in_(ids))
                .group_by(TenderCalcVersion.calc_id)
            )
        )
        .tuples()
        .all()
    )
    active = {
        version.calc_id: version
        for version in await session.scalars(
            select(TenderCalcVersion).where(
                TenderCalcVersion.calc_id.in_(ids), TenderCalcVersion.status == "active"
            )
        )
    }
    releases = await _release_numbers(session, [v.base_release_id for v in active.values()])
    names = await tender_base.user_names(session, [v.uploaded_by for v in active.values()])
    return [
        TenderCalcRead(
            id=calc.id,
            project_id=calc.project_id,
            discipline=_DISCIPLINE.validate_python(calc.discipline),
            system=calc.system,
            title=calc.title,
            created_at=calc.created_at,
            version_count=counts.get(calc.id, 0),
            active_version=(
                summary(active[calc.id], releases, names) if calc.id in active else None
            ),
        )
        for calc in calcs
    ]


async def _release_numbers(
    session: AsyncSession, release_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not release_ids:
        return {}
    rows = await session.execute(
        select(TenderBaseRelease.id, TenderBaseRelease.number).where(
            TenderBaseRelease.id.in_(set(release_ids))
        )
    )
    return dict(rows.tuples().all())


def summary(
    version: TenderCalcVersion, releases: dict[uuid.UUID, int], names: dict[uuid.UUID, str]
) -> TenderCalcVersionSummaryRead:
    return TenderCalcVersionSummaryRead(
        id=version.id,
        calc_id=version.calc_id,
        number=version.number,
        label=version.label,
        message=version.message,
        author=version.author,
        uploaded_by_name=names.get(version.uploaded_by) if version.uploaded_by else None,
        uploaded_at=version.uploaded_at,
        status=_STATUS.validate_python(version.status),
        base_release_id=version.base_release_id,
        base_release_number=releases.get(version.base_release_id, 0),
        quantity_rows=len(version.quantities),
        question_count=len(version.questions),
        warning_count=len(version.warnings),
        view_count=len(version.views),
    )


async def get_calc(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, calc_id: uuid.UUID
) -> TenderCalc | None:
    calc: TenderCalc | None = await session.scalar(
        select(TenderCalc).where(
            TenderCalc.id == calc_id,
            TenderCalc.workspace_id == workspace_id,
            TenderCalc.project_id == project_id,
        )
    )
    return calc


async def list_versions(
    session: AsyncSession, *, calc: TenderCalc
) -> list[TenderCalcVersionSummaryRead]:
    versions = list(
        await session.scalars(
            select(TenderCalcVersion)
            .where(TenderCalcVersion.calc_id == calc.id)
            .order_by(TenderCalcVersion.number.desc())
        )
    )
    releases = await _release_numbers(session, [v.base_release_id for v in versions])
    names = await tender_base.user_names(session, [v.uploaded_by for v in versions])
    return [summary(version, releases, names) for version in versions]


async def get_version(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    lock: bool = False,
) -> tuple[TenderCalcVersion, TenderCalc] | None:
    query = (
        select(TenderCalcVersion, TenderCalc)
        .join(TenderCalc, TenderCalcVersion.calc_id == TenderCalc.id)
        .where(
            TenderCalcVersion.id == version_id,
            TenderCalc.workspace_id == workspace_id,
            TenderCalc.project_id == project_id,
        )
    )
    if lock:
        query = query.with_for_update(of=TenderCalcVersion)
    row = (await session.execute(query)).first()
    return None if row is None else (row[0], row[1])


def diff_quantities(
    previous: Sequence[dict[str, Any]], current: Sequence[dict[str, Any]]
) -> list[TenderQuantityDiffRead]:
    """Разница объёмов по `code`: добавлено, удалено, изменено, без изменений."""
    prev = {str(row["code"]): row for row in previous}
    now = {str(row["code"]): row for row in current}
    result: list[TenderQuantityDiffRead] = []
    for code in [*now, *(code for code in prev if code not in now)]:
        before, after = prev.get(code), now.get(code)
        qty_prev = float(before["qty"]) if before is not None else None
        qty = float(after["qty"]) if after is not None else None
        delta = (qty or 0.0) - (qty_prev or 0.0)
        status: DiffStatus
        if before is None:
            status = "added"
        elif after is None:
            status = "removed"
        elif abs(delta) > _EPS:
            status = "changed"
        else:
            status = "same"
        row = after if after is not None else before
        assert row is not None
        result.append(
            TenderQuantityDiffRead(
                code=code,
                name=str(row["name"]),
                unit=str(row["unit"]),
                qty_prev=qty_prev,
                qty=qty,
                delta=round(delta, 6),
                status=status,
            )
        )
    return result


async def previous_version(
    session: AsyncSession, *, version: TenderCalcVersion
) -> TenderCalcVersion | None:
    """Ближайшая прошлая версия репозитория (отозванные пропускаются)."""
    previous: TenderCalcVersion | None = await session.scalar(
        select(TenderCalcVersion)
        .where(
            TenderCalcVersion.calc_id == version.calc_id,
            TenderCalcVersion.number < version.number,
            TenderCalcVersion.status != "withdrawn",
        )
        .order_by(TenderCalcVersion.number.desc())
        .limit(1)
    )
    return previous


async def stale_flags(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    versions: Sequence[TenderCalcVersion],
) -> dict[tuple[uuid.UUID, str], bool]:
    """`base_stale` по (версия, вид): текущий sha256 DXF вида не равен записанному в выпуске."""
    release_ids = {version.base_release_id for version in versions}
    releases = {
        release.id: release
        for release in await session.scalars(
            select(TenderBaseRelease).where(TenderBaseRelease.id.in_(release_ids))
        )
    }
    keys = [str(view["view_key"]) for version in versions for view in version.views]
    current = await tender_base.current_dxf_hashes(
        session, workspace_id=workspace_id, project_id=project_id, view_keys=keys
    )
    flags: dict[tuple[uuid.UUID, str], bool] = {}
    for version in versions:
        released = {
            str(view["key"]).lower(): view.get("dxf_sha256")
            for view in releases[version.base_release_id].views
        }
        for view in version.views:
            key = str(view["view_key"])
            flags[(version.id, key)] = current.get(key) != released.get(key.lower())
    return flags


async def version_read(
    session: AsyncSession,
    *,
    version: TenderCalcVersion,
    calc: TenderCalc,
) -> TenderCalcVersionRead:
    releases = await _release_numbers(session, [version.base_release_id])
    names = await tender_base.user_names(session, [version.uploaded_by])
    base = summary(version, releases, names)
    prev = await previous_version(session, version=version)
    flags = await stale_flags(
        session, workspace_id=calc.workspace_id, project_id=calc.project_id, versions=[version]
    )
    return TenderCalcVersionRead(
        **base.model_dump(),
        discipline=_DISCIPLINE.validate_python(calc.discipline),
        system=calc.system,
        title=calc.title,
        producer={str(key): str(value) for key, value in version.producer.items()},
        fit=list(version.fit),
        quantities=[TenderQuantityRowRead.model_validate(row) for row in version.quantities],
        questions=[TenderQuestionRead.model_validate(row) for row in version.questions],
        views=[
            TenderViewInfoRead(
                view_key=str(view["view_key"]),
                revision_id=uuid.UUID(str(view["revision_id"])),
                page_index=int(view["page_index"]),
                view=int(view["view"]),
                floors=[str(floor) for floor in view["floors"]],
                dxf_sha256=str(view["dxf_sha256"]),
                polylines=int(view["polylines"]),
                elements=int(view["elements"]),
                base_stale=flags[(version.id, str(view["view_key"]))],
            )
            for view in version.views
        ],
        warnings=[TenderWarningRead.model_validate(row) for row in version.warnings],
        package_sha256=version.package_sha256,
        prev_version_id=prev.id if prev is not None else None,
        diff=diff_quantities(prev.quantities, version.quantities) if prev is not None else [],
    )


async def withdraw(
    session: AsyncSession, version: TenderCalcVersion, *, user_id: uuid.UUID
) -> bool:
    """Отзыв версии: она уходит из показа. Повтор - без эффекта; новой действующей не появляется."""
    if version.status == "withdrawn":
        return False
    version.status = "withdrawn"
    version.withdrawn_by = user_id
    version.withdrawn_at = datetime.now(UTC)
    await session.flush()
    return True


# --------------------------------------------------------------------------- геометрия видов


def _find_view(version: TenderCalcVersion, view_key: str) -> dict[str, Any] | None:
    wanted = view_key.lower()
    return next((v for v in version.views if str(v["view_key"]).lower() == wanted), None)


async def read_view_file(storage: ObjectStorage, entry: dict[str, Any]) -> CalcViewFile:
    """Файл вида версии из хранилища; повреждённый - 500 движка, недоступное хранилище - 503."""
    key = str(entry["object_key"])
    try:
        chunks = [chunk async for chunk in storage.iter_stream(key)]
        return await asyncio.to_thread(CalcViewFile.model_validate_json, b"".join(chunks))
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "Файл вида расчёта вне контракта") from error


async def view_read(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    version: TenderCalcVersion,
    calc: TenderCalc,
    view_key: str,
) -> TenderCalcViewRead | None:
    entry = _find_view(version, view_key)
    if entry is None:
        return None
    file = await read_view_file(storage, entry)
    flags = await stale_flags(
        session, workspace_id=calc.workspace_id, project_id=calc.project_id, versions=[version]
    )
    return TenderCalcViewRead(
        version_id=version.id,
        view_key=str(entry["view_key"]),
        floors=file.floors,
        polylines=file.polylines,
        elements=file.elements,
        base_stale=flags[(version.id, str(entry["view_key"]))],
    )


async def active_versions(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    view_key: str | None = None,
) -> list[tuple[TenderCalcVersion, TenderCalc]]:
    """Действующие версии проекта; с `view_key` - только те, где есть этот вид."""
    query = (
        select(TenderCalcVersion, TenderCalc)
        .join(TenderCalc, TenderCalcVersion.calc_id == TenderCalc.id)
        .where(
            TenderCalc.workspace_id == workspace_id,
            TenderCalc.project_id == project_id,
            TenderCalcVersion.status == "active",
        )
        .order_by(TenderCalc.discipline, TenderCalc.system, TenderCalc.title)
    )
    rows = [(row[0], row[1]) for row in (await session.execute(query)).all()]
    if view_key is None:
        return rows
    return [(version, calc) for version, calc in rows if _find_view(version, view_key) is not None]


async def view_layers(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> list[TenderViewLayerRead]:
    """Слой «Расчёты» вида: геометрия действующих версий, у которых есть этот вид."""
    view_key = make_view_key(revision_id, page_index, view)
    found = await active_versions(
        session, workspace_id=workspace_id, project_id=project_id, view_key=view_key
    )
    if not found:
        return []
    flags = await stale_flags(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        versions=[version for version, _calc in found],
    )
    gate = asyncio.Semaphore(READ_CONCURRENCY)

    async def load(entry: dict[str, Any]) -> CalcViewFile:
        async with gate:
            return await read_view_file(storage, entry)

    entries = [_find_view(version, view_key) for version, _calc in found]
    files = await asyncio.gather(*(load(entry) for entry in entries if entry is not None))
    layers: list[TenderViewLayerRead] = []
    for (version, calc), entry, file in zip(found, entries, files, strict=True):
        assert entry is not None
        layers.append(
            TenderViewLayerRead(
                version_id=version.id,
                calc_id=calc.id,
                discipline=_DISCIPLINE.validate_python(calc.discipline),
                system=calc.system,
                title=calc.title,
                number=version.number,
                label=version.label,
                floors=file.floors,
                polylines=file.polylines,
                elements=file.elements,
                base_stale=flags[(version.id, str(entry["view_key"]))],
            )
        )
    return layers


async def building_layers(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[TenderBuildingLayerRead]:
    """Действующие версии проекта и виды, на которых у них есть геометрия (слой в 3D здания)."""
    found = await active_versions(session, workspace_id=workspace_id, project_id=project_id)
    return [
        TenderBuildingLayerRead(
            version_id=version.id,
            calc_id=calc.id,
            discipline=_DISCIPLINE.validate_python(calc.discipline),
            system=calc.system,
            title=calc.title,
            number=version.number,
            label=version.label,
            view_keys=[str(view["view_key"]) for view in version.views],
        )
        for version, calc in found
    ]
