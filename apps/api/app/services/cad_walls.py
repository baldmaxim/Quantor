"""Задание `cad_walls` (ADR-0038): параметры скрипта, постановка и поиск результата вида.

Задание строит `walls.json` по DXF вида результата `cad_pdf_convert`. Ставится автоматически
после успешной конвертации (для каждого вида с DXF) и вручную — пересчётом. Модуль стандартный:
скрипт `tools/cad_walls` (Shapely, ezdxf, PyMuPDF) запускает только cad-worker подпроцессом.
Файл параметров и версия скрипта читаются здесь лишь ради sha256 и версии.
"""

from __future__ import annotations

import hashlib
import json
import re
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
from app.services import jobs as jobs_service

log = get_logger(__name__)

WALLS_JSON: Final = "walls.json"
_VERSION_LINE: Final = re.compile(
    r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([A-Za-z0-9._-]{1,48})"', re.M
)
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class WallsParams:
    """Параметры скрипта: путь, sha256 канонического JSON, версия скрипта и версия параметров."""

    path: Path
    sha256: str
    generator_version: str
    params_version: str


def params_path(settings: Settings) -> Path:
    if settings.cad_walls_params.strip():
        return Path(settings.cad_walls_params)
    # .../<корень>/apps/api/app/services/cad_walls.py -> <корень>/tools/cad_walls/params/v1.json
    return Path(__file__).resolve().parents[4] / "tools" / "cad_walls" / "params" / "v1.json"


def version_path(params: Path) -> Path:
    """`<tools>/cad_walls/params/v1.json` -> `<tools>/cad_walls/cad_walls/version.py`."""
    return params.parent.parent / "cad_walls" / "version.py"


def load_params(settings: Settings) -> WallsParams:
    """sha256 считается по каноническому JSON, как у скрипта и у параметров движка.

    Версия скрипта — константа `GENERATOR_VERSION` в `cad_walls/version.py` рядом с параметрами;
    версия параметров — имя файла без расширения (так её пишет скрипт в walls.json). Не нашлись —
    отказ, а не умолчание: задание нельзя привязать к неизвестной версии.
    """
    path = params_path(settings)
    unavailable = DomainError(
        ErrorCode.CAD_ENGINE_UNAVAILABLE, "Параметры подсчёта конструкций не найдены"
    )
    try:
        raw = json.loads(path.read_bytes())
        found = _VERSION_LINE.search(version_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise unavailable from error
    if not isinstance(raw, dict) or found is None:
        raise unavailable
    return WallsParams(
        path=path,
        sha256=cad_service.params_sha256(raw),
        generator_version=found.group(1),
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
) -> str:
    """Тот же вид, параметры и версия скрипта — то же задание; пересчёт — следующий номер."""
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
    parent: Job, *, page_index: int, view: int, dxf_sha256: str, params: WallsParams
) -> dict[str, object]:
    return {
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
    }


async def _enqueue(
    session: AsyncSession,
    *,
    parent: Job,
    page_index: int,
    view: int,
    dxf: dict[str, Any],
    params: WallsParams,
    sequence: int,
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
        ),
        payload=_walls_payload(
            parent, page_index=page_index, view=view, dxf_sha256=str(dxf["sha256"]), params=params
        ),
    )


async def enqueue_after_convert(
    session: AsyncSession, parent: Job, settings: Settings
) -> list[Job]:
    """Автопостановка: по заданию на каждый вид успешного `cad_pdf_convert`, у которого есть DXF.

    Вызывается в транзакции записи успеха конвертации: задания появляются вместе с результатом.
    Параметры скрипта не нашлись — конвертация остаётся успешной, а конструкции ставятся
    вручную после исправления установки.
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
    return jobs


async def schedule_recompute(
    session: AsyncSession, *, parent: Job, page_index: int, view: int, settings: Settings
) -> Job:
    """Пересчёт конструкций вида новым заданием.

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
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=load_params(settings),
        sequence=len(existing),
    )
