"""Общее состояние конвейера CAD ревизии: лист -> конвертация -> конструкции, зоны, трассы, 3D.

Читает только то, что уже лежит в базе: задания, решения человека, зоны, листы и калибровки. Число
запросов не зависит от числа листов и видов: задания ревизии, решения, зоны и листы берутся по
одному запросу на ревизию. Задание-родитель листа - последнее `cad_pdf_convert`, в запрошенных
страницах которого есть лист (то же правило, что у сводки листов в интерфейсе).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_pipeline import (
    CadPipelineRead,
    CadPipelineSheetRead,
    CadPipelineStageRead,
    CadPipelineViewRead,
)
from app.domain import JobType
from app.models import CadDecision, CadZone, Job, ScaleCalibration, Sheet
from app.models.cad_decision import DECISION_MEP_ACCEPTANCE, DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_walls

_PIPELINE_TYPES: Final = (
    JobType.CAD_PDF_CONVERT,
    JobType.CAD_WALLS,
    JobType.CAD_ZONES,
    JobType.CAD_MEP_ROUTE,
    JobType.CAD_FLOOR3D_DXF,
)
# (тип дочернего задания, родитель, страница, вид)
_ChildKey = tuple[JobType, str, int, int]
# (задание, попытка, страница, вид)
_DecisionKey = tuple[uuid.UUID, int, int, int]


def stage_of(job: Job) -> CadPipelineStageRead:
    return CadPipelineStageRead(
        job_id=job.id,
        job_type=job.job_type.value,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        result_status=cad_service.current_result(job).get("result_status"),
        error_code=job.error_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _convert_pages(job: Job) -> list[int]:
    params = job.payload.get("params")
    pages = params.get("pages") if isinstance(params, dict) else None
    return [p for p in pages if type(p) is int] if isinstance(pages, list) else []


def _newest(current: Job | None, candidate: Job) -> Job:
    return candidate if current is None or candidate.created_at > current.created_at else current


def _child_key(job: Job) -> _ChildKey | None:
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    parent = job.payload.get("parent_job_id")
    if page_index is None or view is None or not isinstance(parent, str):
        return None
    return job.job_type, parent, page_index, view


def _view_rows(convert: Job | None, page_index: int) -> list[dict[str, Any]]:
    if convert is None:
        return []
    for page in cad_service.current_result(convert).get("pages", []):
        if page.get("index") == page_index:
            rows = [r for r in page.get("views", []) if type(r.get("view")) is int]
            return sorted(rows, key=lambda r: int(r["view"]))
    return []


async def build_pipeline(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> CadPipelineRead:
    jobs = list(
        await session.scalars(
            select(Job).where(
                Job.workspace_id == workspace_id,
                Job.project_id == project_id,
                Job.job_type.in_(_PIPELINE_TYPES),
                Job.payload["revision_id"].astext == str(revision_id),
            )
        )
    )
    latest_convert: dict[int, Job] = {}
    latest_child: dict[_ChildKey, Job] = {}
    job_pages: set[int] = set()
    for job in jobs:
        if job.job_type is JobType.CAD_PDF_CONVERT:
            for page in _convert_pages(job):
                job_pages.add(page)
                latest_convert[page] = _newest(latest_convert.get(page), job)
            continue
        key = _child_key(job)
        if key is not None:
            job_pages.add(key[2])
            latest_child[key] = _newest(latest_child.get(key), job)

    calibrated = set(
        await session.scalars(
            select(Sheet.page_index)
            .join(
                ScaleCalibration,
                (ScaleCalibration.sheet_id == Sheet.id) & ScaleCalibration.is_default.is_(True),
            )
            .where(Sheet.revision_id == revision_id)
        )
    )
    labels = dict(
        (
            await session.execute(
                select(Sheet.page_index, Sheet.page_label).where(
                    Sheet.revision_id == revision_id, Sheet.page_index.in_(job_pages | calibrated)
                )
            )
        )
        .tuples()
        .all()
    )
    zone_counts: dict[int, int] = dict(
        (
            await session.execute(
                select(CadZone.page_index, func.count())
                .where(CadZone.revision_id == revision_id)
                .group_by(CadZone.page_index)
            )
        )
        .tuples()
        .all()
    )
    approvals: set[_DecisionKey] = set()
    acceptances: set[_DecisionKey] = set()
    decisions = await session.scalars(
        select(CadDecision).where(
            CadDecision.revision_id == revision_id,
            CadDecision.workspace_id == workspace_id,
            CadDecision.revoked_at.is_(None),
        )
    )
    for decision in decisions:
        decided = (decision.job_id, decision.attempt, decision.page_index, decision.view)
        if decision.kind == DECISION_VIEW_APPROVAL:
            approvals.add(decided)
        elif decision.kind == DECISION_MEP_ACCEPTANCE:
            acceptances.add(decided)

    by_page: dict[int, dict[JobType, dict[int, Job]]] = defaultdict(lambda: defaultdict(dict))
    for (job_type, parent, page_index, view), job in latest_child.items():
        convert = latest_convert.get(page_index)
        if convert is not None and str(convert.id) == parent:
            by_page[page_index][job_type][view] = job

    sheets: list[CadPipelineSheetRead] = []
    for page_index in sorted(job_pages | calibrated):
        convert = latest_convert.get(page_index)
        convert_attempt = None if convert is None else cad_service.result_of(convert).get("attempt")
        children = by_page.get(page_index, {})
        views: list[CadPipelineViewRead] = []
        for row in _view_rows(convert, page_index):
            view = int(row["view"])
            routes = children.get(JobType.CAD_MEP_ROUTE, {}).get(view)
            route_attempt = (
                None if routes is None else cad_service.current_result(routes).get("attempt")
            )
            walls, zones, floor3d = (
                children.get(kind, {}).get(view)
                for kind in (JobType.CAD_WALLS, JobType.CAD_ZONES, JobType.CAD_FLOOR3D_DXF)
            )
            views.append(
                CadPipelineViewRead(
                    page=page_index,
                    view=view,
                    has_dxf=convert is not None
                    and cad_walls.view_has_dxf(convert, page_index, view) is not None,
                    walls=None if walls is None else stage_of(walls),
                    zones=None if zones is None else stage_of(zones),
                    zones_count=zone_counts.get(page_index, 0),
                    approved=convert is not None
                    and type(convert_attempt) is int
                    and (convert.id, convert_attempt, page_index, view) in approvals,
                    routes=None if routes is None else stage_of(routes),
                    routes_accepted=routes is not None
                    and type(route_attempt) is int
                    and (routes.id, route_attempt, page_index, view) in acceptances,
                    floor3d=None if floor3d is None else stage_of(floor3d),
                )
            )
        sheets.append(
            CadPipelineSheetRead(
                page_index=page_index,
                page_label=labels.get(page_index),
                calibrated=page_index in calibrated,
                convert=None if convert is None else stage_of(convert),
                views=views,
            )
        )
    return CadPipelineRead(revision_id=revision_id, server_time=datetime.now(UTC), sheets=sheets)
