"""Листы CAD проекта, которым нужен масштаб: список для ручной калибровки.

Читает только базу, без артефактов хранилища. Для каждой пары (ревизия, страница) берётся
последнее задание `cad_pdf_convert` (любой статус, кроме отменённого): идущее или стоящее в
очереди лист из списка исключает. Число запросов постоянно и от числа листов не зависит.
Задания читаются лёгкими копиями без истории попыток в payload.

Причины:
- последнее преобразование отказало с `CAD_AUTO_SCALE_UNCONFIRMED` (только страницы, названные
  в `unconfirmed_pages` итога; у старых заданий без поля - все страницы задания);
- преобразование успешно, но у вида в итоге нет принятого масштаба (`scale_status` не из
  `SCALE_PASSED_STATUSES`; масштаб оператора `needs_review` - норма, пока он не разошёлся с
  подбором движка сверх `OPERATOR_SCALE_LIMIT`). Итоги старых заданий без `scale_status`
  проверяются по ошибке последних `cad_zones` / `cad_eom_route` вида: `CAD_INPUT_INVALID`
  с подстрокой `scale` в сообщении;
- в обоих случаях, если действующая калибровка листа создана позже последнего преобразования,
  причина - `rerun_needed`: человек откалибровал, осталось перезапустить.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Final

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import Label

from app.contracts.cad_scale_needed import (
    CadScaleNeededItem,
    CadScaleNeededRead,
    CadScaleNeededReason,
)
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import Document, DocumentRevision, Job, ScaleCalibration, Sheet
from app.services import cad as cad_service
from app.services import cad_pipeline, cad_summary
from app.services.cad_views import (
    OPERATOR_SOURCE,
    SCALE_PASSED_STATUSES,
    operator_scale_mismatch,
    scale_from,
)

_TYPES: Final = (JobType.CAD_PDF_CONVERT, JobType.CAD_ZONES, JobType.CAD_EOM_ROUTE)
# Крупные ключи payload, которым здесь нечего делать: события попыток и итоги прошлых попыток.
_HEAVY_KEYS: Final = ("cad_attempts", "cad_results")


def _operator_scale_diverged(row: dict[str, object]) -> bool:
    """Масштаб оператора `needs_review` разошёлся с подбором движка сверх допуска.

    Правило то же, что у кадра вида: `operator_scale_mismatch`. В итоге задания хранится
    `scale_deviation` = |оператор / размеры - 1|, поэтому масштаб собирается из пары (1 + доля, 1).
    Доли нет (размерных цепочек нет) - расхождения нет.
    """
    deviation = row.get("scale_deviation")
    if isinstance(deviation, bool) or not isinstance(deviation, int | float) or deviation < 0:
        return False
    scale = scale_from(
        {
            "status": "needs_review",
            "source": OPERATOR_SOURCE,
            "operator_mm_per_pt": 1.0 + float(deviation),
            "mm_per_pdf_point_fitted": 1.0,
        }
    )
    return operator_scale_mismatch(scale) is not None


def _view_scale_missing(row: dict[str, object]) -> bool | None:
    """У вида нет принятого масштаба; `None` - статус в итоге не записан (старое задание)."""
    status = row.get("scale_status")
    if not isinstance(status, str):
        return None
    if status in SCALE_PASSED_STATUSES:
        return False
    if status == "needs_review" and row.get("scale_source") == OPERATOR_SOURCE:
        return _operator_scale_diverged(row)
    return True


def _scale_error(job: Job) -> bool:
    return (
        job.status is JobStatus.FAILED
        and job.error_code == ErrorCode.CAD_INPUT_INVALID.value
        and "scale" in (job.error_message or "").lower()
    )


def _missing_view(
    convert: Job, page_index: int, children: dict[tuple[JobType, int], Job]
) -> str | None:
    """Первый вид страницы без масштаба; нет такого - `None`."""
    for row in cad_pipeline._view_rows(convert, page_index):
        view = int(row["view"])
        missing = _view_scale_missing(row)
        if missing is None:
            missing = any(
                (job := children.get((kind, view))) is not None and _scale_error(job)
                for kind in (JobType.CAD_ZONES, JobType.CAD_EOM_ROUTE)
            )
        if missing:
            return str(view)
    return None


def _unconfirmed(job: Job, page: int) -> bool:
    """Страница названа неподтверждённой в итоге отказа; нет списка (старое задание) - да."""
    listed = cad_service.current_result(job).get("unconfirmed_pages")
    if not isinstance(listed, list):
        return True
    return page in listed


def _light_payload() -> Label[dict[str, Any]]:
    """`payload` без событий и истории попыток: JSONB `payload - 'ключ' - ...`."""
    first, second = _HEAVY_KEYS
    expr = Job.payload.op("-", return_type=pg.JSONB)(cast(first, Text)).op(
        "-", return_type=pg.JSONB
    )(cast(second, Text))
    return expr.label("payload")


async def _load_jobs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_ids: list[uuid.UUID],
) -> list[Job]:
    """Лёгкие копии заданий (вне сессии): только нужные колонки, без отменённых."""
    rows = await session.execute(
        select(
            Job.id,
            Job.job_type,
            Job.status,
            Job.attempt,
            Job.created_at,
            Job.error_code,
            Job.error_message,
            _light_payload(),
        ).where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type.in_(_TYPES),
            Job.status != JobStatus.CANCELLED,
            Job.payload["revision_id"].astext.in_([str(rid) for rid in revision_ids]),
        )
    )
    return [
        Job(
            id=job_id,
            job_type=job_type,
            status=status,
            attempt=attempt,
            created_at=created_at,
            error_code=error_code,
            error_message=error_message,
            payload=payload,
        )
        for job_id, job_type, status, attempt, created_at, error_code, error_message, payload in (
            rows.tuples()
        )
    ]


async def build_scale_needed(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CadScaleNeededRead:
    revision_ids = await cad_summary.latest_openable_revisions(session, project_id=project_id)
    if not revision_ids:
        return CadScaleNeededRead(total=0, items=[])
    jobs = await _load_jobs(
        session, workspace_id=workspace_id, project_id=project_id, revision_ids=revision_ids
    )
    latest: dict[tuple[str, int], Job] = {}
    # (родитель, страница) -> {(тип, вид): последнее дочернее задание}
    children: dict[tuple[str, int], dict[tuple[JobType, int], Job]] = defaultdict(dict)
    for job in jobs:
        revision = job.payload.get("revision_id")
        if not isinstance(revision, str):
            continue
        if job.job_type is JobType.CAD_PDF_CONVERT:
            for page in cad_pipeline._convert_pages(job):
                key = (revision, page)
                latest[key] = cad_pipeline._newest(latest.get(key), job)
            continue
        child = cad_pipeline._child_key(job)
        if child is not None:
            slot = children[(child[1], child[2])]
            slot[(child[0], child[3])] = cad_pipeline._newest(slot.get((child[0], child[3])), job)

    rows = await session.execute(
        select(DocumentRevision.id, Document.id, Document.display_name)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(DocumentRevision.id.in_(revision_ids))
    )
    documents = {revision: (document, title) for revision, document, title in rows.tuples()}
    label_rows = await session.execute(
        select(Sheet.revision_id, Sheet.page_index, Sheet.page_label).where(
            Sheet.revision_id.in_(revision_ids)
        )
    )
    labels: dict[tuple[str, int], str | None] = {}
    pages_of: dict[str, list[int]] = defaultdict(list)
    for sheet_revision, sheet_page, label in label_rows.tuples():
        labels[(str(sheet_revision), sheet_page)] = label
        pages_of[str(sheet_revision)].append(sheet_page)
    # Позиция в рабочей области - как `sheetPosition` в web: порядок страниц ревизии, с 1.
    positions = {
        (revision, page): at
        for revision, pages in pages_of.items()
        for at, page in enumerate(sorted(pages), start=1)
    }
    # Действующая калибровка листа (тот же признак, что у `calibrated` в cad_pipeline).
    calibration_rows = await session.execute(
        select(Sheet.revision_id, Sheet.page_index, func.max(ScaleCalibration.created_at))
        .join(
            ScaleCalibration,
            (ScaleCalibration.sheet_id == Sheet.id) & ScaleCalibration.is_default.is_(True),
        )
        .where(Sheet.revision_id.in_(revision_ids))
        .group_by(Sheet.revision_id, Sheet.page_index)
    )
    calibrated_at = {
        (str(revision), page): moment for revision, page, moment in calibration_rows.tuples()
    }

    found: list[tuple[str, int, CadScaleNeededItem]] = []
    for (revision, page), convert in latest.items():
        revision_id = uuid.UUID(revision)
        document = documents.get(revision_id)
        if document is None:
            continue
        reason: CadScaleNeededReason | None = None
        view: str | None = None
        if convert.status is JobStatus.FAILED:
            if convert.error_code == ErrorCode.CAD_AUTO_SCALE_UNCONFIRMED.value and _unconfirmed(
                convert, page
            ):
                reason = "auto_scale_unconfirmed"
        elif convert.status is JobStatus.SUCCEEDED:
            view = _missing_view(convert, page, children.get((str(convert.id), page), {}))
            reason = "scale_missing" if view is not None else None
        if reason is None:
            continue
        calibrated = calibrated_at.get((revision, page))
        if calibrated is not None and calibrated > convert.created_at:
            reason = "rerun_needed"
        found.append(
            (
                document[1],
                page,
                CadScaleNeededItem(
                    document_id=document[0],
                    document_title=document[1],
                    revision_id=revision_id,
                    page_index=page,
                    page_label=labels.get((revision, page)),
                    sheet_position=positions.get((revision, page)),
                    reason=reason,
                    convert_job_id=convert.id,
                    view=view,
                ),
            )
        )
    found.sort(key=lambda row: (row[0], str(row[2].revision_id), row[1]))
    items = [row[2] for row in found]
    return CadScaleNeededRead(total=len(items), items=items)
