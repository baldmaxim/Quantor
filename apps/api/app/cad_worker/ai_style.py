"""Роль Claude «оформление» (`style`): классы подписей штриховки плана, задание `cad_ai_review`.

Ставится автоходом петли пилота (`services/ai_loop`) после первого преобразования листа-плана.
В пакет для модели идут вырезка вида, страница PDF и `hatch_signatures.json` движка. Модель
возвращает класс только по идентификатору подписи; числа подписи (цвет, перо, угол, шаг) сервер
берёт из пакета по идентификатору. Площадей и количеств модель не даёт и сервер не принимает.
Класс уходит движку подсказкой преобразования (`hatch_classes`).
"""

import json
import math
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import CadError, _download, _run_while_owned, _still_owned
from app.cad_worker.mep_handler import _download_artifact
from app.contracts.cad_ai_review import AiUsage
from app.contracts.cad_ai_style import (
    STYLE_SIGNATURES_SCHEMA,
    AiStyleReport,
    AiStyleResolved,
    AiStyleResult,
)
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import AiPromptVersion, DocumentRevision, Job
from app.services import ai_loop, cad, cad_views, cad_walls_zones, jobs
from app.storage.base import ObjectStorage

log = structlog.get_logger(__name__)
_CLI = Path(__file__).with_name("ai_style_cli.py")
_MAX_REPORT_BYTES = 512 * 1024
_MAX_SIGNATURES_BYTES = 1024 * 1024
ROLE: Final = "style"
SIGNATURES_NAME: Final = "hatch_signatures.json"


def read_signatures(raw: bytes) -> dict[str, dict[str, Any]]:
    """Подписи пакета по идентификатору; чужая схема или повтор идентификатора - ошибка."""
    if len(raw) > _MAX_SIGNATURES_BYTES:
        raise ValueError("hatch_signatures.json больше допустимого")
    document = json.loads(raw)
    rows = document.get("signatures") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("schema") != STYLE_SIGNATURES_SCHEMA
        or not isinstance(rows, list)
    ):
        raise ValueError("hatch_signatures.json: неожиданная схема")
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] not in found:
            found[row["id"]] = row
    return found


def sanitize_report(
    report: AiStyleReport, signatures: Mapping[str, Mapping[str, Any]]
) -> tuple[list[AiStyleResolved], list[str]]:
    """Классы с числами из пакета; чужие id, заливки и повторы отбрасываются (строки причин)."""
    resolved: list[AiStyleResolved] = []
    seen: set[str] = set()
    foreign = fills = repeated = broken = 0
    for item in report.classes:
        row = signatures.get(item.signature_id)
        if row is None:
            foreign += 1
            continue
        if item.signature_id in seen:
            repeated += 1
            continue
        if row.get("kind") != "hatch":
            # У заливки нет пера, угла и шага: классом подписи движку её не передать.
            fills += 1
            continue
        try:
            resolved.append(
                AiStyleResolved.model_validate(
                    {
                        "signature_id": item.signature_id,
                        "class_name": item.class_,
                        "confidence": item.confidence,
                        "evidence": item.evidence,
                        "color": row.get("color"),
                        "pen_pt": row.get("pen_pt"),
                        "angle_deg": row.get("angle_deg"),
                        "pitch_pt": row.get("pitch_pt"),
                    }
                )
            )
        except ValidationError:
            broken += 1
            continue
        seen.add(item.signature_id)
    dropped: list[str] = []
    if foreign:
        dropped.append(f"Отброшено подписей вне пакета: {foreign}")
    if fills:
        dropped.append(f"Отброшено заливок (класс только у штриховок): {fills}")
    if repeated:
        dropped.append(f"Отброшено повторов подписи: {repeated}")
    if broken:
        dropped.append(f"Отброшено подписей с неполными числами: {broken}")
    return resolved, dropped


async def _view_zone(
    storage: ObjectStorage, convert: Job, revision_id: uuid.UUID, page_index: int, view: int
) -> list[float] | None:
    """Вырезка вида в pt страницы по подтверждённому кадру; нет кадра - вся страница."""
    try:
        return await _view_zone_of(storage, convert, revision_id, page_index, view)
    except HTTPException as error:
        # Хранилище недоступно: `_artifact_json` отвечает HTTP-ошибкой, исполнителю нужна CadError.
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error


async def _view_zone_of(
    storage: ObjectStorage, convert: Job, revision_id: uuid.UUID, page_index: int, view: int
) -> list[float] | None:
    attempt = cad.result_of(convert).get("attempt")
    if type(attempt) is not int:
        return None
    folder = cad.view_folder(page_index, view)
    scale = cad_views.scale_from(
        await cad_walls_zones._artifact_json(
            storage, convert, revision_id, attempt, f"{folder}/scale.json"
        )
    )
    checks = await cad_walls_zones._artifact_json(
        storage, convert, revision_id, attempt, f"{folder}/cad_checks.json"
    )
    frame = cad_views.frame_from(scale, checks)
    if not frame.confirmed or frame.origin_pt is None or not frame.mm_per_pdf_point:
        return None
    preview = await cad_walls_zones._artifact_json(
        storage, convert, revision_id, attempt, f"{folder}/preview.json"
    )
    zone = cad_walls_zones.view_zone_pt(
        preview.get("bbox") if isinstance(preview, dict) else None,
        origin_pt=frame.origin_pt,
        mm_per_pdf_point=frame.mm_per_pdf_point,
    )
    if zone is None or not all(math.isfinite(value) for value in zone):
        return None
    return [float(value) for value in zone]


async def _prepare(
    session: AsyncSession,
    job: Job,
    storage: ObjectStorage,
    settings: Settings,
    root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    payload = job.payload
    if ai_loop.pilot_for_project(job.project_id, settings) is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "ИИ-оформление недоступно для этого проекта")
    revision_id = uuid.UUID(payload["revision_id"])
    convert = await session.get(Job, uuid.UUID(payload["cad_job_id"]))
    revision = await session.get(DocumentRevision, revision_id)
    page_index, view = payload["page_index"], payload["view"]
    if (
        revision is None
        or convert is None
        or convert.job_type != JobType.CAD_PDF_CONVERT
        or convert.status != JobStatus.SUCCEEDED
        or (convert.project_id, convert.workspace_id) != (job.project_id, job.workspace_id)
        or convert.payload.get("revision_id") != str(revision_id)
        or cad.result_of(convert).get("attempt") != payload["cad_attempt"]
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Преобразование недоступно для оформления")
    folder = cad.view_folder(page_index, view)
    await _download(storage, revision, root / "input.pdf")
    await _download_artifact(
        storage, convert, revision_id, f"{folder}/{SIGNATURES_NAME}", None, root / SIGNATURES_NAME
    )
    signatures = read_signatures((root / SIGNATURES_NAME).read_bytes())
    artifact = cad.find_artifact(convert, f"{folder}/{SIGNATURES_NAME}")
    if artifact is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "У преобразования нет статистики оформления")
    prompt = await session.scalar(
        select(AiPromptVersion).where(
            AiPromptVersion.role == ROLE, AiPromptVersion.status == "active"
        )
    )
    if prompt is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Нет активного промта роли «оформление»")
    prompt_ref: dict[str, Any] = {
        "prompt_version_id": str(prompt.id),
        "prompt_version": prompt.version,
    }
    job.payload = {**job.payload, **prompt_ref}
    # Текст дословно, без перекодирования: по этим байтам считается prompt_sha256.
    (root / "prompt.txt").write_bytes(prompt.text.encode())
    manifest = {
        **payload,
        **prompt_ref,
        "schema": "quantor.cad_ai_style.v1",
        "input_sha256": revision.source_sha256,
        "signatures_sha256": artifact["sha256"],
        "view_zone": await _view_zone(storage, convert, revision_id, page_index, view),
    }
    (root / "manifest.json").write_bytes(cad.params_bytes(manifest))
    (root / "schema.json").write_text(
        json.dumps(AiStyleReport.model_json_schema(), ensure_ascii=False), encoding="utf-8"
    )
    return manifest, signatures


async def execute_ai_style(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    owner, attempt = job.worker_id, job.attempt
    await jobs.start(session, job=job, stage="cad_ai_style")
    await session.commit()
    try:
        if not settings.cad_review_ssh_config or not settings.cad_engine_python:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "SSH для оформления не настроен")
        with tempfile.TemporaryDirectory(prefix="quantor-ai-style-") as directory:
            root = Path(directory)
            manifest, signatures = await _prepare(session, job, storage, settings, root)
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
                raise CadError(ErrorCode.JOB_TIMEOUT, "Claude не уложился во время оформления")
            if code == 255:
                raise CadError(
                    ErrorCode.CAD_ENGINE_UNAVAILABLE, "Нет подключения по SSH к kg_claude"
                )
            if code != 0:
                log.warning("cad_ai_style_process_failed", job_id=str(job.id), exit_code=code)
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED,
                    "Оформление завершилось с ошибкой при подготовке пакета или вызове Claude",
                )
            with (root / "style.json").open("rb") as report_file:
                raw_report = report_file.read(_MAX_REPORT_BYTES + 1)
            if len(raw_report) > _MAX_REPORT_BYTES:
                raise ValueError("Отчёт оформления больше допустимого")
            response = json.loads(raw_report)
            report = AiStyleReport.model_validate(response["report"])
            if set(response["sources"]) != set(manifest["sources"]):
                raise ValueError("Неполный состав источников")
            classes, dropped = sanitize_report(report, signatures)
            result = AiStyleResult(
                cad_job_id=uuid.UUID(manifest["cad_job_id"]),
                cad_attempt=manifest["cad_attempt"],
                revision_id=uuid.UUID(manifest["revision_id"]),
                page_index=manifest["page_index"],
                view=manifest["view"],
                model=str(response.get("model", manifest["model"])),
                input_sha256=manifest["input_sha256"],
                signatures_sha256=manifest["signatures_sha256"],
                prompt_version_id=uuid.UUID(manifest["prompt_version_id"]),
                prompt_version=manifest["prompt_version"],
                prompt_sha256=response["prompt_sha256"],
                bundle_sha256=response["bundle_sha256"],
                usage=AiUsage.model_validate(response.get("usage") or {}),
                sources=response["sources"],
                classes=classes,
                dropped=dropped,
                limitations=report.limitations,
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        # ValidationError - подкласс ValueError.
        log.warning("cad_ai_style_invalid", job_id=str(job.id), error=type(error).__name__)
        failure = CadError(
            ErrorCode.CAD_ENGINE_FAILED, "Не удалось подготовить или прочитать отчёт"
        )
    except CadError as error:
        failure = error
    else:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        done = await jobs.succeed(
            session, job=job, payload={"ai_style": result.model_dump(mode="json")}
        )
        # Автоход петли: в той же транзакции; сбой постановки задание оформления не роняет.
        await ai_loop.after_style(session, done, settings)
        return done
    if await _still_owned(session, job, owner, attempt, lock=True):
        return await jobs.fail(
            session, job=job, error_code=failure.code.value, error_message=failure.message
        )
    return job
