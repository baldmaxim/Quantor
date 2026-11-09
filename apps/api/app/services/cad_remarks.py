"""Замечания проверяющего к видам результата CAD: хранение, правка, слияние при импорте.

Замечание — след человека, а не измерение и не инженерная приёмка. Привязка — задание, попытка,
страница и вид; доступ к заданию проверяет вызывающий (`cad_service.get_cad_job`), этот модуль
доверяет переданному заданию и не читает чужих.

Слияние при импорте то же, что в интерфейсе: ключ — `remark_key`; новый — вставка; существующий с
`updated_at` из файла строго позже хранимого — обновление с сохранением `updated_at` из файла;
иначе без изменений. Каждое замечание — один оператор `INSERT ... ON CONFLICT DO UPDATE ... WHERE`:
два одновременных импорта не дают ни дубля, ни ошибки уникальности.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import column, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import (
    CadRemarkFileItem,
    CadRemarksFile,
    CadRemarkWrite,
)
from app.errors import DomainError, ErrorCode
from app.models import CadRemark, Job
from app.services import cad as cad_service

UNIQUE_CONSTRAINT: Final = "uq_cad_remarks_job_attempt_page_view_key"


def attempt_in_range(job: Job, attempt: int) -> bool:
    """Замечания возможны только у попыток, которые у задания были: 1..job.attempt."""
    return 1 <= attempt <= job.attempt


def _mismatch(detail: str) -> DomainError:
    return DomainError(ErrorCode.CAD_REMARKS_BINDING_MISMATCH, detail)


def check_dxf(
    job: Job, *, attempt: int, page_index: int, view: int, dxf_sha256: str | None
) -> None:
    """DXF вида в замечании совпадает с DXF попытки, если итог этой попытки известен.

    Итог хранится только у последней попытки: у прежних проверить нечем, и привязка к ним
    держится на номерах попытки, страницы и вида.
    """
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise _mismatch("Страница или вид вне допустимых номеров") from error
    result = cad_service.result_of(job)
    if result.get("attempt") != attempt:
        return
    artifact = cad_service.find_artifact(job, f"{folder}/plan_candidates.dxf")
    expected = str(artifact["sha256"]) if artifact is not None else None
    if dxf_sha256 != expected:
        raise _mismatch("DXF (sha256) не совпадает с результатом этой попытки")


def check_file_binding(job: Job, file: CadRemarksFile) -> None:
    """Файл обмена относится именно к этому заданию, попытке, странице, виду и DXF."""
    wrong: list[str] = []
    if file.project_id != str(job.project_id):
        wrong.append("проект")
    if file.revision_id != str(job.payload.get("revision_id")):
        wrong.append("ревизия")
    if file.job_id != str(job.id):
        wrong.append("задание")
    if file.legacy_pdf_page != file.page_index + 1:
        wrong.append("страница")
    if wrong:
        raise _mismatch(f"Файл относится к другому результату: не совпадает {', '.join(wrong)}.")


async def list_remarks(
    session: AsyncSession, *, job: Job, attempt: int, page_index: int, view: int
) -> list[CadRemark]:
    rows = await session.scalars(
        select(CadRemark)
        .where(
            CadRemark.job_id == job.id,
            CadRemark.attempt == attempt,
            CadRemark.page_index == page_index,
            CadRemark.view == view,
        )
        .order_by(CadRemark.created_at, CadRemark.remark_key)
    )
    return list(rows)


async def upsert_remark(
    session: AsyncSession,
    *,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    remark_key: str,
    body: CadRemarkWrite,
    user_id: uuid.UUID,
) -> CadRemark:
    """Создаёт замечание или обновляет существующее; время правки ставит сервер."""
    check_dxf(job, attempt=attempt, page_index=page_index, view=view, dxf_sha256=body.dxf_sha256)
    x0, y0, x1, y1 = body.bbox_pt
    values = {
        "type": body.type,
        "comment": body.comment,
        "reviewer": body.reviewer,
        "status": body.status,
        "bbox_x0": x0,
        "bbox_y0": y0,
        "bbox_x1": x1,
        "bbox_y1": y1,
    }
    statement = (
        insert(CadRemark)
        .values(
            workspace_id=job.workspace_id,
            project_id=job.project_id,
            revision_id=uuid.UUID(str(job.payload["revision_id"])),
            job_id=job.id,
            attempt=attempt,
            page_index=page_index,
            view=view,
            dxf_sha256=body.dxf_sha256,
            remark_key=remark_key,
            created_by=user_id,
            updated_by=user_id,
            **values,
        )
        .on_conflict_do_update(
            constraint=UNIQUE_CONSTRAINT,
            set_={**values, "updated_by": user_id, "updated_at": func.now()},
        )
        .returning(CadRemark)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(statement)).one()


async def delete_remark(
    session: AsyncSession,
    *,
    job: Job,
    attempt: int,
    page_index: int,
    view: int,
    remark_key: str,
) -> bool:
    result = await session.execute(
        delete(CadRemark)
        .where(
            CadRemark.job_id == job.id,
            CadRemark.attempt == attempt,
            CadRemark.page_index == page_index,
            CadRemark.view == view,
            CadRemark.remark_key == remark_key,
        )
        .returning(CadRemark.id)
    )
    return result.first() is not None


async def _merge_one(
    session: AsyncSession,
    *,
    job: Job,
    file: CadRemarksFile,
    item: CadRemarkFileItem,
    user_id: uuid.UUID,
) -> bool | None:
    """True - вставлено, False - обновлено, None - без изменений."""
    x0, y0, x1, y1 = item.bbox_pt
    values = {
        "type": item.type,
        "comment": item.comment,
        "reviewer": item.reviewer,
        "status": item.status,
        "bbox_x0": x0,
        "bbox_y0": y0,
        "bbox_x1": x1,
        "bbox_y1": y1,
    }
    statement = (
        insert(CadRemark)
        .values(
            workspace_id=job.workspace_id,
            project_id=job.project_id,
            revision_id=uuid.UUID(str(job.payload["revision_id"])),
            job_id=job.id,
            attempt=file.attempt,
            page_index=file.page_index,
            view=file.view,
            dxf_sha256=file.dxf_sha256,
            remark_key=item.id,
            created_by=user_id,
            updated_by=user_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            **values,
        )
        .on_conflict_do_update(
            constraint=UNIQUE_CONSTRAINT,
            set_={**values, "updated_by": user_id, "updated_at": item.updated_at},
            where=CadRemark.updated_at < item.updated_at,
        )
        # xmax = 0 у только что вставленной строки; у обновлённой он ненулевой.
        .returning(column("xmax") == 0)
    )
    row = (await session.execute(statement)).first()
    return None if row is None else bool(row[0])


async def import_remarks(
    session: AsyncSession, *, job: Job, file: CadRemarksFile, user_id: uuid.UUID
) -> tuple[int, int]:
    """Слияние файла обмена в хранилище. Привязку и номер попытки проверил вызывающий."""
    imported = 0
    updated = 0
    for item in file.remarks:
        merged = await _merge_one(session, job=job, file=file, item=item, user_id=user_id)
        if merged is True:
            imported += 1
        elif merged is False:
            updated += 1
    return imported, updated
