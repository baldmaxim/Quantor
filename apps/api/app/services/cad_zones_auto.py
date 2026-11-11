"""Задание `cad_zones`: автоматическая разметка зон квартир по DXF вида (ADR-0036).

Задание ставится автоматически после успешной конвертации (для каждого вида с DXF, на листе
которого ещё нет зон) и вручную. Человеческую разметку оно не трогает никогда: нет зон на листе -
разметка ставится, есть - нет. Зоны листа хранятся по странице, а не по виду, поэтому «пустой вид»
здесь - лист без единой зоны. Сами зоны создаёт обработчик через общий сервис зон: площадь и
периметр считает сервер, как у ручных зон.

Модуль стандартный: CLI `cad_mep/run_zones.py` репозитория движка (PyMuPDF, Shapely) запускает
только cad-worker подпроцессом. Версия генератора и sha256 параметров - из pins.json.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadZone, Job
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_walls
from app.services import jobs as jobs_service

log = get_logger(__name__)

ZONES_JSON: Final = "zones.json"
ZONES_SCHEMA: Final = "quantor.cad_mep.zones.v1"
RESULT_READY: Final = "zones_ready"
RESULT_SKIPPED_EXISTING: Final = "zones_skipped_existing"
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)
RUNNER_NAME: Final = "run_zones.py"


def runner_path(settings: Settings) -> Path | None:
    """CLI зон лежит рядом с генератором трасс; генератор не настроен - зон тоже нет."""
    mep_runner = cad_mep_service.runner_path(settings)
    return mep_runner.with_name(RUNNER_NAME) if mep_runner is not None else None


def idempotency_key(
    parent_id: uuid.UUID,
    *,
    parent_attempt: int,
    page_index: int,
    view: int,
    params_sha256: str,
    generator_version: str,
    sequence: int,
) -> str:
    """Тот же вид, параметры и версия генератора - то же задание; повтор - следующий номер."""
    digest = hashlib.sha256(
        "|".join(
            (
                str(parent_id),
                str(parent_attempt),
                str(page_index),
                str(view),
                params_sha256,
                generator_version,
                str(sequence),
            )
        ).encode()
    ).hexdigest()
    return f"cadzones:{digest[:48]}"


async def page_zone_count(session: AsyncSession, *, revision_id: uuid.UUID, page_index: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(CadZone)
        .where(CadZone.revision_id == revision_id, CadZone.page_index == page_index)
    )
    return int(count or 0)


async def zones_jobs_of_view(
    session: AsyncSession, *, parent: Job, page_index: int, view: int
) -> list[Job]:
    """Задания разметки вида по всем попыткам родителя, новые сверху."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_ZONES,
            Job.workspace_id == parent.workspace_id,
            Job.payload["revision_id"].astext == str(parent.payload["revision_id"]),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    return list(rows)


def _zones_payload(
    parent: Job,
    *,
    page_index: int,
    view: int,
    dxf_sha256: str,
    params: cad_mep_service.MepParams,
) -> dict[str, object]:
    return {
        "revision_id": parent.payload["revision_id"],
        "parent_job_id": str(parent.id),
        "parent_attempt": cad_service.result_of(parent).get("attempt"),
        "page_index": page_index,
        "view": view,
        "view_dxf_sha256": dxf_sha256,
        "params_sha256": params.sha256,
        "generator_version": params.generator_version,
        "engine_version": params.generator_version,
    }


async def _enqueue(
    session: AsyncSession,
    *,
    parent: Job,
    page_index: int,
    view: int,
    dxf: dict[str, Any],
    params: cad_mep_service.MepParams,
    sequence: int,
) -> Job:
    attempt = cad_service.result_of(parent).get("attempt")
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_ZONES,
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        idempotency_key=idempotency_key(
            parent.id,
            parent_attempt=int(attempt) if type(attempt) is int else 0,
            page_index=page_index,
            view=view,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            sequence=sequence,
        ),
        payload=_zones_payload(
            parent, page_index=page_index, view=view, dxf_sha256=str(dxf["sha256"]), params=params
        ),
    )


async def enqueue_after_convert(
    session: AsyncSession, parent: Job, settings: Settings
) -> list[Job]:
    """Автопостановка: задание на каждый вид с DXF, на листе которого нет ни одной зоны.

    Вызывается в транзакции записи успеха конвертации. Генератор или его параметры не настроены,
    ошибка постановки - конвертация остаётся успешной: разметку можно запустить вручную.
    """
    if runner_path(settings) is None:
        return []
    try:
        params = cad_mep_service.load_params(settings)
    except DomainError:
        log.warning("cad_zones_params_unavailable", job_id=str(parent.id))
        return []
    revision_raw = parent.payload.get("revision_id")
    try:
        revision_id = uuid.UUID(str(revision_raw))
    except ValueError:
        return []
    jobs: list[Job] = []
    for page in cad_service.result_of(parent).get("pages", []):
        for row in page.get("views", []):
            page_index, view = page.get("index"), row.get("view")
            if type(page_index) is not int or type(view) is not int:
                continue
            dxf = cad_walls.view_has_dxf(parent, page_index, view)
            if dxf is None:
                continue
            try:
                async with session.begin_nested():
                    if await page_zone_count(
                        session, revision_id=revision_id, page_index=page_index
                    ):
                        continue
                    jobs.append(
                        await _enqueue(
                            session,
                            parent=parent,
                            page_index=page_index,
                            view=view,
                            dxf=dxf,
                            params=params,
                            sequence=0,
                        )
                    )
            except (DomainError, SQLAlchemyError):
                log.warning(
                    "cad_zones_enqueue_failed",
                    job_id=str(parent.id),
                    page_index=page_index,
                    view=view,
                )
    return jobs


async def schedule_manual(
    session: AsyncSession, *, parent: Job, page_index: int, view: int, settings: Settings
) -> Job:
    """Ручной запуск разметки вида.

    409 `CAD_ZONES_NOT_EMPTY` - на листе уже есть зоны; 409 `CAD_ZONES_BUSY` - задание этого вида
    в очереди или выполняется. Строка родителя берётся под блокировкой: два нажатия подряд не
    ставят задание дважды.
    """
    if parent.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    await session.refresh(parent, with_for_update=True)
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    dxf = cad_walls.view_has_dxf(parent, page_index, view)
    if dxf is None:
        raise not_found("Вид")
    if await page_zone_count(
        session, revision_id=uuid.UUID(str(parent.payload["revision_id"])), page_index=page_index
    ):
        raise DomainError(ErrorCode.CAD_ZONES_NOT_EMPTY)
    existing = await zones_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    if any(job.status in _ACTIVE for job in existing):
        raise DomainError(ErrorCode.CAD_ZONES_BUSY)
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=cad_mep_service.load_params(settings),
        sequence=len(existing),
    )
