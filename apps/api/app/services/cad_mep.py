"""Трассы механики по одобренному виду CAD (ADR-0036 п. 8): решения человека и постановка.

Цепочка: успешное `cad_pdf_convert` -> человек проверяет вид и ставит `view_approval` (нет
открытых замечаний) -> `cad_mep_route` строит трассы (отметку пола и высоту этажа генератор берёт
из документации, человек может переопределить) -> человек проверяет трассы замечаниями и ставит
`mep_acceptance` -> открывается скачивание `mep_routes.dxf`. Решение можно отозвать (запись
остаётся с отметкой отзыва): одобрение - пока по нему нет принятых трасс, принятие - всегда;
по умолчанию ничего не принимается и не одобряется.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadDecision, CadRemark, Job, Project, UserIdentity
from app.models.cad_decision import DECISION_MEP_ACCEPTANCE, DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_risers
from app.services import jobs as jobs_service

_VERSION_LINE: Final = re.compile(
    r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([A-Za-z0-9._-]{1,48})"', re.M
)
DECISION_KEY: Final = ("kind", "job_id", "attempt", "page_index", "view")

ROUTES_DXF: Final = "mep_routes.dxf"
CANDIDATE_JSON: Final = "candidate.json"
ROUTES3D_JSON: Final = "routes3d.json"
ROUTES3D_SCHEMA: Final = "cad_mep_routes3d.v1"
PREVIEW_JSON: Final = "preview.json"
CANDIDATE_SCHEMA: Final = "quantor.cad_mep.candidate.v1"
PREVIEW_SCHEMA: Final = "quantor.cad_engine.preview.v1"

# Отметка пола и высота этажа: из документации или ввод человека; допустимые пределы, мм.
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
    risers_sha256: str = "",
) -> str:
    """То же одобрение, параметры, версия генератора и реестр стояков - то же задание.

    Реестр стояков (ADR-0041) входит в ключ своим sha256 (пустая строка - реестра нет): другой
    реестр - новое задание, а не пересчёт старого.

    Отметка пола и высота этажа в ключ не входят: это параметры попытки, и их правят пересчётом
    (`recompute_routes`) - новой попыткой того же задания, а не новым заданием.
    """
    digest = hashlib.sha256(
        "|".join(
            (
                str(approval_id),
                params_sha256,
                generator_version,
                risers_sha256,
            )
        ).encode()
    ).hexdigest()
    return f"cadmep:{digest[:48]}"


# ------------------------------------------------------------------ чтение состояния


# решение, имя автора, имя отозвавшего
DecisionRow = tuple[CadDecision, str | None, str | None]
ViewKey = tuple[uuid.UUID, int, int, int]


@dataclass(slots=True)
class MepState:
    """Решения и route-задания для набора заданий CAD (один проход по базе).

    `approvals` и `acceptances` - только действующие решения; отозванные - в `revoked`.
    """

    approvals: dict[ViewKey, DecisionRow] = field(default_factory=dict)
    acceptances: dict[ViewKey, DecisionRow] = field(default_factory=dict)
    # история отзывов вида: старые сверху
    revoked: dict[ViewKey, list[DecisionRow]] = field(default_factory=dict)
    # одобрения, на которые ссылаются route-задания (в том числе отозванные)
    approval_by_id: dict[uuid.UUID, CadDecision] = field(default_factory=dict)
    # parent_job_id -> route-задания, новые сверху
    routes: dict[uuid.UUID, list[Job]] = field(default_factory=dict)


def payload_int(job: Job, key: str) -> int | None:
    value = job.payload.get(key)
    return value if type(value) is int else None


def entry_int(entry: object, key: str) -> int | None:
    value = entry.get(key) if isinstance(entry, dict) else None
    return value if type(value) is int else None


def parent_job_id_of(job: Job) -> uuid.UUID | None:
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        return None
    try:
        return uuid.UUID(str(job.payload.get("parent_job_id")))
    except ValueError:
        return None


def approval_id_of(job: Job) -> uuid.UUID | None:
    """Одобрение вида, по которому построено route-задание."""
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        return None
    try:
        return uuid.UUID(str(job.payload.get("approval_id")))
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
    approval_ids = {a for a in (approval_id_of(job) for job in route_jobs) if a is not None}
    revoker = aliased(UserIdentity)
    rows = await session.execute(
        select(
            CadDecision,
            UserIdentity.display_name,
            UserIdentity.email,
            revoker.display_name,
            revoker.email,
        )
        .join(UserIdentity, UserIdentity.id == CadDecision.decided_by)
        .outerjoin(revoker, revoker.id == CadDecision.revoked_by)
        .where(or_(CadDecision.job_id.in_(ids), CadDecision.id.in_(approval_ids)))
        .order_by(CadDecision.decided_at)
    )
    for decision, name, email, revoker_name, revoker_email in rows.all():
        key = (decision.job_id, decision.attempt, decision.page_index, decision.view)
        row: DecisionRow = (decision, name or email, revoker_name or revoker_email)
        if decision.kind == DECISION_VIEW_APPROVAL:
            state.approval_by_id[decision.id] = decision
        if decision.revoked_at is not None:
            state.revoked.setdefault(key, []).append(row)
            continue
        target = state.approvals if decision.kind == DECISION_VIEW_APPROVAL else state.acceptances
        target[key] = row
    return state


async def find_decision(
    session: AsyncSession,
    *,
    kind: str,
    job_id: uuid.UUID,
    attempt: int,
    page_index: int,
    view: int,
    revoked: bool = False,
) -> CadDecision | None:
    """Действующее решение вида; `revoked=True` - отозванное (последнее)."""
    query = select(CadDecision).where(
        CadDecision.kind == kind,
        CadDecision.job_id == job_id,
        CadDecision.attempt == attempt,
        CadDecision.page_index == page_index,
        CadDecision.view == view,
        CadDecision.revoked_at.is_not(None) if revoked else CadDecision.revoked_at.is_(None),
    )
    found: CadDecision | None = await session.scalar(
        query.order_by(CadDecision.decided_at.desc()).limit(1)
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


async def revoker_name(session: AsyncSession, decision: CadDecision) -> str | None:
    if decision.revoked_by is None:
        return None
    row = (
        await session.execute(
            select(UserIdentity.display_name, UserIdentity.email).where(
                UserIdentity.id == decision.revoked_by
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


async def routes_download_allowed(session: AsyncSession, job: Job, attempt: int) -> bool:
    """`mep_routes.dxf` отдаётся только по действующему принятию трасс этой попытки задания."""
    page_index = payload_int(job, "page_index")
    view = payload_int(job, "view")
    if page_index is None or view is None:
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
        .on_conflict_do_nothing(
            index_elements=[getattr(CadDecision, name) for name in DECISION_KEY],
            index_where=CadDecision.revoked_at.is_(None),
        )
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
    floor_elevation_mm: int | None,
    floor_height_mm: int | None,
    user_id: uuid.UUID,
    settings: Settings,
) -> Job:
    """Задание `cad_mep_route` по одобренному виду.

    Для того же одобрения, параметров и версии генератора возвращается уже поставленное
    задание (его правят пересчётом); новое - только при новом одобрении или версии генератора.

    Нет действующего одобрения - 409 CAD_VIEW_NOT_APPROVED (если его отозвали -
    CAD_VIEW_APPROVAL_REVOKED). Отметки не заданы - генератор определит их по документации.
    """
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
        revoked = await find_decision(
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
    # Реестр стояков листа (ADR-0041): непустой уходит в задание вместе с sha256 файла контракта.
    risers = cad_risers.entries_to_json(
        await cad_risers.load_risers(
            session,
            revision_id=uuid.UUID(str(job.payload["revision_id"])),
            page_index=page_index,
            view=view,
        )
    )
    risers_sha256 = cad_risers.registry_sha256(risers) if risers else ""
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_MEP_ROUTE,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=route_idempotency_key(
            approval.id,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            risers_sha256=risers_sha256,
        ),
        payload={
            "revision_id": job.payload["revision_id"],
            "parent_job_id": str(job.id),
            "parent_attempt": attempt,
            "page_index": page_index,
            "view": view,
            "view_dxf_sha256": approval.artifact_sha256,
            "approval_id": str(approval.id),
            # None - определить по документации; число - переопределение человека
            "floor_elevation_mm": floor_elevation_mm,
            "floor_height_mm": floor_height_mm,
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
            "mep_attempts": [_attempt_entry(1, floor_elevation_mm, floor_height_mm, user_id)],
            **({"risers": risers, "risers_sha256": risers_sha256} if risers else {}),
        },
    )


def _attempt_entry(
    attempt: int, floor_elevation_mm: int | None, floor_height_mm: int | None, user_id: uuid.UUID
) -> dict[str, Any]:
    """Параметры попытки: что запросил человек (пусто - определить по документации)."""
    return {
        "attempt": attempt,
        "floor_elevation_mm": floor_elevation_mm,
        "floor_height_mm": floor_height_mm,
        "requested_at": datetime.now(UTC).isoformat(),
        "requested_by": str(user_id),
    }


async def recompute_routes(
    session: AsyncSession,
    *,
    job: Job,
    floor_elevation_mm: int | None,
    floor_height_mm: int | None,
    user_id: uuid.UUID,
    settings: Settings,
) -> Job:
    """Пересчёт трасс: НОВАЯ ПОПЫТКА того же route-задания с другими отметкой и высотой.

    Не новое задание: параметры попытки - в `payload.mep_attempts`, итог прошлой попытки -
    в `payload.cad_results` (артефакты `attempt-{n}` не удаляются, прошлая попытка открывается
    для просмотра). Открытые замечания текущей попытки копируются в новую той же транзакцией.
    Нельзя: пока задание в очереди или работает; если трассы приняты (сначала отозвать
    принятие); без действующего одобрения вида; с теми же параметрами, что у текущей попытки.
    """
    if job.job_type is not JobType.CAD_MEP_ROUTE:
        raise not_found("Задание")
    page_index = payload_int(job, "page_index")
    view = payload_int(job, "view")
    if page_index is None or view is None:
        raise not_found("Вид")
    await session.refresh(job, with_for_update=True)
    if job.status not in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        _retryable, reason = cad_service.retry_state(job)
        raise DomainError(ErrorCode.JOB_NOT_RETRYABLE, reason or "Пересчёт недоступен")
    old_attempt = job.attempt
    if (
        await find_decision(
            session,
            kind=DECISION_MEP_ACCEPTANCE,
            job_id=job.id,
            attempt=old_attempt,
            page_index=page_index,
            view=view,
        )
        is not None
    ):
        raise DomainError(ErrorCode.CAD_ROUTES_ACCEPTED)
    await _require_active_approval(session, job)
    params = load_params(settings)
    if (
        payload_int(job, "floor_elevation_mm") == floor_elevation_mm
        and payload_int(job, "floor_height_mm") == floor_height_mm
        and job.payload.get("generator_version") == params.generator_version
        and job.payload.get("params_sha256") == params.sha256
    ):
        raise DomainError(ErrorCode.CAD_RECOMPUTE_SAME_PARAMS)

    payload = dict(job.payload)
    result = cad_service.result_of(job)
    if result.get("attempt") == old_attempt:
        stash = dict(payload["cad_results"]) if isinstance(payload.get("cad_results"), dict) else {}
        stash[str(old_attempt)] = result
        payload["cad_results"] = stash
    history = payload.get("mep_attempts")
    entries = list(history) if isinstance(history, list) else []
    entries.append(_attempt_entry(old_attempt + 1, floor_elevation_mm, floor_height_mm, user_id))
    payload.update(
        floor_elevation_mm=floor_elevation_mm,
        floor_height_mm=floor_height_mm,
        params_sha256=params.sha256,
        generator_version=params.generator_version,
        engine_version=params.generator_version,
        mep_attempts=entries,
    )
    job.payload = payload
    # Та же механика, что у повтора (jobs.retry): то же задание возвращается в очередь, номер
    # попытки растёт при захвате; разрешён и из успешного, и из любого отказа.
    job.status = JobStatus.QUEUED
    job.max_attempts = old_attempt + 1
    job.worker_id = None
    job.lease_expires_at = None
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    job.progress = None
    job.stage = None
    await _copy_open_remarks(
        session,
        job=job,
        from_attempt=old_attempt,
        to_attempt=old_attempt + 1,
        page_index=page_index,
        view=view,
    )
    await session.flush()
    return job


async def _copy_open_remarks(
    session: AsyncSession,
    *,
    job: Job,
    from_attempt: int,
    to_attempt: int,
    page_index: int,
    view: int,
) -> None:
    """Открытые замечания переходят в новую попытку; привязка DXF - после её завершения."""
    rows = await session.scalars(
        select(CadRemark).where(
            CadRemark.job_id == job.id,
            CadRemark.attempt == from_attempt,
            CadRemark.page_index == page_index,
            CadRemark.view == view,
            CadRemark.status == "open",
        )
    )
    for row in rows:
        session.add(
            CadRemark(
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                revision_id=row.revision_id,
                job_id=row.job_id,
                attempt=to_attempt,
                page_index=row.page_index,
                view=row.view,
                dxf_sha256=None,
                remark_key=row.remark_key,
                type=row.type,
                comment=row.comment,
                reviewer=row.reviewer,
                status="open",
                bbox_x0=row.bbox_x0,
                bbox_y0=row.bbox_y0,
                bbox_x1=row.bbox_x1,
                bbox_y1=row.bbox_y1,
                created_by=row.created_by,
                updated_by=row.updated_by,
            )
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
    await _require_active_approval(session, job)
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


async def _require_active_approval(session: AsyncSession, job: Job) -> None:
    """Принимать можно только трассы по действующему одобрению вида.

    Строка родителя берётся под блокировкой (после строки route-задания): отзыв одобрения
    блокирует ту же строку и проверяет принятия, поэтому принятие и отзыв не расходятся.
    """
    approval_id = approval_id_of(job)
    approval = None if approval_id is None else await session.get(CadDecision, approval_id)
    if approval is None or approval.kind != DECISION_VIEW_APPROVAL:
        raise DomainError(ErrorCode.CAD_VIEW_NOT_APPROVED)
    parent = await session.get(Job, approval.job_id)
    if parent is None:
        raise DomainError(ErrorCode.CAD_VIEW_NOT_APPROVED)
    await session.refresh(parent, with_for_update=True)
    await session.refresh(approval)
    if approval.revoked_at is not None:
        raise DomainError(ErrorCode.CAD_VIEW_APPROVAL_REVOKED)


async def decision_in_scope(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    decision_id: uuid.UUID,
) -> CadDecision:
    """Решение своего пространства, проекта и ревизии; чужое - 404."""
    decision: CadDecision | None = await session.scalar(
        select(CadDecision).where(
            CadDecision.id == decision_id,
            CadDecision.workspace_id == workspace_id,
            CadDecision.project_id == project_id,
            CadDecision.revision_id == revision_id,
        )
    )
    if decision is None:
        raise not_found("Решение")
    return decision


async def revoke_decision(
    session: AsyncSession,
    *,
    decision: CadDecision,
    reason: str | None,
    user_id: uuid.UUID,
) -> CadDecision:
    """Отзыв решения: ставится один раз, запись остаётся.

    Одобрение вида отзывается, пока по нему нет принятых трасс (CAD_ROUTES_ACCEPTED): сначала
    отзывают принятие. Строка задания решения берётся под блокировкой - вместе с принятием
    трасс отзыв не расходится.
    """
    job = await session.get(Job, decision.job_id)
    if job is None:
        raise not_found("Задание")
    await session.refresh(job, with_for_update=True)
    await session.refresh(decision)
    if decision.revoked_at is not None:
        raise DomainError(ErrorCode.CAD_ALREADY_REVOKED)
    if decision.kind == DECISION_VIEW_APPROVAL:
        accepted = await session.scalar(
            select(CadDecision.id)
            .join(Job, Job.id == CadDecision.job_id)
            .where(
                CadDecision.kind == DECISION_MEP_ACCEPTANCE,
                CadDecision.revoked_at.is_(None),
                Job.job_type == JobType.CAD_MEP_ROUTE,
                Job.payload["approval_id"].astext == str(decision.id),
            )
            .limit(1)
        )
        if accepted is not None:
            raise DomainError(ErrorCode.CAD_ROUTES_ACCEPTED)
    decision.revoked_at = func.now()
    decision.revoked_by = user_id
    decision.revoke_reason = reason
    await session.flush()
    await session.refresh(decision)
    return decision


def sheet_level_default(value_mm: int | None, low: int, high: int) -> int | None:
    """Уровень листа как значение по умолчанию для трасс; вне пределов задания - не определён."""
    return value_mm if value_mm is not None and low <= value_mm <= high else None


def merge_floor_params(
    *,
    requested_elevation_mm: int | None,
    requested_height_mm: int | None,
    level_elevation_mm: int | None,
    level_height_mm: int | None,
) -> tuple[int | None, int | None]:
    """Отметка и высота для трасс: явное значение запроса главнее уровней листа (ADR-0039).

    Уровни листа - те же, по которым строится 3D-вид этажа; не определены - `None`, и генератор
    выводит значение сам, как прежде.
    """
    elevation = (
        requested_elevation_mm
        if requested_elevation_mm is not None
        else sheet_level_default(level_elevation_mm, ELEVATION_MIN_MM, ELEVATION_MAX_MM)
    )
    height = (
        requested_height_mm
        if requested_height_mm is not None
        else sheet_level_default(level_height_mm, FLOOR_HEIGHT_MIN_MM, FLOOR_HEIGHT_MAX_MM)
    )
    return elevation, height


def heights_match(
    routes_elevation_mm: int | None,
    routes_height_mm: int | None,
    level_elevation_mm: int | None,
    level_height_mm: int | None,
) -> bool:
    """Обе пары (отметка, высота) известны и равны; иначе - нет."""
    values = (routes_elevation_mm, routes_height_mm, level_elevation_mm, level_height_mm)
    return None not in values and (routes_elevation_mm, routes_height_mm) == (
        level_elevation_mm,
        level_height_mm,
    )


async def latest_succeeded_route_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> Job | None:
    """Новейшее успешное `cad_mep_route` листа (ревизия, страница, вид) - как в web-автовыборе."""
    found: Job | None = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_MEP_ROUTE,
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
