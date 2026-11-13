"""Задание `cad_walls` (ADR-0038): параметры скрипта, постановка и поиск результата вида.

Задание строит `walls.json` по DXF вида результата `cad_pdf_convert`. Ставится автоматически
после успешной конвертации (для каждого вида с DXF) и вручную — пересчётом. Модуль стандартный:
скрипт `generators/cad_walls` репозитория движка (Shapely, ezdxf, PyMuPDF) запускает только
cad-worker подпроцессом. Версия скрипта и sha256 параметров берутся из pins.json.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_pins, cad_walls_zones
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)

WALLS_JSON: Final = "walls.json"
# Контроль движка PDF->DXF (`Контроль_CAD.json`) в артефактах конвертации; вход `--control` скрипта.
CONTROL_ARTIFACT: Final = "cad_checks.json"
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class WallsParams:
    """Параметры скрипта: путь, sha256 канонического JSON, версия скрипта и версия параметров."""

    path: Path
    sha256: str
    generator_version: str
    params_version: str


def runner_path(settings: Settings) -> Path | None:
    """Скрипт конструкций: `CAD_WALLS_RUNNER` или `<CAD_GENERATORS_ROOT>/cad_walls/run_walls.py`."""
    return cad_pins.generator_runner(
        settings, explicit=settings.cad_walls_runner, package="cad_walls", script="run_walls.py"
    )


def load_params(settings: Settings) -> WallsParams:
    """Версия скрипта и sha256 параметров берутся из `pins.json` (раздел `generators`).

    sha256 - канонического JSON параметров (как у скрипта и у параметров движка); версия
    параметров - имя файла без расширения (так её пишет скрипт в walls.json). Файл параметров
    читает только исполнитель; если он настроен (`CAD_WALLS_PARAMS` или `CAD_GENERATORS_ROOT`), его
    байты сверяются с пином. Нет закрепления - отказ, а не умолчание.
    """
    pin = cad_pins.load_generator_pin(settings, "cad_walls")
    path, configured = cad_pins.params_file(settings, settings.cad_walls_params, pin)
    if configured:
        cad_pins.verify_params_file(path, pin, "cad_walls")
    return WallsParams(
        path=path,
        sha256=pin.params_canonical_sha256,
        generator_version=pin.generator_version,
        params_version=path.stem,
    )


def idempotency_key(
    parent_id: uuid.UUID,
    *,
    parent_attempt: int,
    page_index: int,
    view: int,
    params_sha256: str,
    generator_version: str,
    sequence: int,
    zones_sha256: str = "",
) -> str:
    """Тот же вид, параметры, зоны и версия скрипта — то же задание; пересчёт — следующий номер."""
    digest = hashlib.sha256(
        "|".join(
            (
                str(parent_id),
                str(parent_attempt),
                str(page_index),
                str(view),
                params_sha256,
                generator_version,
                zones_sha256,
                str(sequence),
            )
        ).encode()
    ).hexdigest()
    return f"cadwalls:{digest[:48]}"


def view_has_dxf(parent: Job, page_index: int, view: int) -> dict[str, Any] | None:
    """Артефакт DXF вида в текущем итоге родителя; нет вида или DXF — `None`."""
    result = cad_service.current_result(parent)
    for page in result.get("pages", []):
        if page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if isinstance(row, dict) and row.get("view") == view:
                try:
                    folder = cad_service.view_folder(page_index, view)
                except ValueError:
                    return None
                return cad_service.find_artifact(parent, f"{folder}/plan_candidates.dxf")
    return None


async def walls_jobs_of_view(
    session: AsyncSession, *, parent: Job, page_index: int, view: int
) -> list[Job]:
    """Задания конструкций вида (все попытки родителя), новые сверху."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_WALLS,
            Job.workspace_id == parent.workspace_id,
            Job.payload["parent_job_id"].astext == str(parent.id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    return list(rows)


def _walls_payload(
    parent: Job,
    *,
    page_index: int,
    view: int,
    dxf_sha256: str,
    params: WallsParams,
    zones: cad_walls_zones.ZonesInput,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "revision_id": parent.payload["revision_id"],
        "parent_job_id": str(parent.id),
        "parent_attempt": cad_service.result_of(parent).get("attempt"),
        "page_index": page_index,
        "view": view,
        "view_dxf_sha256": dxf_sha256,
        "params_sha256": params.sha256,
        "params_version": params.params_version,
        "generator_version": params.generator_version,
        "engine_version": params.generator_version,
        # зоны помещений листа для контура плиты: пусты — стены без зон (прежнее поведение)
        "zones_sha256": zones.sha256,
        "zones_size": len(zones.raw),
        "zones_count": zones.count,
    }
    if zones.warning is not None:
        payload["zones_warning"] = zones.warning
    if zones.view_zone is not None:
        # прямоугольник вида в pt PDF: скрипт по центру выбирает заголовок плана (`--view-zone`)
        payload["view_zone"] = list(zones.view_zone)
    return payload


async def _enqueue(
    session: AsyncSession,
    *,
    parent: Job,
    page_index: int,
    view: int,
    dxf: dict[str, Any],
    params: WallsParams,
    sequence: int,
    zones: cad_walls_zones.ZonesInput = cad_walls_zones.NO_ZONES,
) -> Job:
    attempt = cad_service.result_of(parent).get("attempt")
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_WALLS,
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
            zones_sha256=zones.sha256,
        ),
        payload=_walls_payload(
            parent,
            page_index=page_index,
            view=view,
            dxf_sha256=str(dxf["sha256"]),
            params=params,
            zones=zones,
        ),
    )


async def enqueue_after_convert(
    session: AsyncSession, storage: ObjectStorage, parent: Job, settings: Settings
) -> list[Job]:
    """Автопостановка: по заданию на каждый вид успешного `cad_pdf_convert`, у которого есть DXF.

    Вызывается в транзакции записи успеха конвертации: задания появляются вместе с результатом.
    Параметры скрипта не нашлись — конвертация остаётся успешной, а конструкции ставятся
    вручную после исправления установки. Зоны помещений листа уходят входом задания, как у
    пересчёта; сбой их чтения конвертацию не рушит (задание без зон, причина в `zones_warning`).
    """
    try:
        params = load_params(settings)
    except DomainError:
        log.warning("cad_walls_params_unavailable", job_id=str(parent.id))
        return []
    jobs: list[Job] = []
    for page in cad_service.result_of(parent).get("pages", []):
        for row in page.get("views", []):
            page_index, view = page.get("index"), row.get("view")
            if type(page_index) is not int or type(view) is not int:
                continue
            dxf = view_has_dxf(parent, page_index, view)
            if dxf is None:
                continue
            zones = await cad_walls_zones.prepare_or_empty(
                session, storage, parent=parent, page_index=page_index, view=view
            )
            jobs.append(
                await _enqueue(
                    session,
                    parent=parent,
                    page_index=page_index,
                    view=view,
                    dxf=dxf,
                    params=params,
                    sequence=0,
                    zones=zones,
                )
            )
    return jobs


async def schedule_after_auto_zones(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    settings: Settings,
) -> Job | None:
    """Пересчёт конструкций вида после появления зон авторазметки; без 409 и без исключений.

    Первое задание листа без разметки человека уходит до авторазметки, то есть без зон. Нет DXF,
    параметров или самих зон либо уже активно задание вида с теми же зонами — ничего не
    ставится, причина в логе; активное задание без этих зон пересчёт не блокирует. Цикла нет:
    зоны авторазметка создаёт только на пустом листе, поэтому повторного успеха с новыми
    зонами не бывает, а ключ идемпотентности включает хеш зон и номер пересчёта.
    """
    try:
        params = load_params(settings)
    except DomainError:
        log.warning("cad_walls_params_unavailable", job_id=str(parent.id))
        return None
    await session.refresh(parent, with_for_update=True)
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        return None
    dxf = view_has_dxf(parent, page_index, view)
    if dxf is None:
        return None
    existing = await walls_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    zones = await cad_walls_zones.prepare_or_empty(
        session, storage, parent=parent, page_index=page_index, view=view
    )
    if not zones.present:
        log.info(
            "cad_walls_recompute_skipped_no_zones",
            job_id=str(parent.id),
            page_index=page_index,
            view=view,
        )
        return None
    # Активное задание вида с теми же зонами уже всё сделает. Активное без них (или с другими)
    # не мешает: пересчёт ставится следующим, а API берёт последнее успешное задание по created_at.
    if any(
        job.status in _ACTIVE and job.payload.get("zones_sha256") == zones.sha256
        for job in existing
    ):
        log.info(
            "cad_walls_recompute_skipped_same_zones",
            job_id=str(parent.id),
            page_index=page_index,
            view=view,
        )
        return None
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=params,
        sequence=len(existing),
        zones=zones,
    )


async def schedule_recompute(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    settings: Settings,
) -> Job:
    """Пересчёт конструкций вида новым заданием.

    Зоны квартир и МОП страницы уходят входом задания (контур плиты); нет кадра вида — без зон.

    Нельзя, пока задание этого вида в очереди или выполняется (409 `CAD_WALLS_BUSY`). Строка
    родителя берётся под блокировкой: два одновременных нажатия не ставят задание дважды.
    """
    if parent.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    await session.refresh(parent, with_for_update=True)
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    dxf = view_has_dxf(parent, page_index, view)
    if dxf is None:
        raise not_found("Вид")
    existing = await walls_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    if any(job.status in _ACTIVE for job in existing):
        raise DomainError(ErrorCode.CAD_WALLS_BUSY)
    zones = await cad_walls_zones.prepare(
        session, storage, parent=parent, page_index=page_index, view=view
    )
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=load_params(settings),
        sequence=len(existing),
        zones=zones,
    )
