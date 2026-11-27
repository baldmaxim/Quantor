"""Роль Claude «координация» (`coordination`): пары осей этажа и эталона, задание `cad_ai_review`.

Ставится автоходом петли пилота после конструкций плана (`services/cad_axis_coordination_jobs`) или
вручную. В пакет для модели идут два плана с метками идентификаторов осей и списки осей без
координат. Модель возвращает только пары идентификаторов; смещение в мм считает
`services/cad_axis_coordination` по осям из `walls.json` и кадру вида. Итог - кандидат для сборки
«Здания»: в `plan_alignments` (подтверждение человеком) он не пишется.
"""

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Final

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.ai_style import _view_zone
from app.cad_worker.handler import CadError, _download, _run_while_owned, _still_owned
from app.cad_worker.mep_handler import _download_artifact
from app.contracts.cad import CadFrameRead
from app.contracts.cad_ai_coordination import (
    COORDINATION_AXES_SCHEMA,
    AiCoordinationReport,
    AiCoordinationResult,
    AiCoordinationSkipped,
    AiCoordinationView,
)
from app.contracts.cad_ai_review import AiUsage
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import AiPromptVersion, DocumentRevision, Job
from app.services import ai_loop, cad, cad_views, cad_walls_zones, jobs
from app.services import cad_axis_coordination as coordination
from app.services import cad_axis_coordination_jobs as coordination_jobs
from app.services import cad_building3d as b3d
from app.services.cad_building3d import CoordAxis
from app.services.cad_walls import WALLS_JSON
from app.storage.base import ObjectStorage

log = structlog.get_logger(__name__)
_CLI = Path(__file__).with_name("ai_coordination_cli.py")
_MAX_REPORT_BYTES = 512 * 1024
_MAX_WALLS_BYTES = 64 * 1024 * 1024
ROLE: Final = "coordination"
SIDES: Final = ("target", "reference")
# Меньше двух осей в направлении - пара осей в нём невозможна, модель не спрашиваем.
_MIN_AXES: Final = coordination.MIN_AGREED_PAIRS


def _view_of(payload: dict[str, Any], side: str) -> AiCoordinationView:
    try:
        return AiCoordinationView.model_validate(payload[side])
    except (KeyError, ValidationError) as error:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "В задании нет адреса вида") from error


async def _frame(
    storage: ObjectStorage, convert: Job, revision_id: uuid.UUID, page_index: int, view: int
) -> CadFrameRead:
    """Кадр вида тем же путём, что в сборке «Здания» (`cad_views.frame_from`)."""
    attempt = cad.result_of(convert).get("attempt")
    if type(attempt) is not int:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "У преобразования нет попытки")
    folder = cad.view_folder(page_index, view)
    try:
        scale = cad_views.scale_from(
            await cad_walls_zones._artifact_json(
                storage, convert, revision_id, attempt, f"{folder}/scale.json"
            )
        )
        checks = await cad_walls_zones._artifact_json(
            storage, convert, revision_id, attempt, f"{folder}/cad_checks.json"
        )
    except HTTPException as error:
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    return cad_views.frame_from(scale, checks)


async def _prepare_side(
    session: AsyncSession,
    job: Job,
    storage: ObjectStorage,
    root: Path,
    side: str,
    shared_pdf: dict[uuid.UUID, str],
) -> tuple[dict[str, Any], list[CoordAxis]]:
    view = _view_of(job.payload, side)
    walls = await session.get(Job, view.walls_job_id)
    convert = await session.get(Job, view.cad_job_id)
    revision = await session.get(DocumentRevision, view.revision_id)
    if (
        revision is None
        or walls is None
        or convert is None
        or walls.job_type != JobType.CAD_WALLS
        or walls.status != JobStatus.SUCCEEDED
        or convert.job_type != JobType.CAD_PDF_CONVERT
        or convert.status != JobStatus.SUCCEEDED
        or (walls.project_id, walls.workspace_id) != (job.project_id, job.workspace_id)
        or (convert.project_id, convert.workspace_id) != (job.project_id, job.workspace_id)
        or walls.payload.get("revision_id") != str(view.revision_id)
        or str(walls.payload.get("parent_job_id")) != str(view.cad_job_id)
        or cad.result_of(walls).get("page_index") != view.page_index
        or cad.result_of(walls).get("view") != view.view
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Конструкции вида недоступны для координации")
    frame = await _frame(storage, convert, view.revision_id, view.page_index, view.view)
    if not frame.confirmed:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Для координации нужен подтверждённый кадр")
    folder = cad.view_folder(view.page_index, view.view)
    walls_path = root / f"walls_{side}.json"
    await _download_artifact(
        storage,
        walls,
        view.revision_id,
        f"{folder}/{WALLS_JSON}",
        cad.result_of(walls).get("walls_sha256"),
        walls_path,
    )
    if walls_path.stat().st_size > _MAX_WALLS_BYTES:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "walls.json больше допустимого")
    axes = b3d.coordination_axes(json.loads(walls_path.read_bytes()), frame)
    walls_path.unlink()
    for orient in (coordination.VERTICAL, coordination.HORIZONTAL):
        if sum(1 for axis in axes if axis.orient == orient) < _MIN_AXES:
            raise CadError(
                ErrorCode.CAD_INPUT_INVALID,
                "На виде меньше двух осей в одном из направлений: координировать нечем",
            )
    # Ревизия цели и эталона бывает одна: страница PDF скачивается один раз.
    pdf_file = shared_pdf.get(view.revision_id)
    if pdf_file is None:
        pdf_file = f"{side}.pdf"
        await _download(storage, revision, root / pdf_file)
        shared_pdf[view.revision_id] = pdf_file
    spec = {
        "revision_id": str(view.revision_id),
        "page_index": view.page_index,
        "pdf_page": view.page_index + 1,
        "view": view.view,
        "pdf_file": pdf_file,
        "input_sha256": revision.source_sha256,
        "walls_sha256": cad.result_of(walls).get("walls_sha256"),
        "view_zone": await _view_zone(
            storage, convert, view.revision_id, view.page_index, view.view
        ),
    }
    return spec, axes


async def _active_prompt(session: AsyncSession) -> AiPromptVersion:
    prompt = await session.scalar(
        select(AiPromptVersion).where(
            AiPromptVersion.role == ROLE, AiPromptVersion.status == "active"
        )
    )
    if prompt is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Нет активного промта роли «координация»")
    return prompt


def _prompt_ref(prompt: AiPromptVersion) -> dict[str, Any]:
    return {"prompt_version_id": str(prompt.id), "prompt_version": prompt.version}


async def _prepare(
    session: AsyncSession,
    job: Job,
    storage: ObjectStorage,
    root: Path,
    prompt: AiPromptVersion,
) -> tuple[dict[str, Any], dict[str, list[CoordAxis]]]:
    shared_pdf: dict[uuid.UUID, str] = {}
    specs: dict[str, dict[str, Any]] = {}
    axes: dict[str, list[CoordAxis]] = {}
    for side in SIDES:
        specs[side], axes[side] = await _prepare_side(session, job, storage, root, side, shared_pdf)
    prompt_ref = _prompt_ref(prompt)
    job.payload = {**job.payload, **prompt_ref}
    # Текст дословно, без перекодирования: по этим байтам считается prompt_sha256.
    (root / "prompt.txt").write_bytes(prompt.text.encode())
    for side in SIDES:
        (root / f"axes_{side}.json").write_text(
            json.dumps(
                {
                    "schema": COORDINATION_AXES_SCHEMA,
                    "axes": coordination.axes_document(axes[side]),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Положение осей на странице нужно только рисовальщику меток: модели файл не уходит.
        (root / f"draw_{side}.json").write_text(
            json.dumps(
                {
                    "axes": [
                        {"id": axis.id, "orient": axis.orient, "pos_pt": axis.pos_pt}
                        for axis in axes[side]
                    ]
                }
            ),
            encoding="utf-8",
        )
    manifest = {
        "schema": "quantor.cad_ai_coordination.v1",
        "role": ROLE,
        "project_id": job.payload.get("project_id"),
        "model": job.payload["model"],
        "sources": job.payload["sources"],
        **prompt_ref,
        "target": specs["target"],
        "reference": specs["reference"],
    }
    (root / "manifest.json").write_bytes(cad.params_bytes(manifest))
    (root / "schema.json").write_text(
        json.dumps(AiCoordinationReport.model_json_schema(), ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest, axes


async def _resolve_pair(
    session: AsyncSession, job: Job, storage: ObjectStorage
) -> tuple[AiCoordinationView, AiCoordinationView] | AiCoordinationSkipped:
    """Эталон вида в «Здании»: (цель, эталон) с отпечатками осей либо причина пропуска.

    Модель не вызывается, если эталона нет, вид сам эталон или сборка «Здания» берёт для вида
    иной прогон конструкций.
    """
    target = _view_of(job.payload, "target")
    if job.workspace_id is None or job.project_id is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "У задания нет проекта")
    resolved = await coordination_jobs.resolve_reference(
        session,
        storage,
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        revision_id=target.revision_id,
        page_index=target.page_index,
        view=target.view,
    )
    if isinstance(resolved, str):
        return AiCoordinationSkipped(reason=resolved, target=target)
    reference_walls_id = resolved.reference.walls_job_id
    if resolved.target.walls_job_id != target.walls_job_id or reference_walls_id is None:
        return AiCoordinationSkipped(
            reason="сборка «Здания» берёт для вида иной прогон конструкций", target=target
        )
    reference_walls = await session.get(Job, reference_walls_id)
    if reference_walls is None:
        return AiCoordinationSkipped(reason="конструкции эталона не найдены", target=target)
    try:
        reference = AiCoordinationView.model_validate(
            coordination_jobs.walls_view(reference_walls, resolved.reference_axes_sha256)
        )
    except (ValidationError, DomainError) as error:
        raise CadError(
            ErrorCode.CAD_INPUT_INVALID, "У конструкций эталона нет адреса вида"
        ) from error
    return target.model_copy(update={"axes_sha256": resolved.target_axes_sha256}), reference


async def _finish(
    session: AsyncSession, job: Job, owner: str | None, attempt: int, result: dict[str, Any]
) -> Job:
    """Успех задания: итог под ключом `ai_coordination`, если задание ещё за этим исполнителем."""
    if not await _still_owned(session, job, owner, attempt, lock=True):
        return job
    return await jobs.succeed(session, job=job, payload={"ai_coordination": result})


async def execute_ai_coordination(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    owner, attempt = job.worker_id, job.attempt
    await jobs.start(session, job=job, stage="cad_ai_coordination")
    await session.commit()
    try:
        if not settings.cad_review_ssh_config or not settings.cad_engine_python:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "SSH для координации не настроен")
        with tempfile.TemporaryDirectory(prefix="quantor-ai-coordination-") as directory:
            root = Path(directory)
            if ai_loop.pilot_for_project(job.project_id, settings) is None:
                raise CadError(
                    ErrorCode.CAD_INPUT_INVALID, "ИИ-координация недоступна для этого проекта"
                )
            prompt = await _active_prompt(session)
            pair = await _resolve_pair(session, job, storage)
            if isinstance(pair, AiCoordinationSkipped):
                return await _finish(session, job, owner, attempt, pair.model_dump(mode="json"))
            target_view, reference_view = pair
            reuse = await coordination_jobs.reusable_result(
                session, job, target_view, reference_view, prompt.id
            )
            if reuse is not None:
                source, previous = reuse
                copied = previous.model_copy(
                    update={
                        "target": target_view,
                        "reference": reference_view,
                        "usage": AiUsage(),
                        "reused_from": source.id,
                    }
                )
                job.payload = {**job.payload, **_prompt_ref(prompt)}
                return await _finish(session, job, owner, attempt, copied.model_dump(mode="json"))
            job.payload = {
                **job.payload,
                "target": target_view.model_dump(mode="json"),
                "reference": reference_view.model_dump(mode="json"),
            }
            manifest, axes = await _prepare(session, job, storage, root, prompt)
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
                raise CadError(ErrorCode.JOB_TIMEOUT, "Claude не уложился во время координации")
            if code == 255:
                raise CadError(
                    ErrorCode.CAD_ENGINE_UNAVAILABLE, "Нет подключения по SSH к kg_claude"
                )
            if code != 0:
                log.warning(
                    "cad_ai_coordination_process_failed", job_id=str(job.id), exit_code=code
                )
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED,
                    "Координация завершилась с ошибкой при подготовке пакета или вызове Claude",
                )
            with (root / "coordination.json").open("rb") as report_file:
                raw_report = report_file.read(_MAX_REPORT_BYTES + 1)
            if len(raw_report) > _MAX_REPORT_BYTES:
                raise ValueError("Отчёт координации больше допустимого")
            response = json.loads(raw_report)
            report = AiCoordinationReport.model_validate(response["report"])
            if set(response["sources"]) != set(manifest["sources"]):
                raise ValueError("Неполный состав источников")
            kept, rejected = coordination.sanitize_pairs(report, axes["target"], axes["reference"])
            offset = coordination.compute_offset(kept)
            result = AiCoordinationResult(
                # Отпечаток считается по тем осям, которые видела модель: он ключ применимости пар.
                target=_view_of(job.payload, "target").model_copy(
                    update={"axes_sha256": coordination.axes_fingerprint(axes["target"])}
                ),
                reference=_view_of(job.payload, "reference").model_copy(
                    update={"axes_sha256": coordination.axes_fingerprint(axes["reference"])}
                ),
                model=str(response.get("model", manifest["model"])),
                target_input_sha256=manifest["target"]["input_sha256"],
                reference_input_sha256=manifest["reference"]["input_sha256"],
                target_walls_sha256=manifest["target"]["walls_sha256"],
                reference_walls_sha256=manifest["reference"]["walls_sha256"],
                prompt_version_id=uuid.UUID(manifest["prompt_version_id"]),
                prompt_version=manifest["prompt_version"],
                prompt_sha256=response["prompt_sha256"],
                bundle_sha256=response["bundle_sha256"],
                usage=AiUsage.model_validate(response.get("usage") or {}),
                sources=response["sources"],
                pairs=offset.used,
                dropped=[*rejected, *offset.dropped],
                offset_mm=offset.offset_mm,
                status=offset.status,
                reason=offset.reason,
                notes=report.notes,
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        # ValidationError - подкласс ValueError.
        log.warning("cad_ai_coordination_invalid", job_id=str(job.id), error=type(error).__name__)
        failure = CadError(
            ErrorCode.CAD_ENGINE_FAILED, "Не удалось подготовить или прочитать отчёт"
        )
    except CadError as error:
        failure = error
    else:
        return await _finish(session, job, owner, attempt, result.model_dump(mode="json"))
    if await _still_owned(session, job, owner, attempt, lock=True):
        return await jobs.fail(
            session, job=job, error_code=failure.code.value, error_message=failure.message
        )
    return job
