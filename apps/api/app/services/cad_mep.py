"""Трассы механики по одобренному виду CAD (ADR-0036 п. 8): решения человека и постановка.

Цепочка: успешное `cad_pdf_convert` -> человек проверяет вид и ставит `view_approval` (нет
открытых замечаний) -> `cad_mep_route` строит трассы (отметки пола и высота этажа вводит человек)
-> человек проверяет трассы замечаниями и ставит `mep_acceptance` -> открывается скачивание
`mep_routes.dxf`. Решения неизменяемы; по умолчанию ничего не принимается и не одобряется.

Модуль стандартный: генератор (`tools/cad_mep`, PyMuPDF/Shapely/ezdxf) запускает только
cad-worker подпроцессом; сюда эти пакеты не импортируются. Файл параметров генератора читается
только ради sha256 и версии.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadDecision, CadRemark, Job, Project, UserIdentity
from app.models.cad_decision import DECISION_MEP_ACCEPTANCE, DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import jobs as jobs_service

_VERSION_LINE: Final = re.compile(
    r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([A-Za-z0-9._-]{1,48})"', re.M
)
UNIQUE_DECISION: Final = "uq_cad_decisions_kind_job_attempt_page_view"

ROUTES_DXF: Final = "mep_routes.dxf"
CANDIDATE_JSON: Final = "candidate.json"
PREVIEW_JSON: Final = "preview.json"
CANDIDATE_SCHEMA: Final = "quantor.cad_mep.candidate.v1"
PREVIEW_SCHEMA: Final = "quantor.cad_engine.preview.v1"

# Отметка пола и высота этажа — ввод человека; допустимые пределы, мм.
ELEVATION_MIN_MM: Final = -100_000
ELEVATION_MAX_MM: Final = 1_000_000
FLOOR_HEIGHT_MIN_MM: Final = 2000
FLOOR_HEIGHT_MAX_MM: Final = 6000


@dataclass(frozen=True, slots=True)
class MepParams:
    """Параметры генератора: путь к файлу, sha256 канонического JSON и версия генератора."""

    path: Path
    sha256: str
    generator_version: str


def params_path(settings: Settings) -> Path:
    if settings.cad_mep_params.strip():
        return Path(settings.cad_mep_params)
    # .../<корень>/apps/api/app/services/cad_mep.py -> <корень>/tools/cad_mep/params/v1.json
    return Path(__file__).resolve().parents[4] / "tools" / "cad_mep" / "params" / "v1.json"


def version_path(params: Path) -> Path:
    """`<tools>/cad_mep/params/v1.json` -> `<tools>/cad_mep/cad_mep/version.py`."""
    return params.parent.parent / "cad_mep" / "version.py"


def load_params(settings: Settings) -> MepParams:
    """sha256 считается по каноническому JSON, как у параметров движка (`params_sha256`).

    Версия генератора - константа `GENERATOR_VERSION` в `cad_mep/version.py` рядом с параметрами
    (в файле параметров лежат только константы с источником, версии там нет). Не нашлась - отказ,
    а не умолчание: задание нельзя привязать к неизвестной версии.
    """
    path = params_path(settings)
    unavailable = DomainError(
        ErrorCode.CAD_ENGINE_UNAVAILABLE, "Параметры трасс механики не найдены"
    )
    try:
        raw = json.loads(path.read_bytes())
        found = _VERSION_LINE.search(version_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise unavailable from error
    if not isinstance(raw, dict) or found is None:
        raise unavailable
    return MepParams(
        path=path, sha256=cad_service.params_sha256(raw), generator_version=found.group(1)
    )


def route_idempotency_key(
    approval_id: uuid.UUID,
    *,
    params_sha256: str,
    generator_version: str,
    floor_elevation_mm: int,
    floor_height_mm: int,
) -> str:
    """То же одобрение, параметры, версия генератора и отметки - то же задание."""
    digest = hashlib.sha256(
        "|".join(
            (
                str(approval_id),
                params_sha256,
                generator_version,
                str(floor_elevation_mm),
                str(floor_height_mm),
            )
        ).encode()
    ).hexdigest()
    return f"cadmep:{digest[:48]}"


# ------------------------------------------------------------------ чтение состояния


@dataclass(slots=True)
class MepState:
    """Решения и route-задания для набора заданий CAD (один проход по базе)."""

    # (job_id, attempt, page_index, view) -> (решение, имя автора)
    approvals: dict[tuple[uuid.UUID, int, int, int], tuple[CadDecision, str | None]] = field(
        default_factory=dict
    )
    acceptances: dict[tuple[uuid.UUID, int, int, int], tuple[CadDecision, str | None]] = field(
        default_factory=dict
    )
    # parent_job_id -> route-задания, новые сверху
    routes: dict[uuid.UUID, list[Job]] = field(default_factory=dict)


def payload_int(job: Job, key: str) -> int | None:
    value = job.payload.get(key)
    return value if type(value) is int else None


def parent_job_id_of(job: Job) -> uuid.UUID | None:
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        return None
    try:
        return uuid.UUID(str(job.payload.get("parent_job_id")))
    except ValueError:
        return None


async def load_state(session: AsyncSession, jobs: list[Job]) -> MepState:
    state = MepState()
    convert_ids = [job.id for job in jobs if job.job_type is JobType.CAD_PDF_CONVERT]
    route_jobs = [job for job in jobs if job.job_type is JobType.CAD_MEP_ROUTE]
    if convert_ids:
        found = await session.scalars(
            select(Job)
            .where(
                Job.job_type == JobType.CAD_MEP_ROUTE,
                Job.workspace_id == jobs[0].workspace_id,
                Job.payload["parent_job_id"].astext.in_([str(i) for i in convert_ids]),
            )
            .order_by(Job.created_at.desc())
        )
        for route in found:
            parent = parent_job_id_of(route)
            if parent is not None:
                state.routes.setdefault(parent, []).append(route)
                route_jobs.append(route)
    ids = {*convert_ids, *(job.id for job in route_jobs)}
    if not ids:
        return state
    rows = await session.execute(
        select(CadDecision, UserIdentity.display_name, UserIdentity.email)
        .join(UserIdentity, UserIdentity.id == CadDecision.decided_by)
        .where(CadDecision.job_id.in_(ids))
    )
    for decision, display_name, email in rows.all():
        key = (decision.job_id, decision.attempt, decision.page_index, decision.view)
        target = state.approvals if decision.kind == DECISION_VIEW_APPROVAL else state.acceptances
        target[key] = (decision, display_name or email)
    return state


async def find_decision(
    session: AsyncSession,
    *,
    kind: str,
    job_id: uuid.UUID,
    attempt: int,
    page_index: int,
    view: int,
) -> CadDecision | None:
    found: CadDecision | None = await session.scalar(
        select(CadDecision).where(
            CadDecision.kind == kind,
            CadDecision.job_id == job_id,
            CadDecision.attempt == attempt,
            CadDecision.page_index == page_index,
            CadDecision.view == view,
        )
    )
    return found


async def decision_author(session: AsyncSession, decision: CadDecision) -> str | None:
    row = (
        await session.execute(
            select(UserIdentity.display_name, UserIdentity.email).where(
                UserIdentity.id == decision.decided_by
            )
        )
    ).first()
    return None if row is None else (row[0] or row[1])


async def open_remark_count(
    session: AsyncSession, *, job: Job, attempt: int, page_index: int, view: int
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(CadRemark)
        .where(
            CadRemark.job_id == job.id,
            CadRemark.attempt == attempt,
            CadRemark.page_index == page_index,
            CadRemark.view == view,
            CadRemark.status == "open",
        )
    )
    return int(count or 0)


async def routes_download_allowed(session: AsyncSession, job: Job) -> bool:
    """`mep_routes.dxf` отдаётся только по принятию трасс этого задания и его попытки."""
    result = cad_service.result_of(job)
    attempt = result.get("attempt")
    page_index = payload_int(job, "page_index")
    view = payload_int(job, "view")
    if type(attempt) is not int or page_index is None or view is None:
        return False
    return (
        await find_decision(
            session,
            kind=DECISION_MEP_ACCEPTANCE,
            job_id=job.id,
            attempt=attempt,
            page_index=page_index,
            view=view,
        )
        is not None
    )


# ------------------------------------------------------------------ решения и постановка


def _succeeded_current(job: Job, attempt: int) -> dict[str, Any]:
    """Итог текущей успешной попытки; решение даётся только по нему."""
    if job.status is not JobStatus.SUCCEEDED:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    result = cad_service.current_result(job)
    if result.get("attempt") != attempt:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "Эта попытка не текущая")
    return result


def _view_row(result: dict[str, Any], page_index: int, view: int) -> dict[str, Any]:
    for page in result.get("pages", []):
        if page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if isinstance(row, dict) and row.get("view") == view:
                return row
    raise not_found("Вид")


def _folder(page_index: int, view: int) -> str:
    try:
        return cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise not_found("Вид") from error


async def _insert_decision(
    session: AsyncSession,
    *,
    kind: str,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    artifact_sha256: str,
    comment: str | None,
    user_id: uuid.UUID,
) -> CadDecision:
    statement = (
        insert(CadDecision)
        .values(
            workspace_id=job.workspace_id,
            project_id=job.project_id,
            revision_id=uuid.UUID(str(job.payload["revision_id"])),
            kind=kind,
            job_id=job.id,
            attempt=attempt,
            page_index=page_index,
            view=view,
            artifact_sha256=artifact_sha256,
            decided_by=user_id,
            comment=comment,
        )
        .on_conflict_do_nothing(constraint=UNIQUE_DECISION)
        .returning(CadDecision)
        .execution_options(populate_existing=True)
    )
    decision = (await session.scalars(statement)).first()
    if decision is None:
        raise DomainError(ErrorCode.CAD_ALREADY_DECIDED)
    return decision


async def approve_view(
    session: AsyncSession,
    *,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    comment: str | None,
    user_id: uuid.UUID,
) -> CadDecision:
    """Одобрение вида: родитель успешен, у вида есть DXF, открытых замечаний нет."""
    if job.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    # Строка под блокировкой: одобрение и замечание не расходятся при одновременных запросах.
    await session.refresh(job, with_for_update=True)
    result = _succeeded_current(job, attempt)
    _view_row(result, page_index, view)
    dxf = cad_service.find_artifact(job, f"{_folder(page_index, view)}/plan_candidates.dxf")
    if dxf is None:
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "У вида нет DXF")
    existing = await find_decision(
        session,
        kind=DECISION_VIEW_APPROVAL,
        job_id=job.id,
        attempt=attempt,
        page_index=page_index,
        view=view,
    )
    if existing is not None:
        raise DomainError(ErrorCode.CAD_ALREADY_DECIDED)
    if await open_remark_count(session, job=job, attempt=attempt, page_index=page_index, view=view):
        raise DomainError(ErrorCode.CAD_OPEN_REMARKS)
    return await _insert_decision(
        session,
        kind=DECISION_VIEW_APPROVAL,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        artifact_sha256=str(dxf["sha256"]),
        comment=comment,
        user_id=user_id,
    )


async def schedule_routes(
    session: AsyncSession,
    *,
    project: Project,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    floor_elevation_mm: int,
    floor_height_mm: int,
    settings: Settings,
) -> Job:
    """Задание `cad_mep_route` по одобренному виду. Без одобрения - 409 CAD_VIEW_NOT_APPROVED."""
    if job.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    result = _succeeded_current(job, attempt)
    _view_row(result, page_index, view)
    folder = _folder(page_index, view)
    approval = await find_decision(
        session,
        kind=DECISION_VIEW_APPROVAL,
        job_id=job.id,
        attempt=attempt,
        page_index=page_index,
        view=view,
    )
    if approval is None:
        raise DomainError(ErrorCode.CAD_VIEW_NOT_APPROVED)
    dxf = cad_service.find_artifact(job, f"{folder}/plan_candidates.dxf")
    for name in ("scale.json", "preview.json"):
        if cad_service.find_artifact(job, f"{folder}/{name}") is None:
            raise DomainError(ErrorCode.CAD_INPUT_INVALID, f"У вида нет {name}")
    if dxf is None or dxf.get("sha256") != approval.artifact_sha256:
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "DXF вида не совпадает с одобренным")
    params = load_params(settings)
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_MEP_ROUTE,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=route_idempotency_key(
            approval.id,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            floor_elevation_mm=floor_elevation_mm,
            floor_height_mm=floor_height_mm,
        ),
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
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
        },
    )


async def accept_routes(
    session: AsyncSession,
    *,
    job: Job,
    attempt: int,
    comment: str | None,
    user_id: uuid.UUID,
) -> CadDecision:
    """Принятие трасс этажа: route-задание успешно и открытых замечаний нет."""
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        raise not_found("Задание")
    page_index = payload_int(job, "page_index")
    view = payload_int(job, "view")
    if page_index is None or view is None:
        raise not_found("Вид")
    await session.refresh(job, with_for_update=True)
    _succeeded_current(job, attempt)
    dxf = cad_service.find_artifact(job, f"{_folder(page_index, view)}/{ROUTES_DXF}")
    if dxf is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "У задания нет DXF трасс")
    existing = await find_decision(
        session,
        kind=DECISION_MEP_ACCEPTANCE,
        job_id=job.id,
        attempt=attempt,
        page_index=page_index,
        view=view,
    )
    if existing is not None:
        raise DomainError(ErrorCode.CAD_ALREADY_DECIDED)
    if await open_remark_count(session, job=job, attempt=attempt, page_index=page_index, view=view):
        raise DomainError(ErrorCode.CAD_OPEN_REMARKS)
    return await _insert_decision(
        session,
        kind=DECISION_MEP_ACCEPTANCE,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        artifact_sha256=str(dxf["sha256"]),
        comment=comment,
        user_id=user_id,
    )
