"""ЭОМ и СС этажа по одобренному виду CAD: постановка задания `cad_eom_route` и чтение результата.

Цепочка та же, что у трасс механики (`cad_mep`): успешное `cad_pdf_convert` -> человек одобряет вид
(`view_approval`) -> `cad_eom_route` строит ЭОМ и СС этажа по тому же виду, тем же отметке пола,
высоте этажа и уровням. Результат - кандидат: `eom_routes3d.json` (сети и приборы в 3D, Z от
отметки этажа), `eom_candidate.json` (щиты, квартиры, ведомость количеств с формулами и
источниками) и `eom_routes.dxf`. Ничего не принимается и не одобряется по умолчанию.

Модуль стандартный: генератор (`generators/cad_eom` репозитория движка) запускает только
cad-worker подпроцессом; версия генератора и sha256 параметров берутся из pins.json.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import Job, Project
from app.models.cad_decision import DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_pins
from app.services import jobs as jobs_service

ROUTES3D_JSON: Final = "eom_routes3d.json"
CANDIDATE_JSON: Final = "eom_candidate.json"
ROUTES_DXF: Final = "eom_routes.dxf"
ROUTES3D_SCHEMA: Final = "cad_eom_routes3d.v1"
CANDIDATE_SCHEMA: Final = "quantor.cad_eom.candidate.v1"
OUTPUT_FILES: Final = (ROUTES3D_JSON, CANDIDATE_JSON, ROUTES_DXF)


@dataclass(frozen=True, slots=True)
class EomParams:
    """Параметры генератора: путь к файлу, sha256 канонического JSON и версия генератора."""

    path: Path
    sha256: str
    generator_version: str


def runner_path(settings: Settings) -> Path | None:
    """Скрипт ЭОМ: `CAD_EOM_RUNNER` или `<CAD_GENERATORS_ROOT>/cad_eom/run_eom.py`, иначе `None`."""
    return cad_pins.generator_runner(
        settings, explicit=settings.cad_eom_runner, package="cad_eom", script="run_eom.py"
    )


def load_params(settings: Settings) -> EomParams:
    """Версия и sha256 параметров - из `pins.json` (`generators.cad_eom`); нет пина - отказ."""
    pin = cad_pins.load_generator_pin(settings, "cad_eom")
    path, configured = cad_pins.params_file(settings, settings.cad_eom_params, pin)
    if configured:
        cad_pins.verify_params_file(path, pin, "cad_eom")
    return EomParams(
        path=path, sha256=pin.params_canonical_sha256, generator_version=pin.generator_version
    )


def eom_idempotency_key(
    approval_id: uuid.UUID,
    *,
    params_sha256: str,
    generator_version: str,
    floor_elevation_mm: int | None,
    floor_height_mm: int | None,
    clear_height_mm: int | None,
    slab_thickness_mm: int | None,
) -> str:
    """То же одобрение, параметры, версия генератора и уровни - то же задание.

    Пересчёта у ЭОМ нет: другая отметка, высота этажа или уровни - новое задание.
    """
    digest = hashlib.sha256(
        "|".join(
            (
                str(approval_id),
                params_sha256,
                generator_version,
                f"elev={floor_elevation_mm}",
                f"height={floor_height_mm}",
                f"clear={clear_height_mm}",
                f"slab={slab_thickness_mm}",
            )
        ).encode()
    ).hexdigest()
    return f"cadeom:{digest[:48]}"


async def schedule_eom(
    session: AsyncSession,
    *,
    project: Project,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    floor_elevation_mm: int | None,
    floor_height_mm: int | None,
    settings: Settings,
    clear_height_mm: int | None = None,
    slab_thickness_mm: int | None = None,
    levels_source: str = "none",
) -> Job:
    """Задание `cad_eom_route` по одобренному виду - те же проверки входа, что у трасс механики.

    Нет действующего одобрения - 409 CAD_VIEW_NOT_APPROVED (отозвано - CAD_VIEW_APPROVAL_REVOKED).
    Высота в свету и толщина плиты вместе не передаются (у генератора это `levels_conflict`).
    """
    if job.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    if clear_height_mm is not None and slab_thickness_mm is not None:
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID, "Высота в свету и толщина плиты не задаются вместе"
        )
    result = cad_mep_service._succeeded_current(job, attempt)
    cad_mep_service._view_row(result, page_index, view)
    folder = cad_mep_service._folder(page_index, view)
    approval = await cad_mep_service.find_decision(
        session,
        kind=DECISION_VIEW_APPROVAL,
        job_id=job.id,
        attempt=attempt,
        page_index=page_index,
        view=view,
    )
    if approval is None:
        revoked = await cad_mep_service.find_decision(
            session,
            kind=DECISION_VIEW_APPROVAL,
            job_id=job.id,
            attempt=attempt,
            page_index=page_index,
            view=view,
            revoked=True,
        )
        raise DomainError(
            ErrorCode.CAD_VIEW_APPROVAL_REVOKED
            if revoked is not None
            else ErrorCode.CAD_VIEW_NOT_APPROVED
        )
    dxf = cad_service.find_artifact(job, f"{folder}/plan_candidates.dxf")
    for name in ("scale.json", "preview.json"):
        if cad_service.find_artifact(job, f"{folder}/{name}") is None:
            raise DomainError(ErrorCode.CAD_INPUT_INVALID, f"У вида нет {name}")
    if dxf is None or dxf.get("sha256") != approval.artifact_sha256:
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "DXF вида не совпадает с одобренным")
    params = load_params(settings)
    route = await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_EOM_ROUTE,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=eom_idempotency_key(
            approval.id,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            floor_elevation_mm=floor_elevation_mm,
            floor_height_mm=floor_height_mm,
            clear_height_mm=clear_height_mm,
            slab_thickness_mm=slab_thickness_mm,
        ),
        # Поля входа - те же, что у `cad_mep_route`: исполнитель проверяет их общей функцией.
        payload={
            "revision_id": job.payload["revision_id"],
            "parent_job_id": str(job.id),
            "parent_attempt": attempt,
            "page_index": page_index,
            "view": view,
            "view_dxf_sha256": approval.artifact_sha256,
            "approval_id": str(approval.id),
            "floor_elevation_mm": floor_elevation_mm,
            "floor_height_mm": floor_height_mm,
            "clear_height_mm": clear_height_mm,
            "slab_thickness_mm": slab_thickness_mm,
            "levels_source": levels_source,
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
        },
    )
    return await cad_service.requeue_if_retryable_failure(
        session, route, settings=settings, refresh=False
    )


async def latest_succeeded_eom_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> Job | None:
    """Новейшее успешное `cad_eom_route` листа (ревизия, страница, вид)."""
    found: Job | None = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_EOM_ROUTE,
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["revision_id"].astext == str(revision_id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return found


async def latest_eom_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> Job | None:
    """Новейшее `cad_eom_route` листа в любом статусе: для показа хода и отказа."""
    found: Job | None = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_EOM_ROUTE,
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.payload["revision_id"].astext == str(revision_id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return found
