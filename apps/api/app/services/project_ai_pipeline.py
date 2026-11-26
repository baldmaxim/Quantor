"""Этапы ИИ-проверки проекта (S3-A): сводка по всем листам и запуск этапов проверки.

Этап 1 (прогон чертежей) берётся из того же конвейера CAD, что и панель «Обработка»
(`cad_pipeline.build_pipelines`): последняя ревизия каждого PDF, последний показываемый
`cad_pdf_convert` листа и последнее `cad_walls` вида (в любом статусе). Этапы 2-4 считаются только
по видам, где конструкции успешны. Запросов на проект - константа: конвейеры ревизий, листы, задания
по id, ИИ-проверки и проверки Codex по `walls_job_id`, открытые замечания одной группировкой.

Лимит кругов считается так же, как в `ai_review.enqueue_for_walls`: в него входят все проверки
задания конструкций обеих ролей, включая упавшие. Вердикт, данный по другой попытке конструкций
(`walls_attempt`), в «последний вердикт» не входит, но в лимит идёт.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import ai_review, outline_review
from app.contracts.cad_ai_review import AiLoopPilot, AiReviewResult, AiRole
from app.contracts.cad_ai_style import AiStyleResult
from app.contracts.cad_outline_review import OutlineReviewResult
from app.contracts.cad_pipeline import CadPipelineSheetRead, CadPipelineViewRead
from app.contracts.project_ai_pipeline import (
    AiRunnableStage,
    AiRunResult,
    AiRunSkip,
    AiSheetStage1,
    AiSheetStage2,
    AiSheetStage3,
    AiSheetStage4,
    AiSheetStyle,
    AiStageState,
    AiStageStatus,
    AiStageSummary,
    AiVerdict,
    ProjectAiPipelineRead,
    ProjectAiSheetRow,
)
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import CadRemark, DocumentRevision, Job, Project, Sheet
from app.services import cad as cad_service
from app.services import cad_pipeline, sheet_passports
from app.services.ai_loop import STYLE_ROLE

_ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)
_TITLES = {
    1: "Прогон чертежей",
    2: "Проверка Claude и перестроение",
    3: "Верификация",
    4: "Приёмка человеком",
}


@dataclass(slots=True)
class _Cost:
    cost_usd: float = 0.0
    duration_ms: int = 0
    known: bool = False

    def add(self, result: AiReviewResult) -> None:
        if result.usage.cost_usd is None:
            return
        self.known = True
        self.cost_usd += result.usage.cost_usd
        self.duration_ms += result.usage.duration_ms or 0


@dataclass(slots=True)
class _Reviews:
    """Проверки одного задания конструкций: новые первыми."""

    claude: list[Job] = field(default_factory=list)
    codex: list[Job] = field(default_factory=list)


@dataclass(slots=True)
class _Row:
    revision: DocumentRevision
    sheet: CadPipelineSheetRead
    position: int
    view: CadPipelineViewRead | None
    walls: Job | None
    row: ProjectAiSheetRow
    reviews: _Reviews
    # Решение про лимит и запуск: считается сводкой и используется запуском этапа.
    exhausted: bool = False
    corrector_verdict: AiVerdict | None = None
    corrector_stale: bool = False
    verifier_ok: bool = False
    running: bool = False


def _newest_first(jobs: list[Job]) -> list[Job]:
    return sorted(jobs, key=lambda job: (job.created_at, str(job.id)), reverse=True)


def _project_pilot(project_id: uuid.UUID, settings: Settings) -> AiLoopPilot | None:
    if not settings.cad_ai_loop:
        return None
    try:
        pilot = AiLoopPilot.model_validate_json(settings.cad_ai_loop)
    except ValidationError:
        return None
    return pilot if pilot.project_id == project_id else None


def _ai_result(job: Job) -> AiReviewResult | None:
    raw = job.payload.get("ai_review")
    if job.status is not JobStatus.SUCCEEDED or not isinstance(raw, dict):
        return None
    try:
        return AiReviewResult.model_validate(raw)
    except ValidationError:
        return None


def _style_result(job: Job) -> AiStyleResult | None:
    raw = job.payload.get("ai_style")
    if job.status is not JobStatus.SUCCEEDED or not isinstance(raw, dict):
        return None
    try:
        return AiStyleResult.model_validate(raw)
    except ValidationError:
        return None


def _codex_result(job: Job) -> OutlineReviewResult | None:
    raw = job.payload.get("outline_review")
    if job.status is not JobStatus.SUCCEEDED or not isinstance(raw, dict):
        return None
    try:
        return OutlineReviewResult.model_validate(raw)
    except ValidationError:
        return None


def _job_state(job: Job | None) -> AiStageState:
    if job is None:
        return "not_started"
    if job.status in _ACTIVE:
        return "running"
    return "ok" if job.status is JobStatus.SUCCEEDED else "failed"


_StyleKey = tuple[uuid.UUID, int, int]


def _style_of(
    jobs: list[Job] | None, convert_job: Job | None, page_index: int, view: int
) -> AiSheetStyle | None:
    """Оформление вида: последнее задание роли `style`, регионы - из итога преобразования."""
    if not jobs:
        return None
    last = jobs[0]
    result: AiStyleResult | None = None
    for job in jobs:
        result = _style_result(job)
        if result is not None:
            break
    applied: int | None = None
    raw = cad_service.result_of(convert_job).get("hatch_applied") if convert_job else None
    for entry in raw if isinstance(raw, list) else []:
        if (
            isinstance(entry, dict)
            and entry.get("page_index") == page_index
            and entry.get("view") == view
            and isinstance(entry.get("classes"), list)
        ):
            applied = sum(
                row["added"]
                for row in entry["classes"]
                if isinstance(row, dict) and type(row.get("added")) is int
            )
    failed = _failed(last)
    return AiSheetStyle(
        state=_job_state(last),
        classes_found=len(result.classes) if result is not None else None,
        regions_applied=applied,
        error_message=last.error_message if failed else None,
    )


def _stage1(
    sheet: CadPipelineSheetRead,
    view: CadPipelineViewRead | None,
    jobs: dict[uuid.UUID, Job],
) -> AiSheetStage1:
    """Преобразование и конструкции: хуже состояние побеждает (идёт > ошибка > готово)."""
    convert = sheet.convert
    if convert is None:
        return AiSheetStage1(state="not_started")
    convert_job = jobs.get(convert.job_id)
    update_job = jobs.get(sheet.update.job_id) if sheet.update is not None else None
    walls_job = jobs.get(view.walls.job_id) if view is not None and view.walls is not None else None
    states: list[AiStageState] = [
        _job_state(convert_job),
        _job_state(update_job) if update_job is not None else "ok",
    ]
    if view is not None:
        states.append(_job_state(walls_job))
    for failed in (convert_job, update_job, walls_job):
        if failed is not None and failed.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            message = failed.error_message
            break
    else:
        message = None
    if "running" in states:
        return AiSheetStage1(state="running")
    if "failed" in states:
        return AiSheetStage1(state="failed", error_message=message)
    # Конвертация готова, а конструкций вида ещё нет - вид ждёт постановки.
    return AiSheetStage1(state="not_started" if "not_started" in states else "ok")


def _failed(job: Job | None) -> bool:
    return job is not None and job.status in (JobStatus.FAILED, JobStatus.CANCELLED)


def _stage2(row: _Row, pilot: AiLoopPilot, costs: dict[int, _Cost]) -> AiSheetStage2:
    walls = row.walls
    assert walls is not None
    reviews = row.reviews.claude
    correctors = [job for job in reviews if job.payload.get("role") == "corrector"]
    row.exhausted = len(correctors) >= pilot.max_iterations
    running = any(job.status in _ACTIVE for job in reviews)
    row.running = row.running or running
    parsed = [(job, _ai_result(job)) for job in correctors]
    done = [(job, result) for job, result in parsed if result is not None]
    last_job, last = done[0] if done else (None, None)
    verdict = last.report.verdict if last is not None else None
    stale = last_job is not None and last_job.payload.get("walls_attempt") != walls.attempt
    row.corrector_verdict, row.corrector_stale = verdict, stale
    for job in reviews:
        result = _ai_result(job)
        if result is not None:
            stage = 2 if job.payload.get("role") == "corrector" else 3
            costs[stage].add(result)
    failed_last = bool(correctors) and _failed(correctors[0])
    state: AiStageState
    if running:
        state = "running"
    elif failed_last:
        state = "failed"
    elif verdict == "ready_for_human_review" and not stale:
        state = "ok"
    elif row.exhausted or (verdict == "insufficient_evidence" and not stale):
        state = "attention"
    else:
        state = "not_started"
    return AiSheetStage2(
        state=state,
        rounds_done=len(done),
        rounds_max=pilot.max_iterations,
        exhausted=row.exhausted,
        last_verdict=verdict,
        verdict_stale=stale,
        last_findings=(
            len(last.report.findings) + len(last.report.slab_findings) if last is not None else None
        ),
        running=running,
        error_message=correctors[0].error_message if failed_last else None,
    )


def _stage3(row: _Row, settings: Settings) -> AiSheetStage3:
    walls = row.walls
    assert walls is not None
    verifiers = [job for job in row.reviews.claude if job.payload.get("role") == "verifier"]
    claude_running = any(job.status in _ACTIVE for job in verifiers)
    claude: AiVerdict | None = None
    for job in verifiers:
        result = _ai_result(job)
        if result is not None:
            if job.payload.get("walls_attempt") == walls.attempt:
                claude = result.report.verdict
            break
    codex_running = any(job.status in _ACTIVE for job in row.reviews.codex)
    codex: AiVerdict | None = None
    for job in row.reviews.codex:
        codex_result = _codex_result(job)
        if codex_result is not None:
            if job.payload.get("walls_attempt") == walls.attempt:
                codex = codex_result.report.verdict
            break
    row.running = row.running or claude_running or codex_running
    row.verifier_ok = claude == "ready_for_human_review"
    verdicts = [value for value in (claude, codex) if value is not None]
    latest_failed = bool(verifiers) and _failed(verifiers[0])
    state: AiStageState
    if claude_running or codex_running:
        state = "running"
    elif verdicts:
        ready = all(value == "ready_for_human_review" for value in verdicts)
        state = "ok" if ready else "attention"
    elif latest_failed:
        state = "failed"
    else:
        state = "not_started"
    return AiSheetStage3(
        state=state,
        claude_verdict=claude,
        claude_running=claude_running,
        codex_available=outline_review.review_available(walls, settings),
        codex_verdict=codex,
        codex_running=codex_running,
        error_message=verifiers[0].error_message if latest_failed and not verdicts else None,
    )


def _status(total: int, done: int, running: int, failed: int, needs_human: int) -> AiStageStatus:
    if running > 0:
        return "running"
    if failed > 0 or needs_human > 0:
        return "attention"
    if total > 0 and done == total:
        return "done"
    # Часть листов готова, остальные ждут запуска: нужно действие.
    return "attention" if done > 0 else "not_started"


def _summary(stage: int, states: list[AiStageState], cost: _Cost | None = None) -> AiStageSummary:
    done, running = states.count("ok"), states.count("running")
    failed, needs_human = states.count("failed"), states.count("attention")
    return AiStageSummary(
        stage=stage,
        title=_TITLES[stage],
        total=len(states),
        done=done,
        running=running,
        failed=failed,
        needs_human=needs_human,
        status=_status(len(states), done, running, failed, needs_human),
        cost_usd=cost.cost_usd if cost is not None and cost.known else None,
        duration_ms=cost.duration_ms if cost is not None and cost.known else None,
    )


async def _collect(
    session: AsyncSession, project: Project, settings: Settings
) -> tuple[list[_Row], AiLoopPilot | None, dict[int, _Cost]]:
    revisions = await sheet_passports.latest_pdf_revisions(session, project_id=project.id)
    if not revisions:
        return [], _project_pilot(project.id, settings), {2: _Cost(), 3: _Cost()}
    revision_ids = [revision.id for revision in revisions]
    pipelines = await cad_pipeline.build_pipelines(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        revision_ids=revision_ids,
    )
    positions: dict[uuid.UUID, dict[int, int]] = defaultdict(dict)
    sheet_rows = await session.execute(
        select(Sheet.revision_id, Sheet.page_index)
        .where(Sheet.revision_id.in_(revision_ids))
        .order_by(Sheet.revision_id, Sheet.page_index)
    )
    for revision_id, page_index in sheet_rows.tuples():
        positions[revision_id][page_index] = len(positions[revision_id]) + 1

    job_ids: set[uuid.UUID] = set()
    for pipeline in pipelines.values():
        for sheet in pipeline.sheets:
            for stage in (sheet.convert, sheet.update):
                if stage is not None:
                    job_ids.add(stage.job_id)
            for known in sheet.views:
                if known.walls is not None:
                    job_ids.add(known.walls.job_id)
    jobs: dict[uuid.UUID, Job] = {}
    if job_ids:
        jobs = {
            job.id: job for job in await session.scalars(select(Job).where(Job.id.in_(job_ids)))
        }

    walls_ids = [str(job.id) for job in jobs.values() if job.job_type is JobType.CAD_WALLS]
    reviews: dict[str, _Reviews] = defaultdict(_Reviews)
    if walls_ids:
        found = await session.scalars(
            select(Job).where(
                Job.project_id == project.id,
                Job.job_type.in_((JobType.CAD_AI_REVIEW, JobType.CAD_OUTLINE_REVIEW)),
                Job.payload["walls_job_id"].astext.in_(walls_ids),
            )
        )
        for job in _newest_first(list(found)):
            bucket = reviews[str(job.payload.get("walls_job_id"))]
            (bucket.claude if job.job_type is JobType.CAD_AI_REVIEW else bucket.codex).append(job)

    # Оформление (роль `style`) по виду всей цепочки преобразований: новые первыми.
    styles: dict[_StyleKey, list[Job]] = defaultdict(list)
    style_rows = await session.scalars(
        select(Job).where(
            Job.project_id == project.id,
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.payload["role"].astext == STYLE_ROLE,
        )
    )
    for job in _newest_first(list(style_rows)):
        page, view_no = job.payload.get("page_index"), job.payload.get("view")
        try:
            style_revision = uuid.UUID(str(job.payload.get("revision_id")))
        except ValueError:
            continue
        if type(page) is int and type(view_no) is int:
            styles[(style_revision, page, view_no)].append(job)

    open_remarks: dict[tuple[uuid.UUID, int, int, int], int] = {}
    remark_rows = await session.execute(
        select(
            CadRemark.job_id, CadRemark.attempt, CadRemark.page_index, CadRemark.view, func.count()
        )
        .where(
            CadRemark.project_id == project.id,
            CadRemark.revision_id.in_(revision_ids),
            CadRemark.status == "open",
        )
        .group_by(CadRemark.job_id, CadRemark.attempt, CadRemark.page_index, CadRemark.view)
    )
    for job_id, attempt, page_index, view_no, count in remark_rows.tuples():
        open_remarks[(job_id, attempt, page_index, view_no)] = count

    pilot = _project_pilot(project.id, settings)
    costs = {2: _Cost(), 3: _Cost()}
    rows: list[_Row] = []
    for revision in revisions:
        for sheet in pipelines[revision.id].sheets:
            if not sheet.is_plan and sheet.convert is None:
                continue
            position = positions[revision.id].get(sheet.page_index, sheet.page_index + 1)
            views: list[CadPipelineViewRead | None] = [*sheet.views] if sheet.views else [None]
            for view in views:
                rows.append(
                    _build_row(
                        revision,
                        sheet,
                        view,
                        position,
                        jobs,
                        reviews,
                        styles,
                        open_remarks,
                        pilot,
                        settings,
                        costs,
                    )
                )
    return rows, pilot, costs


def _build_row(
    revision: DocumentRevision,
    sheet: CadPipelineSheetRead,
    view: CadPipelineViewRead | None,
    position: int,
    jobs: dict[uuid.UUID, Job],
    reviews: dict[str, _Reviews],
    styles: dict[_StyleKey, list[Job]],
    open_remarks: dict[tuple[uuid.UUID, int, int, int], int],
    pilot: AiLoopPilot | None,
    settings: Settings,
    costs: dict[int, _Cost],
) -> _Row:
    walls = jobs.get(view.walls.job_id) if view is not None and view.walls is not None else None
    walls_ok = walls is not None and walls.status is JobStatus.SUCCEEDED
    convert_job = jobs.get(sheet.convert.job_id) if sheet.convert is not None else None
    row = ProjectAiSheetRow(
        document_name=revision.source_filename,
        revision_id=revision.id,
        page_index=sheet.page_index,
        sheet_position=position,
        sheet_title=sheet.title or sheet.page_label,
        convert_job_id=convert_job.id if convert_job is not None else None,
        view=view.view if view is not None else None,
        walls_job_id=walls.id if walls is not None else None,
        review_available=walls is not None and ai_review.review_available(walls, settings),
        stage1=_stage1(sheet, view, jobs),
    )
    state = _Row(
        revision=revision,
        sheet=sheet,
        position=position,
        view=view,
        walls=walls if walls_ok else None,
        row=row,
        reviews=reviews.get(str(walls.id), _Reviews()) if walls is not None else _Reviews(),
    )
    state.running = row.stage1.state == "running"
    if view is not None:
        style_jobs = styles.get((revision.id, sheet.page_index, view.view))
        row.style = _style_of(style_jobs, convert_job, sheet.page_index, view.view)
        state.running = state.running or (row.style is not None and row.style.state == "running")
    if walls is None or not walls_ok or view is None:
        return state
    if row.review_available and pilot is not None:
        row.stage2 = _stage2(state, pilot, costs)
    codex_possible = outline_review.review_available(walls, settings)
    if row.review_available or codex_possible:
        row.stage3 = _stage3(state, settings)
    attempt = cad_service.result_of(convert_job).get("attempt") if convert_job is not None else None
    remarks = 0
    if convert_job is not None and isinstance(attempt, int):
        remarks = open_remarks.get((convert_job.id, attempt, sheet.page_index, view.view), 0)
    row.stage4 = AiSheetStage4(
        open_remarks=remarks,
        approved=view.approved,
    )
    return state


async def build(
    session: AsyncSession, project: Project, settings: Settings
) -> ProjectAiPipelineRead:
    rows, pilot, costs = await _collect(session, project, settings)
    sheets = [item.row for item in rows]
    stage4 = [item.row for item in rows if item.row.stage4 is not None]
    stage4_states: list[AiStageState] = []
    for row in stage4:
        assert row.stage4 is not None
        if row.stage4.approved:
            stage4_states.append("ok")
        elif row.stage3 is None or row.stage3.state == "ok":
            stage4_states.append("attention")
        else:
            stage4_states.append("not_started")
    stages = [
        _summary(1, [row.stage1.state for row in sheets]),
        _summary(2, [row.stage2.state for row in sheets if row.stage2 is not None], costs[2]),
        _summary(3, [row.stage3.state for row in sheets if row.stage3 is not None], costs[3]),
        _summary(4, stage4_states),
    ]
    return ProjectAiPipelineRead(
        server_time=datetime.now(UTC),
        available=pilot is not None,
        max_iterations=pilot.max_iterations if pilot is not None else 0,
        codex_available=any(
            row.stage3 is not None and row.stage3.codex_available for row in sheets
        ),
        active=any(item.running for item in rows),
        stages=stages,
        sheets=sheets,
    )


def _skip(item: _Row, reason: str) -> AiRunSkip:
    return AiRunSkip(
        page_index=item.row.page_index,
        view=item.row.view,
        document_name=item.row.document_name,
        reason=reason,
    )


def _refusal(item: _Row, stage: AiRunnableStage) -> str | None:
    """Причина, по которой вид пропускается; `None` - проверку можно ставить."""
    if item.row.stage2 is None:
        return "Для вида ИИ-проверка недоступна"
    if item.row.stage2.running or item.running:
        return "Проверка уже идёт"
    if stage == "review":
        if item.exhausted:
            return "Исчерпан лимит кругов ИИ-проверки"
        if item.row.stage2.state == "ok":
            return "Проверка правщика уже пройдена"
        return None
    # Верификация - после «готово» правщика или после исчерпанных кругов правки.
    ready = item.corrector_verdict == "ready_for_human_review" and not item.corrector_stale
    if not ready and not item.exhausted:
        return "Правщик ещё не дал вердикт «готово к проверке человеком»"
    if item.verifier_ok:
        return "Проверщик уже подтвердил вид"
    return None


async def run_stage(
    session: AsyncSession, project: Project, settings: Settings, stage: AiRunnableStage
) -> AiRunResult:
    """Ставит проверки Claude по подходящим видам; каждая постановка в своём савепоинте."""
    rows, _, _ = await _collect(session, project, settings)
    role: AiRole = "corrector" if stage == "review" else "verifier"
    queued = 0
    skipped: list[AiRunSkip] = []
    for item in rows:
        if item.walls is None or item.view is None:
            continue
        reason = _refusal(item, stage)
        if reason is not None:
            if item.row.stage2 is not None:
                skipped.append(_skip(item, reason))
            continue
        try:
            async with session.begin_nested():
                await ai_review.enqueue_for_walls(session, item.walls, settings, role)
        except DomainError as error:
            skipped.append(_skip(item, error.detail))
            continue
        queued += 1
    return AiRunResult(queued=queued, skipped=skipped)
