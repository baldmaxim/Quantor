"""Перенос решений человека на новый прогон движка при полном совпадении геометрии вида.

При каждом выпуске движка лист переводится заново (новое `cad_pdf_convert`), а решения человека
привязаны к конкретному прогону. Здесь они переносятся, но только если геометрия вида не
изменилась: `dxf_geometry_sha256` вида (секции TABLES, BLOCKS, ENTITIES DXF) есть в итогах обоих
прогонов и равен. Иначе, и для старых итогов без отпечатка, всё как раньше: человек решает заново.

Перенесённое решение - обычная запись `cad_decisions` на ключ нового прогона: тот же вид решения,
`artifact_sha256` нового DXF, автор - тот же человек, что дал исходное решение (не система), а
`carried_from_id` и `comment` называют исходное решение, задание и отпечаток. Одобрение
переносится, только если равны и отпечаток геометрии, и sha256 `scale.json` вида (масштаб и
привязка). Перенос не выдумывает решений: нет действующего исходного решения (его не было или
отозвано), есть открытые замечания на новом виде или на виде-источнике, отпечатки или масштаб
разные - не переносится. Источник - самое новое решение
`view_approval` этого вида на прежних прогонах; если оно отозвано, более старое не берётся.

Принятие трасс переносится вдвое осторожнее: по перенесённому одобрению, у исходного вида которого
были принятые трассы, автоматически ставится `cad_mep_route` с теми же параметрами; принятие
переносится, только когда DXF новых трасс совпал с принятым (отпечаток геометрии, а если его нет у
старого итога, - sha256 файла целиком). Иначе трассы ждут человека.

Всё идемпотентно: любая запись на новом ключе (и отозванная) - перенос пропускается.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.models import CadDecision, Job, Project
from app.models.cad_decision import (
    DECISION_MEP_ACCEPTANCE,
    DECISION_VIEW_APPROVAL,
    MAX_DECISION_COMMENT,
)
from app.services import cad as cad_service
from app.services import cad_mep
from app.services import feature_flags as flags_service

log = get_logger(__name__)

FINGERPRINT_KEY: Final = "dxf_geometry_sha256"
SCALE_KEY: Final = "scale_sha256"
# Трассы по перенесённому одобрению ставятся только там, где открыты оба флага пространства.
ROUTE_FLAGS: Final = ("cad.export", "cad.mep_engine")


def _view_row(result: dict[str, Any], page_index: int, view: int) -> dict[str, Any] | None:
    for page in result.get("pages", []):
        if not isinstance(page, dict) or page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if isinstance(row, dict) and row.get("view") == view:
                return row
    return None


def _view_value(result: dict[str, Any], page_index: int, view: int, key: str) -> str | None:
    row = _view_row(result, page_index, view)
    value = None if row is None else row.get(key)
    return value if isinstance(value, str) and value else None


def _fingerprint(result: dict[str, Any], page_index: int, view: int) -> str | None:
    return _view_value(result, page_index, view, FINGERPRINT_KEY)


def _comment(source: CadDecision, what: str, fingerprint: str | None) -> str:
    """Происхождение перенесённого решения; комментарий исходного решения дописывается."""
    text = (
        f"Перенесено с прогона {source.job_id} (попытка {source.attempt}, решение {source.id}): "
        f"{what}" + (f", отпечаток геометрии {fingerprint[:16]}" if fingerprint else "") + "."
    )
    if source.comment and not source.comment.startswith("Перенесено с прогона"):
        text += f" Комментарий исходного решения: {source.comment}"
    return text[:MAX_DECISION_COMMENT]


async def _has_any_decision(
    session: AsyncSession, kind: str, job: Job, attempt: int, page_index: int, view: int
) -> bool:
    """Любая запись на ключе, в том числе отозванная: человек уже решал, перенос не вмешивается."""
    found = await session.scalar(
        select(CadDecision.id)
        .where(
            CadDecision.kind == kind,
            CadDecision.job_id == job.id,
            CadDecision.attempt == attempt,
            CadDecision.page_index == page_index,
            CadDecision.view == view,
        )
        .limit(1)
    )
    return found is not None


async def _latest_approval(
    session: AsyncSession, job: Job, revision_id: uuid.UUID, page_index: int, view: int
) -> CadDecision | None:
    """Самое новое одобрение вида на прежних прогонах (отозванное - тоже: старее не берётся)."""
    found: CadDecision | None = await session.scalar(
        select(CadDecision)
        .join(Job, Job.id == CadDecision.job_id)
        .where(
            CadDecision.kind == DECISION_VIEW_APPROVAL,
            CadDecision.revision_id == revision_id,
            CadDecision.workspace_id == job.workspace_id,
            CadDecision.page_index == page_index,
            CadDecision.view == view,
            CadDecision.job_id != job.id,
            Job.job_type == JobType.CAD_PDF_CONVERT,
            Job.created_at <= job.created_at,
        )
        .order_by(CadDecision.decided_at.desc(), CadDecision.id)
        .limit(1)
    )
    return found


async def carry_after_convert(session: AsyncSession, job: Job, settings: Settings) -> None:
    """Переносит одобрения видов нового прогона и ставит трассы там, где у исходного они приняты.

    Вызывается в транзакции записи успеха конвертации. Любой сбой переноса конвертацию не рушит:
    каждый вид переносится в своей вложенной транзакции (savepoint), её откат не оставляет
    полузаписанных решений, а человек просто решит заново.
    """
    try:
        await _carry_after_convert(session, job, settings)
    except Exception:
        log.exception("cad_decision_carry_crashed", job_id=str(job.id))


async def _carry_after_convert(session: AsyncSession, job: Job, settings: Settings) -> None:
    if job.job_type is not JobType.CAD_PDF_CONVERT or job.status is not JobStatus.SUCCEEDED:
        return
    try:
        revision_id = uuid.UUID(str(job.payload.get("revision_id")))
    except ValueError:
        return
    result = cad_service.current_result(job)
    attempt = result.get("attempt")
    if type(attempt) is not int:
        return
    for page in result.get("pages", []):
        for row in page.get("views", []):
            page_index, view = page.get("index"), row.get("view")
            if type(page_index) is not int or type(view) is not int:
                continue
            try:
                async with session.begin_nested():
                    await _carry_view(
                        session, job, settings, revision_id, attempt, page_index, view
                    )
            except Exception:
                log.exception(
                    "cad_decision_carry_failed",
                    job_id=str(job.id),
                    page_index=page_index,
                    view=view,
                )


async def _carry_view(
    session: AsyncSession,
    job: Job,
    settings: Settings,
    revision_id: uuid.UUID,
    attempt: int,
    page_index: int,
    view: int,
) -> None:
    result = cad_service.current_result(job)
    fingerprint = _fingerprint(result, page_index, view)
    folder = cad_service.view_folder(page_index, view)
    dxf = cad_service.find_artifact(job, f"{folder}/plan_candidates.dxf")
    if fingerprint is None or dxf is None:
        return
    if await _has_any_decision(session, DECISION_VIEW_APPROVAL, job, attempt, page_index, view):
        return
    source = await _latest_approval(session, job, revision_id, page_index, view)
    if source is None or source.revoked_at is not None:
        return
    old_job = await session.get(Job, source.job_id)
    if old_job is None or old_job.status is not JobStatus.SUCCEEDED:
        return
    old_fingerprint = _fingerprint(
        cad_service.result_for_attempt(old_job, source.attempt), page_index, view
    )
    if old_fingerprint is None or old_fingerprint != fingerprint:
        return
    # Масштаб и привязка вида - часть условия: при равной геометрии, но другом scale.json
    # одобрение относилось к другому масштабу.
    old_result = cad_service.result_for_attempt(old_job, source.attempt)
    scale = _view_value(result, page_index, view, SCALE_KEY)
    if scale is None or scale != _view_value(old_result, page_index, view, SCALE_KEY):
        return
    if await cad_mep.open_remark_count(
        session, job=job, attempt=attempt, page_index=page_index, view=view
    ) or await cad_mep.open_remark_count(
        session, job=old_job, attempt=source.attempt, page_index=page_index, view=view
    ):
        return
    approval = await cad_mep._insert_decision(
        session,
        kind=DECISION_VIEW_APPROVAL,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        artifact_sha256=str(dxf["sha256"]),
        comment=_comment(source, "геометрия вида не изменилась", fingerprint),
        user_id=source.decided_by,
        carried_from_id=source.id,
    )
    log.info("cad_view_approval_carried", job_id=str(job.id), decision_id=str(approval.id))
    await _schedule_accepted_routes(session, job, settings, source, attempt, page_index, view)


async def _accepted_routes(
    session: AsyncSession, source_approval_id: uuid.UUID, page_index: int, view: int
) -> tuple[CadDecision, Job] | None:
    """Действующее принятие трасс по одобрению (самое новое) и его route-задание."""
    row = (
        await session.execute(
            select(CadDecision, Job)
            .join(Job, Job.id == CadDecision.job_id)
            .where(
                CadDecision.kind == DECISION_MEP_ACCEPTANCE,
                CadDecision.revoked_at.is_(None),
                CadDecision.page_index == page_index,
                CadDecision.view == view,
                Job.job_type == JobType.CAD_MEP_ROUTE,
                Job.status == JobStatus.SUCCEEDED,
                Job.payload["approval_id"].astext == str(source_approval_id),
            )
            .order_by(CadDecision.decided_at.desc(), CadDecision.id)
            .limit(1)
        )
    ).first()
    return None if row is None else (row[0], row[1])


def _int_or_none(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if type(value) is int else None


def _origin_or_none(payload: dict[str, Any], key: str) -> dict[str, str | int | None] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) and value else None


async def _schedule_accepted_routes(
    session: AsyncSession,
    job: Job,
    settings: Settings,
    source_approval: CadDecision,
    attempt: int,
    page_index: int,
    view: int,
) -> None:
    """Трассы по перенесённому одобрению - теми же параметрами, что у принятого задания трасс."""
    accepted = await _accepted_routes(session, source_approval.id, page_index, view)
    if accepted is None:
        return
    acceptance, old_route = accepted
    if cad_mep.runner_path(settings) is None:
        return
    # Эндпоинт трасс закрыт `cad.mep_engine` (require_mep_engine): перенос его не обходит.
    evaluated = await flags_service.evaluate_all(
        session, settings, flags_service.EvaluationContext(workspace_id=job.workspace_id)
    )
    if not all(evaluated[key].value for key in ROUTE_FLAGS):
        log.info("cad_carry_routes_flag_off", job_id=str(job.id))
        return
    project = await session.get(Project, job.project_id)
    if project is None:
        return
    payload = old_route.payload
    sections = payload.get("section_level_ids")
    warnings = payload.get("levels_warnings")
    await cad_mep.schedule_routes(
        session,
        project=project,
        job=job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        floor_elevation_mm=_int_or_none(payload, "floor_elevation_mm"),
        floor_height_mm=_int_or_none(payload, "floor_height_mm"),
        # Трассы ставит система по принятию человека: запрос приписан тому, кто принял исходные.
        user_id=acceptance.decided_by,
        settings=settings,
        clear_height_mm=_int_or_none(payload, "clear_height_mm"),
        slab_thickness_mm=_int_or_none(payload, "slab_thickness_mm"),
        levels_source=str(payload.get("levels_source") or "none"),
        section_level_ids=[str(item) for item in sections] if isinstance(sections, list) else None,
        levels_warnings=[str(item) for item in warnings] if isinstance(warnings, list) else None,
        levels_doc_answer=_origin_or_none(payload, "levels_doc_answer"),
        ceiling_height_mm=_int_or_none(payload, "ceiling_height_mm"),
        ceiling_doc_answer=_origin_or_none(payload, "ceiling_doc_answer"),
    )


async def carry_routes_acceptance(session: AsyncSession, route_job: Job) -> None:
    """Принятие трасс переносится, если DXF новых трасс совпал с принятым.

    Вызывается после успеха `cad_mep_route`. Не по перенесённому одобрению, отозванное одобрение,
    открытые замечания, иная геометрия трасс - ничего не делает (трассы ждут человека).
    """
    if (
        route_job.job_type is not JobType.CAD_MEP_ROUTE
        or route_job.status is not JobStatus.SUCCEEDED
    ):
        return
    try:
        async with session.begin_nested():
            await _carry_routes(session, route_job)
    except Exception:
        log.exception("cad_acceptance_carry_failed", job_id=str(route_job.id))


async def _carry_routes(session: AsyncSession, route_job: Job) -> None:
    approval_id = cad_mep.approval_id_of(route_job)
    page_index = cad_mep.payload_int(route_job, "page_index")
    view = cad_mep.payload_int(route_job, "view")
    if approval_id is None or page_index is None or view is None:
        return
    approval = await session.get(CadDecision, approval_id)
    if approval is None or approval.carried_from_id is None or approval.revoked_at is not None:
        return
    result = cad_service.current_result(route_job)
    attempt = result.get("attempt")
    folder = cad_service.view_folder(page_index, view)
    dxf = cad_service.find_artifact(route_job, f"{folder}/{cad_mep.ROUTES_DXF}")
    if type(attempt) is not int or dxf is None:
        return
    if await _has_any_decision(
        session, DECISION_MEP_ACCEPTANCE, route_job, attempt, page_index, view
    ):
        return
    accepted = await _accepted_routes(session, approval.carried_from_id, page_index, view)
    if accepted is None:
        return
    acceptance, old_route = accepted
    new_fingerprint = _fingerprint(result, page_index, view)
    old_fingerprint = _fingerprint(
        cad_service.result_for_attempt(old_route, acceptance.attempt), page_index, view
    )
    if new_fingerprint is not None and old_fingerprint is not None:
        same = new_fingerprint == old_fingerprint
    else:
        # У старого итога отпечатка нет: DXF трасс пишется с фиксированными метаданными, поэтому
        # совпадение sha256 файла целиком - то же полное совпадение.
        same = str(dxf["sha256"]) == acceptance.artifact_sha256
    if not same:
        return
    if await cad_mep.open_remark_count(
        session, job=route_job, attempt=attempt, page_index=page_index, view=view
    ):
        return
    await cad_mep._insert_decision(
        session,
        kind=DECISION_MEP_ACCEPTANCE,
        job=route_job,
        attempt=attempt,
        page_index=page_index,
        view=view,
        artifact_sha256=str(dxf["sha256"]),
        comment=_comment(acceptance, "трассы не изменились", new_fingerprint),
        user_id=acceptance.decided_by,
        carried_from_id=acceptance.id,
    )
    log.info("cad_mep_acceptance_carried", job_id=str(route_job.id))
