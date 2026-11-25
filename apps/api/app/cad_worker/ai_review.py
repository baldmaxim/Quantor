"""ИИ-проверка вида обводки: ручной запуск после `cad_walls`, находки становятся замечаниями CAD.

Свойства конструкций в этом срезе не меняются: предложения правок только сохраняются в задании.
"""

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import CadError, _download, _run_while_owned, _still_owned
from app.cad_worker.mep_handler import _download_artifact
from app.cad_worker.walls_handler import _view_frame_of, _view_zone_of
from app.contracts.cad import MAX_COMMENT_LENGTH, MAX_REVIEWER_LENGTH, CadBboxPt, CadRemarkWrite
from app.contracts.cad_ai_review import (
    AiLoopPilot,
    AiRender,
    AiReviewReport,
    AiReviewResult,
    AiRole,
    AiUsage,
)
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad, cad_remarks, jobs
from app.services.cad_walls import WALLS_JSON
from app.storage.base import ObjectStorage

log = structlog.get_logger(__name__)
_CLI = Path(__file__).with_name("ai_review_cli.py")
_MAX_REPORT_BYTES = 512 * 1024
_BBOX_PAD_PT = 6.0
_ROLE_LABEL: dict[str, str] = {"corrector": "правщик", "verifier": "проверщик"}
# Замечания пишет система, а не пользователь портала: автор - нулевой идентификатор.
_SYSTEM_USER = uuid.UUID(int=0)


def pilot_for(walls: Job, settings: Settings) -> AiLoopPilot | None:
    """Пилот ИИ-проверки, если задание конструкций принадлежит его проекту; иначе None."""
    if not settings.cad_ai_loop:
        return None
    try:
        pilot = AiLoopPilot.model_validate_json(settings.cad_ai_loop)
    except ValidationError:
        log.error("cad_ai_loop_pilot_invalid")
        return None
    return pilot if walls.project_id == pilot.project_id else None


def _view_of(walls: Job) -> tuple[int, int] | None:
    result = cad.result_of(walls)
    page_index, view = result.get("page_index"), result.get("view")
    if type(page_index) is not int or type(view) is not int:
        return None
    return page_index, view


def review_available(walls: Job, settings: Settings) -> bool:
    return (
        walls.job_type == JobType.CAD_WALLS
        and walls.status == JobStatus.SUCCEEDED
        and pilot_for(walls, settings) is not None
        and _view_of(walls) is not None
    )


async def reviews_of(session: AsyncSession, walls: Job) -> list[Job]:
    """ИИ-проверки этого задания конструкций: новые первыми."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.workspace_id == walls.workspace_id,
            Job.project_id == walls.project_id,
            Job.payload["walls_job_id"].astext == str(walls.id),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    return list(rows)


async def enqueue_for_walls(
    session: AsyncSession, walls: Job, settings: Settings, role: AiRole
) -> Job:
    """Ручной запуск проверки; идущую проверку не дублирует, число кругов ограничено."""
    pilot = pilot_for(walls, settings)
    position = _view_of(walls)
    if pilot is None or position is None or not review_available(walls, settings):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "ИИ-проверка для этого листа недоступна")
    existing = await reviews_of(session, walls)
    if existing and existing[0].status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return existing[0]
    iteration = len(existing) + 1
    if iteration > pilot.max_iterations:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "Исчерпан лимит кругов ИИ-проверки")
    parent_id, parent_attempt = (
        walls.payload.get("parent_job_id"),
        walls.payload.get("parent_attempt"),
    )
    if not isinstance(parent_id, str) or type(parent_attempt) is not int:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "У вида нет задания преобразования")
    page_index, view = position
    payload: dict[str, Any] = {
        "walls_job_id": str(walls.id),
        "walls_attempt": walls.attempt,
        "cad_job_id": parent_id,
        "cad_attempt": parent_attempt,
        "revision_id": str(walls.payload.get("revision_id")),
        "page_index": page_index,
        "pdf_page": page_index + 1,
        "view": view,
        "role": role,
        "iteration": iteration,
        "model": pilot.model,
        "sources": pilot.sources,
    }
    digest = hashlib.sha256(cad.params_bytes(payload)).hexdigest()
    return await jobs.enqueue(
        session,
        job_type=JobType.CAD_AI_REVIEW,
        project_id=walls.project_id,
        workspace_id=walls.workspace_id,
        idempotency_key=f"cad-ai-review:v1:{digest}:{iteration}",
        payload=payload,
    )


def bbox_px_to_pt(
    bbox_px: list[float], clip: list[float], zoom: float, pad: float = _BBOX_PAD_PT
) -> CadBboxPt:
    """Рамка в пикселях plan.png -> pt страницы (от левого верхнего угла), с запасом, в clip.

    `clip` - участок страницы, который покрывает растр: пиксель (0, 0) лежит в (clip[0], clip[1]).
    """
    cx0, cy0, cx1, cy1 = clip
    x0, y0, x1, y1 = bbox_px
    left = min(max(cx0 + x0 / zoom - pad, cx0), cx1)
    top = min(max(cy0 + y0 / zoom - pad, cy0), cy1)
    right = min(max(cx0 + x1 / zoom + pad, cx0), cx1)
    bottom = min(max(cy0 + y1 / zoom + pad, cy0), cy1)
    # Рамка целиком вне растра схлопывается на край: оставляем видимый минимум внутри clip.
    if right - left < 1.0:
        left, right = max(cx0, right - 1.0), max(right, min(cx1, cx0 + 1.0))
    if bottom - top < 1.0:
        top, bottom = max(cy0, bottom - 1.0), max(bottom, min(cy1, cy0 + 1.0))
    return (left, top, right, bottom)


def build_remarks(
    *,
    job_id: uuid.UUID,
    role: str,
    iteration: int,
    report: AiReviewReport,
    render: AiRender,
    dxf_sha256: str,
) -> list[tuple[str, CadRemarkWrite]]:
    """Находки отчёта как замечания CAD; ключи детерминированы по заданию и номеру находки."""
    reviewer = f"ИИ {_ROLE_LABEL.get(role, role)} · круг {iteration}"[:MAX_REVIEWER_LENGTH]
    rows: list[tuple[str, CadRemarkWrite]] = []
    for index, finding in enumerate(report.findings):
        key = "ai-" + hashlib.sha1(f"{job_id}:{index}".encode()).hexdigest()[:20]  # noqa: S324
        comment = (
            f"[{finding.priority}] {finding.observation} — Доказательство: {finding.evidence}"
            f" — Исправить: {finding.suggested_fix}"
        )
        rows.append(
            (
                key,
                CadRemarkWrite(
                    type=finding.type,
                    comment=comment[:MAX_COMMENT_LENGTH],
                    reviewer=reviewer,
                    status="open",
                    bbox_pt=bbox_px_to_pt(finding.bbox_px, render.clip, render.zoom),
                    dxf_sha256=dxf_sha256,
                ),
            )
        )
    return rows


async def _write_remarks(
    session: AsyncSession, job: Job, rows: list[tuple[str, CadRemarkWrite]]
) -> None:
    payload = job.payload
    cad_job = await session.get(Job, uuid.UUID(payload["cad_job_id"]))
    attempt = payload["cad_attempt"]
    if (
        cad_job is None
        or cad_job.job_type != JobType.CAD_PDF_CONVERT
        or (cad_job.project_id, cad_job.workspace_id) != (job.project_id, job.workspace_id)
        or not cad_remarks.attempt_in_range(cad_job, attempt)
    ):
        raise CadError(
            ErrorCode.CAD_INPUT_INVALID, "Задание преобразования недоступно для замечаний"
        )
    try:
        # Савепоинт: при отказе на середине ни одно замечание этого запуска не остаётся.
        async with session.begin_nested():
            for key, body in rows:
                await cad_remarks.upsert_remark(
                    session,
                    job=cad_job,
                    attempt=attempt,
                    page_index=payload["page_index"],
                    view=payload["view"],
                    remark_key=key,
                    body=body,
                    user_id=_SYSTEM_USER,
                )
    except DomainError as error:
        raise CadError(
            ErrorCode.CAD_INPUT_INVALID, f"Замечания не привязаны: {error.code.value}"
        ) from error


async def _prepare(
    session: AsyncSession, job: Job, storage: ObjectStorage, root: Path
) -> dict[str, Any]:
    payload = job.payload
    revision_id = uuid.UUID(payload["revision_id"])
    walls = await session.get(Job, uuid.UUID(payload["walls_job_id"]))
    revision = await session.get(DocumentRevision, revision_id)
    if (
        revision is None
        or walls is None
        or walls.job_type != JobType.CAD_WALLS
        or walls.status != JobStatus.SUCCEEDED
        or (walls.project_id, walls.workspace_id) != (job.project_id, job.workspace_id)
        or walls.payload.get("revision_id") != str(revision_id)
        or walls.attempt != payload["walls_attempt"]
        or str(walls.payload.get("parent_job_id")) != payload["cad_job_id"]
        or walls.payload.get("parent_attempt") != payload["cad_attempt"]
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Попытка обводки недоступна")
    frame = _view_frame_of(walls.payload)
    if frame is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Для проверки нужен подтверждённый кадр")
    result = cad.result_of(walls)
    if (result.get("page_index"), result.get("view")) != (payload["page_index"], payload["view"]):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Вид обводки не совпал с заданием")
    folder = cad.view_folder(payload["page_index"], payload["view"])
    await _download(storage, revision, root / "input.pdf")
    await _download_artifact(
        storage,
        walls,
        revision_id,
        f"{folder}/{WALLS_JSON}",
        result["walls_sha256"],
        root / "walls.json",
    )
    manifest = {
        **payload,
        "schema": "quantor.cad_ai_review.v1",
        "input_sha256": revision.source_sha256,
        "walls_sha256": result["walls_sha256"],
        "dxf_sha256": result["dxf_sha256"],
        "generator": result["generator"],
        "zones_count": result.get("zones_count", 0),
        "frame": frame,
        "view_zone": _view_zone_of(walls.payload),
    }
    (root / "manifest.json").write_bytes(cad.params_bytes(manifest))
    (root / "schema.json").write_text(
        json.dumps(AiReviewReport.model_json_schema(), ensure_ascii=False), encoding="utf-8"
    )
    return manifest


async def execute_ai_review(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    owner, attempt = job.worker_id, job.attempt
    await jobs.start(session, job=job, stage="cad_ai_review")
    await session.commit()
    try:
        if not settings.cad_review_ssh_config or not settings.cad_engine_python:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "SSH для проверки не настроен")
        with tempfile.TemporaryDirectory(prefix="quantor-ai-review-") as directory:
            root = Path(directory)
            manifest = await _prepare(session, job, storage, root)
            await session.commit()
            if not await _still_owned(session, job, owner, attempt):
                return job
            timeout = settings.cad_ai_timeout_seconds
            outcome = await _run_while_owned(
                session,
                job,
                owner,
                attempt,
                [
                    settings.cad_engine_python,
                    "-I",
                    str(_CLI),
                    directory,
                    settings.cad_review_ssh_config,
                    str(timeout),
                ],
                limit_seconds=timeout + 60,
                poll_interval=settings.worker_heartbeat_interval_seconds,
                memory_limit_mb=settings.cad_max_memory_mb,
            )
            if outcome is None:
                return job
            code, _ = outcome
            if code == 124:
                raise CadError(ErrorCode.JOB_TIMEOUT, "Claude не уложился во время проверки")
            if code == 255:
                raise CadError(
                    ErrorCode.CAD_ENGINE_UNAVAILABLE, "Нет подключения по SSH к kg_claude"
                )
            if code != 0:
                log.warning("cad_ai_review_process_failed", job_id=str(job.id), exit_code=code)
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED,
                    "Проверка завершилась с ошибкой при подготовке пакета или вызове Claude по SSH",
                )
            with (root / "review.json").open("rb") as report_file:
                raw_report = report_file.read(_MAX_REPORT_BYTES + 1)
            if len(raw_report) > _MAX_REPORT_BYTES:
                raise ValueError("Отчёт проверки больше допустимого")
            response = json.loads(raw_report)
            report = AiReviewReport.model_validate(response["report"])
            if set(response["sources"]) != set(manifest["sources"]):
                raise ValueError("Неполный состав источников")
            render = AiRender.model_validate(json.loads((root / "render.json").read_bytes()))
            remarks = build_remarks(
                job_id=job.id,
                role=manifest["role"],
                iteration=manifest["iteration"],
                report=report,
                render=render,
                dxf_sha256=manifest["dxf_sha256"],
            )
            result = AiReviewResult(
                walls_job_id=manifest["walls_job_id"],
                walls_attempt=manifest["walls_attempt"],
                cad_job_id=manifest["cad_job_id"],
                revision_id=manifest["revision_id"],
                page_index=manifest["page_index"],
                view=manifest["view"],
                role=manifest["role"],
                iteration=manifest["iteration"],
                model=str(response.get("model", manifest["model"])),
                input_sha256=manifest["input_sha256"],
                walls_sha256=manifest["walls_sha256"],
                dxf_sha256=manifest["dxf_sha256"],
                prompt_sha256=response["prompt_sha256"],
                bundle_sha256=response["bundle_sha256"],
                sources=response["sources"],
                usage=AiUsage.model_validate(response.get("usage") or {}),
                render=render,
                remark_keys=[key for key, _ in remarks],
                report=report,
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        # ValidationError - подкласс ValueError.
        log.warning("cad_ai_review_invalid", job_id=str(job.id), error=type(error).__name__)
        failure = CadError(
            ErrorCode.CAD_ENGINE_FAILED, "Не удалось подготовить или прочитать отчёт"
        )
    except CadError as error:
        failure = error
    else:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        try:
            await _write_remarks(session, job, remarks)
        except CadError as error:
            failure = error
        else:
            return await jobs.succeed(
                session, job=job, payload={"ai_review": result.model_dump(mode="json")}
            )
    if await _still_owned(session, job, owner, attempt, lock=True):
        return await jobs.fail(
            session, job=job, error_code=failure.code.value, error_message=failure.message
        )
    return job
