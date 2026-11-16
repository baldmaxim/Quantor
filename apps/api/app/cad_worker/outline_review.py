"""Автоматическая проверка результата CAD на выбранных этажах пилота."""

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import CadError, _download, _run_while_owned, _still_owned
from app.cad_worker.mep_handler import _download_artifact
from app.cad_worker.walls_handler import _view_frame_of, _view_zone_of
from app.contracts.cad_outline_review import OutlinePilot, OutlineReport
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad, jobs
from app.services.cad_walls import WALLS_JSON
from app.storage.base import ObjectStorage

log = structlog.get_logger(__name__)
_CLI = Path(__file__).with_name("outline_review_cli.py")


async def enqueue_after_walls(session: AsyncSession, walls: Job, settings: Settings) -> None:
    if not settings.cad_review_pilot:
        return
    try:
        pilot = OutlinePilot.model_validate_json(settings.cad_review_pilot)
    except ValidationError:
        log.error("cad_outline_review_pilot_invalid")
        return
    if walls.project_id != pilot.project_id or walls.payload.get("revision_id") != str(
        pilot.revision_id
    ):
        return
    result = cad.result_of(walls)
    for floor in pilot.floors:
        if (result.get("page_index"), result.get("view")) != (floor.pdf_page - 1, floor.view):
            continue
        payload = {
            "walls_job_id": str(walls.id),
            "walls_attempt": walls.attempt,
            "revision_id": str(pilot.revision_id),
            "section": pilot.section,
            **floor.model_dump(),
            "sources": pilot.sources,
        }
        digest = hashlib.sha256(cad.params_bytes(payload)).hexdigest()
        await jobs.enqueue(
            session,
            job_type=JobType.CAD_OUTLINE_REVIEW,
            project_id=walls.project_id,
            workspace_id=walls.workspace_id,
            idempotency_key=f"cad-outline-review:v1:{digest}",
            payload=payload,
        )
        return


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
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Попытка обводки недоступна")
    frame = _view_frame_of(walls.payload)
    if frame is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Для сравнения нужен подтверждённый кадр")
    result = cad.result_of(walls)
    folder = cad.view_folder(payload["pdf_page"] - 1, payload["view"])
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
        "schema": "quantor.cad_outline_review.v1",
        "building": 9,
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
        json.dumps(OutlineReport.model_json_schema(), ensure_ascii=False), encoding="utf-8"
    )
    return manifest


async def execute_outline_review(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    owner, attempt = job.worker_id, job.attempt
    await jobs.start(session, job=job, stage="codex_outline_review")
    await session.commit()
    try:
        if not settings.cad_review_ssh_config or not settings.cad_engine_python:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "SSH для проверки не настроен")
        with tempfile.TemporaryDirectory(prefix="quantor-outline-") as directory:
            root = Path(directory)
            manifest = await _prepare(session, job, storage, root)
            await session.commit()
            if not await _still_owned(session, job, owner, attempt):
                return job
            timeout = settings.cad_review_timeout_seconds
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
                limit_seconds=timeout + 45,
                poll_interval=settings.worker_heartbeat_interval_seconds,
                memory_limit_mb=settings.cad_max_memory_mb,
            )
            if outcome is None:
                return job
            code, _ = outcome
            if code == 124:
                raise CadError(ErrorCode.JOB_TIMEOUT, "Codex не уложился во время проверки")
            if code == 255:
                raise CadError(
                    ErrorCode.CAD_ENGINE_UNAVAILABLE, "Нет подключения по SSH к kg_claude"
                )
            if code != 0:
                log.warning("cad_outline_review_process_failed", job_id=str(job.id), exit_code=code)
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED,
                    "Проверка завершилась с ошибкой при подготовке пакета или вызове Codex по SSH",
                )
            with (root / "review.json").open("rb") as report_file:
                raw_report = report_file.read(128 * 1024 + 1)
            if len(raw_report) > 128 * 1024:
                raise ValueError("Отчёт проверки больше допустимого")
            response = json.loads(raw_report)
            report = OutlineReport.model_validate(response["report"])
            if set(response["sources"]) != set(manifest["sources"]):
                raise ValueError("Неполный состав источников")
            result = {**manifest, **response, "report": report.model_dump(mode="json")}
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("cad_outline_review_invalid", job_id=str(job.id), error=type(error).__name__)
        failure = CadError(
            ErrorCode.CAD_ENGINE_FAILED, "Не удалось подготовить или прочитать отчёт"
        )
    except CadError as error:
        failure = error
    else:
        if await _still_owned(session, job, owner, attempt, lock=True):
            return await jobs.succeed(session, job=job, payload={"outline_review": result})
        return job
    if await _still_owned(session, job, owner, attempt, lock=True):
        return await jobs.fail(
            session, job=job, error_code=failure.code.value, error_message=failure.message
        )
    return job
