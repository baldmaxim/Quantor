"""Сводка распознавания CAD по проекту: листы последних открываемых ревизий по состоянию.

Источник истины - общий вид конвейера (`cad_pipeline.build_pipelines`): те же листы и те же
последние задания этапов, что видит страница ревизии, одним набором запросов на весь проект.
Состояние листа считается по этапам конвертации, конструкций, зон и трасс; необязательный
3D DXF в итог не входит (как в `sheetSummary` веб-клиента). Этап отказал, если его последнее
задание не `succeeded` (в том числе отменено) или итог попытки - `failed`.
"""

from __future__ import annotations

import uuid
from typing import Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_pipeline import CadPipelineSheetRead, CadPipelineStageRead
from app.contracts.cad_summary import CadProjectSummaryRead
from app.domain import DocumentKind, GeometryStatus, JobStatus
from app.models import Document, DocumentRevision, Sheet
from app.services import cad_pipeline

SheetState = Literal["done", "running", "failed", "idle"]

_NOT_READY: Final = (GeometryStatus.PENDING, GeometryStatus.EXTRACTING, GeometryStatus.FAILED)
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


def _stages(sheet: CadPipelineSheetRead) -> list[CadPipelineStageRead]:
    """Последние задания основных этапов листа; необязательный 3D DXF не входит."""
    stages = [sheet.convert] if sheet.convert is not None else []
    for view in sheet.views:
        stages.extend(stage for stage in (view.walls, view.zones, view.routes) if stage is not None)
    return stages


def _is_failed(stage: CadPipelineStageRead) -> bool:
    return stage.status is not JobStatus.SUCCEEDED or stage.result_status == "failed"


def sheet_state(sheet: CadPipelineSheetRead) -> SheetState:
    stages = _stages(sheet)
    if any(stage.status in _ACTIVE for stage in stages):
        return "running"
    if any(_is_failed(stage) for stage in stages):
        return "failed"
    return "done" if stages else "idle"


async def latest_openable_revisions(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[uuid.UUID]:
    """Последняя открываемая ревизия каждого PDF-документа проекта (как в веб-клиенте).

    Открываемая: геометрия не готовится и не отказала, листы есть.
    """
    has_sheets = (
        select(func.count(Sheet.id))
        .where(Sheet.revision_id == DocumentRevision.id)
        .correlate(DocumentRevision)
        .scalar_subquery()
        > 0
    )
    rows = await session.execute(
        select(DocumentRevision.document_id, DocumentRevision.id)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(
            Document.project_id == project_id,
            Document.document_kind == DocumentKind.PDF,
            DocumentRevision.geometry_status.not_in(_NOT_READY),
            has_sheets,
        )
        .order_by(DocumentRevision.created_at.asc(), DocumentRevision.id.asc())
    )
    # Порядок возрастающий: последняя запись документа перезаписывает предыдущие.
    latest = dict(rows.tuples().all())
    return list(latest.values())


async def build_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CadProjectSummaryRead:
    revision_ids = await latest_openable_revisions(session, project_id=project_id)
    pipelines = await cad_pipeline.build_pipelines(
        session, workspace_id=workspace_id, project_id=project_id, revision_ids=revision_ids
    )
    counts: dict[SheetState, int] = {"done": 0, "running": 0, "failed": 0, "idle": 0}
    for pipeline in pipelines.values():
        for sheet in pipeline.sheets:
            counts[sheet_state(sheet)] += 1
    return CadProjectSummaryRead(
        sheets_total=sum(counts.values()),
        sheets_done=counts["done"],
        sheets_running=counts["running"],
        sheets_failed=counts["failed"],
        sheets_idle=counts["idle"],
        documents_total=len(revision_ids),
    )
