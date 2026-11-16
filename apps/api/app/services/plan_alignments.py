"""Совмещение планов с уровнем (ADR-0043, С3): задание, выдача, подтверждение, входы проверки.

Задание `plan_align` берёт подтверждённые паспорта планов этажей последних ревизий PDF проекта,
находит их виды в итогах CAD (`cad_pdf_convert` + последний успешный `cad_walls`), читает оси из
walls.json и кадр вида (масштаб, начало координат) и совмещает виды каждой секции с её эталонным
планом АР детерминированным правилом `consistency.align.v1`. Второго распознавателя осей нет: оси
- итог `cad_walls`. Повторный запуск заменяет кандидатов; подтверждённые и отклонённые совмещения
не трогает, а подтверждённый эталон секции остаётся эталоном. Доступ к проекту проверяет
вызывающий.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import CadFrameRead, CadScaleRead
from app.contracts.plan_alignments import (
    AlignmentStatus,
    AlignParamsOut,
    AlignRunSummary,
    PlanAlignmentOut,
    PlanAlignmentsOut,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode, not_found
from app.models import Job, PlanAlignment, Project, SheetPassport
from app.services import cad_building3d, cad_views
from app.services import jobs as jobs_service
from app.services.cad_building3d import SheetRef
from app.services.consistency.align_checks import ALIGN_CHECKS_VERSION, AlignmentView
from app.services.consistency.dictionaries import SheetKind, normalize_mark
from app.services.consistency.plan_alignment import (
    ALIGN_VERSION,
    AXIS_AGREE_MM,
    RESIDUAL_CHECK_MM,
    Alignment,
    AlignResult,
    AlignScaleSource,
    SheetAxes,
    align_section,
)
from app.services.sheet_passports import latest_pdf_revisions
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

ALIGN_FAILED_CODE: Final = ErrorCode.PLAN_ALIGN_FAILED.value
NO_CAD: Final = (
    "последняя ревизия листа не преобразована в CAD: преобразуйте лист (флаг cad.export), "
    "оси берутся из подсчёта конструкций"
)
NO_WALLS: Final = "конструкции вида не посчитаны: оси берутся из подсчёта конструкций"
WALLS_UNREADABLE: Final = "walls.json вида не читается"
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


def versions() -> dict[str, str]:
    return {"align": ALIGN_VERSION, "checks": ALIGN_CHECKS_VERSION}


def params() -> AlignParamsOut:
    return AlignParamsOut(axis_agree_mm=AXIS_AGREE_MM, residual_check_mm=RESIDUAL_CHECK_MM)


# --------------------------------------------------------------------------- постановка


async def schedule_align(session: AsyncSession, *, project: Project) -> Job:
    """Ставит задание совмещения; уже есть активное - возвращает его (проект под блокировкой)."""
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    active = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.PLAN_ALIGN,
            Job.project_id == project.id,
            Job.status.in_(_ACTIVE),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active
    return await jobs_service.enqueue(
        session,
        job_type=JobType.PLAN_ALIGN,
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )


# --------------------------------------------------------------------------- исполнитель


@dataclass(frozen=True, slots=True)
class _ViewInput:
    """Вид плана со всем, что нужно для совмещения и записи строки."""

    passport: SheetPassport
    view: int
    cad_job_id: uuid.UUID | None
    axes: SheetAxes
    frame: CadFrameRead | None

    @property
    def key(self) -> str:
        return view_key(self.passport.id, self.view)


def view_key(passport_id: uuid.UUID, view: int) -> str:
    return f"{passport_id}:{view}"


def _is_ar(passport: SheetPassport) -> bool:
    mark = passport.section_mark
    return mark is not None and normalize_mark(mark) == "АР"


def _scale_source(scale: CadScaleRead | None) -> AlignScaleSource | None:
    if scale is None:
        return None
    if scale.source == cad_views.OPERATOR_SOURCE:
        return AlignScaleSource.CALIBRATION
    return AlignScaleSource.DIMENSION_CHAINS


async def _read_view(
    storage: ObjectStorage, passport: SheetPassport, sheet: SheetRef
) -> _ViewInput:
    """Оси и кадр вида; сбой чтения - вид без осей с причиной, а не отказ задания."""
    key = view_key(passport.id, sheet.view)

    def unusable(problem: str, frame: CadFrameRead | None = None) -> _ViewInput:
        axes = SheetAxes(key, _is_ar(passport), {}, {}, None, problem)
        return _ViewInput(passport, sheet.view, sheet.job_id, axes, frame)

    if sheet.walls_key is None:
        return unusable(NO_WALLS)
    if sheet.scale_key is None or sheet.checks_key is None:
        return unusable("в итоге CAD нет масштаба или проверок вида: кадр координат не установлен")
    try:
        raw_walls = await cad_views.read_json(storage, sheet.walls_key)
        scale = cad_views.scale_from(await cad_views.read_json(storage, sheet.scale_key))
        checks = await cad_views.read_json(storage, sheet.checks_key)
    except (
        ObjectNotFoundError,
        StorageUnavailableError,
        cad_views.ArtifactTooLargeError,
        ValueError,
    ):
        return unusable(WALLS_UNREADABLE)
    frame = cad_views.frame_from(scale, checks)
    found = cad_building3d.axes_in_mm(raw_walls, frame)
    axes = SheetAxes(
        key=key,
        is_ar=_is_ar(passport),
        vertical=found.vertical,
        horizontal=found.horizontal,
        scale_source=_scale_source(scale),
        problem=found.message,
    )
    return _ViewInput(passport, sheet.view, sheet.job_id, axes, frame)


async def _plan_passports(session: AsyncSession, project_id: uuid.UUID) -> list[SheetPassport]:
    """Подтверждённые паспорта планов этажей последних ревизий PDF проекта."""
    revision_ids = [item.id for item in await latest_pdf_revisions(session, project_id=project_id)]
    if not revision_ids:
        return []
    rows = await session.scalars(
        select(SheetPassport)
        .where(
            SheetPassport.project_id == project_id,
            SheetPassport.revision_id.in_(revision_ids),
            SheetPassport.status == "confirmed",
            SheetPassport.sheet_kind == SheetKind.FLOOR_PLAN.value,
        )
        .order_by(SheetPassport.file_name, SheetPassport.page_index, SheetPassport.id)
    )
    return list(rows)


def _group(passport: SheetPassport) -> tuple[str | None, str | None]:
    return (passport.building, passport.section)


def _row(item: _ViewInput, alignment: Alignment, project_id: uuid.UUID) -> PlanAlignment:
    passport = item.passport
    frame = item.frame
    confirmed = frame is not None and frame.confirmed
    return PlanAlignment(
        project_id=project_id,
        passport_id=passport.id,
        revision_id=passport.revision_id,
        page_index=passport.page_index,
        view=item.view,
        file_name=passport.file_name,
        section_mark=passport.section_mark,
        building=passport.building,
        section=passport.section,
        level_from=passport.level_from,
        level_to=passport.level_to,
        cad_job_id=item.cad_job_id,
        result=alignment.result.value,
        rotation_deg=alignment.rotation_deg,
        dx_mm=alignment.dx_mm,
        dy_mm=alignment.dy_mm,
        axes=list(alignment.axes),
        common_axes=alignment.common_axes,
        agreed_axes=alignment.agreed_axes,
        residual_rms_mm=alignment.residual_rms_mm,
        residual_max_mm=alignment.residual_max_mm,
        scale_source=None if item.axes.scale_source is None else item.axes.scale_source.value,
        mm_per_pdf_point=frame.mm_per_pdf_point if confirmed and frame else None,
        origin_pt=list(frame.origin_pt) if confirmed and frame and frame.origin_pt else None,
        reasons=list(alignment.reasons),
        status=AlignmentStatus.CANDIDATE.value,
        versions=versions(),
    )


async def _write(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    inputs: list[_ViewInput],
    alignments: dict[str, Alignment],
    reviewed: dict[str, PlanAlignment],
) -> int:
    """Заменяет кандидатов проекта; проверенные строки остаются. Итог - число новых строк."""
    await session.execute(
        delete(PlanAlignment).where(
            PlanAlignment.project_id == project_id,
            PlanAlignment.status == AlignmentStatus.CANDIDATE.value,
        )
    )
    rows: dict[str, PlanAlignment] = dict(reviewed)
    created: list[tuple[PlanAlignment, Alignment]] = []
    for item in inputs:
        if item.key in reviewed:
            continue
        alignment = alignments[item.key]
        row = _row(item, alignment, project_id)
        session.add(row)
        rows[item.key] = row
        created.append((row, alignment))
    await session.flush()
    for row, alignment in created:
        reference = rows.get(alignment.reference_key) if alignment.reference_key else None
        row.reference_id = None if reference is None else reference.id
    await session.flush()
    return len(created)


async def execute_plan_align(
    session: AsyncSession, job: Job, *, storage: ObjectStorage, settings: Settings
) -> Job:
    """Тело задания `plan_align`: кандидаты совмещения видов планов с уровнем.

    Лист без CAD, вид без конструкций, кадра или осей задание не валят: строка с итогом
    `not_run` и причиной. Содержимое документов в итог и журнал не попадает.
    """
    del settings  # пределы чтения JSON CAD - общие (`cad_views.read_json`)
    try:
        project_id = uuid.UUID(str(job.payload.get("project_id")))
    except ValueError:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=ALIGN_FAILED_CODE,
            error_message="в задании нет ссылки на проект",
        )
    if job.workspace_id is None:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=ALIGN_FAILED_CODE,
            error_message="у задания нет рабочего пространства",
        )

    await jobs_service.start(session, job=job, stage="align")
    passports = await _plan_passports(session, project_id)
    sheets, _, _ = await cad_building3d.collect_sheets(
        session, workspace_id=job.workspace_id, project_id=project_id
    )
    by_page: dict[tuple[uuid.UUID, int], list[SheetRef]] = defaultdict(list)
    for sheet in sheets:
        by_page[(sheet.revision_id, sheet.page_index)].append(sheet)
    reviewed = {
        view_key(row.passport_id, row.view): row
        for row in await session.scalars(
            select(PlanAlignment).where(
                PlanAlignment.project_id == project_id,
                PlanAlignment.status != AlignmentStatus.CANDIDATE.value,
            )
        )
    }
    await session.commit()

    inputs: list[_ViewInput] = []
    without_cad = 0
    total = max(len(passports), 1)
    for number, passport in enumerate(passports, start=1):
        refs = by_page.get((passport.revision_id, passport.page_index), [])
        if not refs:
            without_cad += 1
            axes = SheetAxes(view_key(passport.id, 0), _is_ar(passport), {}, {}, None, NO_CAD)
            inputs.append(_ViewInput(passport, 0, None, axes, None))
        for sheet in refs:
            inputs.append(await _read_view(storage, passport, sheet))
        await jobs_service.report_progress(session, job=job, progress=number / total)
        await session.commit()

    # Подтверждённый эталон секции остаётся эталоном: система координат уровня не прыгает.
    preferred = {
        (row.building, row.section): view_key(row.passport_id, row.view)
        for row in reviewed.values()
        if row.status == AlignmentStatus.CONFIRMED.value
        and row.result == AlignResult.REFERENCE.value
    }
    groups: dict[tuple[str | None, str | None], list[_ViewInput]] = defaultdict(list)
    for item in inputs:
        groups[_group(item.passport)].append(item)

    def candidate_axes(item: _ViewInput) -> SheetAxes:
        # Вид, совмещение которого человек отклонил, эталоном секции не становится.
        row = reviewed.get(item.key)
        if row is not None and row.status == AlignmentStatus.REJECTED.value:
            return replace(item.axes, is_ar=False)
        return item.axes

    alignments: dict[str, Alignment] = {}
    for group, items in groups.items():
        for alignment in align_section([candidate_axes(i) for i in items], preferred.get(group)):
            alignments[alignment.key] = alignment

    created = await _write(
        session, project_id=project_id, inputs=inputs, alignments=alignments, reviewed=reviewed
    )
    counts: dict[AlignResult, int] = defaultdict(int)
    for alignment in alignments.values():
        counts[alignment.result] += 1
    log.info(
        "plan_align_finished",
        job_id=str(job.id),
        plans=len(passports),
        views=len(inputs),
        without_cad=without_cad,
        created=created,
    )
    result = await jobs_service.succeed(
        session,
        job=job,
        payload={
            "plans": len(passports),
            "views": len(inputs),
            "without_cad": without_cad,
            "aligned": counts[AlignResult.ALIGNED] + counts[AlignResult.REFERENCE],
            "check": counts[AlignResult.CHECK],
            "failed": counts[AlignResult.FAILED],
            "not_run": counts[AlignResult.NOT_RUN],
            "versions": versions(),
        },
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- выдача


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _payload_versions(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("versions")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


async def latest_run_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> AlignRunSummary | None:
    job = await session.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.PLAN_ALIGN,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    payload: dict[str, Any] = job.payload if isinstance(job.payload, dict) else {}
    return AlignRunSummary(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
        plans=_payload_int(payload, "plans"),
        views=_payload_int(payload, "views"),
        without_cad=_payload_int(payload, "without_cad"),
        aligned=_payload_int(payload, "aligned"),
        check=_payload_int(payload, "check"),
        failed=_payload_int(payload, "failed"),
        not_run=_payload_int(payload, "not_run"),
        versions=_payload_versions(payload),
    )


def _strings(raw: list[Any]) -> list[str]:
    return [item for item in raw if isinstance(item, str)]


def _origin(raw: list[Any] | None) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    values = [item for item in raw if isinstance(item, int | float) and not isinstance(item, bool)]
    return [float(item) for item in values] if len(values) == 2 else None


def _alignment_out(row: PlanAlignment) -> PlanAlignmentOut:
    return PlanAlignmentOut(
        id=row.id,
        passport_id=row.passport_id,
        revision_id=row.revision_id,
        file_name=row.file_name,
        page_index=row.page_index,
        view=row.view,
        section_mark=row.section_mark,
        building=row.building,
        section=row.section,
        level_from=row.level_from,
        level_to=row.level_to,
        cad_job_id=row.cad_job_id,
        reference_id=row.reference_id,
        result=AlignResult(row.result),
        rotation_deg=row.rotation_deg,
        dx_mm=row.dx_mm,
        dy_mm=row.dy_mm,
        axes=_strings(row.axes),
        common_axes=row.common_axes,
        agreed_axes=row.agreed_axes,
        residual_rms_mm=row.residual_rms_mm,
        residual_max_mm=row.residual_max_mm,
        scale_source=None if row.scale_source is None else AlignScaleSource(row.scale_source),
        mm_per_pdf_point=row.mm_per_pdf_point,
        origin_pt=_origin(row.origin_pt),
        reasons=_strings(row.reasons),
        status=AlignmentStatus(row.status),
        confirmed_at=row.confirmed_at,
    )


def _natural(value: str | None) -> tuple[int, int, str]:
    if value is None:
        return (0, 0, "")
    return (1, int(value), "") if value.isdigit() else (2, 0, value)


async def _current_rows(session: AsyncSession, project_id: uuid.UUID) -> list[PlanAlignment]:
    """Совмещения паспортов последних ревизий: по корпусу, секции, файлу, странице и виду."""
    revision_ids = [item.id for item in await latest_pdf_revisions(session, project_id=project_id)]
    if not revision_ids:
        return []
    rows = list(
        await session.scalars(
            select(PlanAlignment).where(
                PlanAlignment.project_id == project_id,
                PlanAlignment.revision_id.in_(revision_ids),
            )
        )
    )
    return sorted(
        rows,
        key=lambda row: (
            _natural(row.building),
            _natural(row.section),
            row.file_name,
            row.page_index,
            row.view,
        ),
    )


async def alignments_view(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> PlanAlignmentsOut:
    rows = await _current_rows(session, project_id)
    return PlanAlignmentsOut(
        alignments=[_alignment_out(row) for row in rows],
        last_run=await latest_run_summary(
            session, workspace_id=workspace_id, project_id=project_id
        ),
        params=params(),
        versions=versions(),
    )


async def bulk_status(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    ids: list[uuid.UUID],
    status: AlignmentStatus,
    user_id: uuid.UUID,
) -> int:
    """Единый статус пачке совмещений проекта; чужой или неизвестный id - 404, без изменений."""
    unique = set(ids)
    found = await session.scalar(
        select(func.count())
        .select_from(PlanAlignment)
        .where(PlanAlignment.project_id == project_id, PlanAlignment.id.in_(unique))
    )
    if int(found or 0) != len(unique):
        raise not_found("Совмещение плана")
    review = status is not AlignmentStatus.CANDIDATE
    updated = await session.scalars(
        update(PlanAlignment)
        .where(PlanAlignment.project_id == project_id, PlanAlignment.id.in_(unique))
        .values(
            status=status.value,
            confirmed_by=user_id if review else None,
            confirmed_at=datetime.now(UTC) if review else None,
        )
        .returning(PlanAlignment.id)
    )
    return len(updated.all())


# --------------------------------------------------------------------------- входы проверки


def _label(row: PlanAlignment) -> str:
    mark = f"{row.section_mark} · " if row.section_mark else ""
    view = f" · вид {row.view}" if row.view > 0 else ""
    return f"{mark}лист {row.page_index + 1}{view}"


async def align_check_inputs(session: AsyncSession, project_id: uuid.UUID) -> list[AlignmentView]:
    """Совмещения последних ревизий, паспорт которых по-прежнему подтверждён."""
    rows = await _current_rows(session, project_id)
    if not rows:
        return []
    confirmed = set(
        await session.scalars(
            select(SheetPassport.id).where(
                SheetPassport.id.in_([row.passport_id for row in rows]),
                SheetPassport.status == "confirmed",
            )
        )
    )
    return [
        AlignmentView(
            id=str(row.id),
            building=row.building,
            section=row.section,
            label=_label(row),
            file_name=row.file_name,
            page_index=row.page_index,
            result=AlignResult(row.result),
            status=row.status,
            residual_rms_mm=row.residual_rms_mm,
            reason=next(iter(_strings(row.reasons)), None),
        )
        for row in rows
        if row.passport_id in confirmed
    ]
