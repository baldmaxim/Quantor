"""Общее состояние конвейера CAD ревизии: лист -> конвертация -> конструкции, зоны, трассы, 3D.

Читает только то, что уже лежит в базе: задания, решения человека, зоны, листы и калибровки. Число
запросов не зависит от числа листов и видов: задания ревизий, решения, зоны и листы берутся по
одному запросу на список ревизий (`build_pipelines`). Задание-родитель листа - последнее
`cad_pdf_convert`, в запрошенных страницах которого есть лист (то же правило, что у сводки листов
в интерфейсе).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import CadSheetFloorTitle
from app.contracts.cad_pipeline import (
    CadPipelineRead,
    CadPipelineSheetRead,
    CadPipelineStageRead,
    CadPipelineViewRead,
)
from app.domain import JobStatus, JobType
from app.models import CadDecision, CadZone, Job, ScaleCalibration, Sheet, SheetPassport
from app.models.cad_decision import DECISION_MEP_ACCEPTANCE, DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_walls
from app.services import documents as documents_service
from app.services.cad_plan_sheets import is_plan_sheet

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


def _floor_title(job: Job) -> CadSheetFloorTitle | None:
    """Заголовок плана из итога успешного `cad_walls`; нет или вне контракта — `None`."""
    raw = cad_service.current_result(job).get("floor_title")
    if not isinstance(raw, dict):
        return None
    try:
        return CadSheetFloorTitle.model_validate(raw)
    except ValidationError:
        return None


def _scale_source(convert: Job | None, page_index: int) -> Literal["calibration", "auto"] | None:
    """Масштаб задания листа по его параметрам: `{"auto": true}` - движок, иначе калибровка."""
    if convert is None:
        return None
    params = convert.payload.get("params")
    scales = params.get("scales") if isinstance(params, dict) else None
    entry = scales.get(str(page_index)) if isinstance(scales, dict) else None
    if not isinstance(entry, dict):
        return None
    return "auto" if entry.get("auto") is True else "calibration"


def _view_rows(convert: Job | None, page_index: int) -> list[dict[str, Any]]:
    if convert is None:
        return []
    for page in cad_service.current_result(convert).get("pages", []):
        if page.get("index") == page_index:
            rows = [r for r in page.get("views", []) if type(r.get("view")) is int]
            return sorted(rows, key=lambda r: int(r["view"]))
    return []


def _pipeline_of(
    revision_id: uuid.UUID,
    *,
    jobs: list[Job],
    calibrated: set[int],
    sheet_rows: list[Any],
    stamp_titles: dict[uuid.UUID, str],
    passports: dict[int, Any],
    zone_counts: dict[int, int],
    approvals: set[_DecisionKey],
    acceptances: set[_DecisionKey],
) -> CadPipelineRead:
    """Сборка вида конвейера одной ревизии из уже прочитанных данных (без запросов)."""
    latest_convert: dict[int, Job] = {}
    latest_child: dict[_ChildKey, Job] = {}
    # Заголовок плана берётся из последнего УСПЕШНОГО cad_walls, даже если позже запущен новый.
    latest_walls_ok: dict[_ChildKey, Job] = {}
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
            if job.job_type is JobType.CAD_WALLS and job.status is JobStatus.SUCCEEDED:
                latest_walls_ok[key] = _newest(latest_walls_ok.get(key), job)

    # Все листы ревизии: листы-планы (штамп или паспорт листа) входят в конвейер и без работы
    # (массовый запуск, ADR-0045). Название: штамп -> паспорт -> подпись страницы.
    labels: dict[int, str | None] = {row.page_index: row.page_label for row in sheet_rows}
    titles_by_page: dict[int, str | None] = {}
    plan_pages: set[int] = set()
    for sheet_row in sheet_rows:
        passport = passports.get(sheet_row.page_index)
        passport_title = (passport.title or "").strip() or None if passport else None
        stamp_title = stamp_titles.get(sheet_row.id)
        titles_by_page[sheet_row.page_index] = stamp_title or passport_title or sheet_row.page_label
        if is_plan_sheet(
            stamp_title=stamp_title,
            passport_kind=passport.sheet_kind if passport else None,
            passport_title=passport_title,
            page_label=sheet_row.page_label,
        ):
            plan_pages.add(sheet_row.page_index)

    by_page: dict[int, dict[JobType, dict[int, Job]]] = defaultdict(lambda: defaultdict(dict))
    for (job_type, parent, page_index, view), job in latest_child.items():
        convert = latest_convert.get(page_index)
        if convert is not None and str(convert.id) == parent:
            by_page[page_index][job_type][view] = job

    titles: dict[int, tuple[int, CadSheetFloorTitle]] = {}
    for (_kind, parent, page_index, view), job in latest_walls_ok.items():
        convert = latest_convert.get(page_index)
        if convert is None or str(convert.id) != parent:
            continue
        title = _floor_title(job)
        known = titles.get(page_index)
        if title is not None and (known is None or view < known[0]):
            titles[page_index] = (view, title)

    sheets: list[CadPipelineSheetRead] = []
    for page_index in sorted(job_pages | calibrated | plan_pages):
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
                title=titles_by_page.get(page_index),
                is_plan=page_index in plan_pages,
                calibrated=page_index in calibrated,
                floor_title=titles[page_index][1] if page_index in titles else None,
                convert=None if convert is None else stage_of(convert),
                scale_source=_scale_source(convert, page_index),
                views=views,
            )
        )
    return CadPipelineRead(revision_id=revision_id, server_time=datetime.now(UTC), sheets=sheets)


async def build_pipelines(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, CadPipelineRead]:
    """Виды конвейера сразу для списка ревизий: тот же код сборки, что и у одной ревизии.

    Читает всё по одному запросу на таблицу для всех ревизий сразу, поэтому число запросов не
    зависит ни от числа ревизий, ни от числа листов. Ревизии проверяет вызывающий.
    """
    wanted = list(dict.fromkeys(revision_ids))
    if not wanted:
        return {}
    jobs_by_revision: dict[str, list[Job]] = defaultdict(list)
    jobs = await session.scalars(
        select(Job).where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type.in_(_PIPELINE_TYPES),
            Job.payload["revision_id"].astext.in_([str(revision_id) for revision_id in wanted]),
        )
    )
    for job in jobs:
        raw = job.payload.get("revision_id")
        if isinstance(raw, str):
            jobs_by_revision[raw].append(job)

    calibrated_by_revision: dict[uuid.UUID, set[int]] = defaultdict(set)
    calibrated_rows = await session.execute(
        select(Sheet.revision_id, Sheet.page_index)
        .join(
            ScaleCalibration,
            (ScaleCalibration.sheet_id == Sheet.id) & ScaleCalibration.is_default.is_(True),
        )
        .where(Sheet.revision_id.in_(wanted))
    )
    for revision_id, page_index in calibrated_rows.tuples():
        calibrated_by_revision[revision_id].add(page_index)

    sheet_rows_by_revision: dict[uuid.UUID, list[Any]] = defaultdict(list)
    sheet_rows = await session.execute(
        select(Sheet.id, Sheet.revision_id, Sheet.page_index, Sheet.page_label).where(
            Sheet.revision_id.in_(wanted)
        )
    )
    for sheet_row in sheet_rows.all():
        sheet_rows_by_revision[sheet_row.revision_id].append(sheet_row)
    stamp_titles = await documents_service.sheet_titles(
        session,
        sheet_ids=[row.id for rows in sheet_rows_by_revision.values() for row in rows],
    )

    passports_by_revision: dict[uuid.UUID, dict[int, Any]] = defaultdict(dict)
    passport_rows = await session.execute(
        select(
            SheetPassport.revision_id,
            SheetPassport.page_index,
            SheetPassport.sheet_kind,
            SheetPassport.title,
        ).where(SheetPassport.revision_id.in_(wanted), SheetPassport.status != "rejected")
    )
    for passport_row in passport_rows.all():
        passports_by_revision[passport_row.revision_id][passport_row.page_index] = passport_row

    zone_counts_by_revision: dict[uuid.UUID, dict[int, int]] = defaultdict(dict)
    zone_rows = await session.execute(
        select(CadZone.revision_id, CadZone.page_index, func.count())
        .where(CadZone.revision_id.in_(wanted))
        .group_by(CadZone.revision_id, CadZone.page_index)
    )
    for revision_id, page_index, count in zone_rows.tuples():
        zone_counts_by_revision[revision_id][page_index] = count

    # Ключ решения содержит идентификатор задания, поэтому наборы общие для всех ревизий.
    approvals: set[_DecisionKey] = set()
    acceptances: set[_DecisionKey] = set()
    decisions = await session.scalars(
        select(CadDecision).where(
            CadDecision.revision_id.in_(wanted),
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

    return {
        revision_id: _pipeline_of(
            revision_id,
            jobs=jobs_by_revision.get(str(revision_id), []),
            calibrated=calibrated_by_revision.get(revision_id, set()),
            sheet_rows=sheet_rows_by_revision.get(revision_id, []),
            stamp_titles=stamp_titles,
            passports=passports_by_revision.get(revision_id, {}),
            zone_counts=zone_counts_by_revision.get(revision_id, {}),
            approvals=approvals,
            acceptances=acceptances,
        )
        for revision_id in wanted
    }


async def build_pipeline(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> CadPipelineRead:
    pipelines = await build_pipelines(
        session, workspace_id=workspace_id, project_id=project_id, revision_ids=[revision_id]
    )
    return pipelines[revision_id]
