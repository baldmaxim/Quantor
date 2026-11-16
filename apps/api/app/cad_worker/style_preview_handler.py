"""Тело задания `cad_style_preview`: образцы -> runner `style` -> кандидат профиля (ADR-0049).

Движок не импортируется: runner (`tools/cad_engine`) подпроцессом интерпретатора движка проверяет
архив, распаковывает его и запускает `style_samples.py` по исходному PDF ревизии. Результат -
малый JSON в payload задания (`cad_result`): тело профиля (если хоть один образец дал подпись) и
предпросмотр. Файлов в хранилище нет. Профиль тома здесь не создаётся: это делает человек,
принимая результат.

Исход runner: код 0 - `profile`; в `result.json` статус `no_signature` - ни один образец не дал
подписи, есть только предпросмотр (это не ошибка); остальные коды - отказ задания.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Final, NamedTuple

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.facades_handler import _has_nul
from app.cad_worker.handler import (
    _EXIT_CODES,
    CadError,
    EngineCommand,
    _download,
    _fail,
    _run_while_owned,
    _still_owned,
)
from app.contracts.cad_style_profiles import (
    STYLE_SCHEMA,
    CadStyleProfileBody,
    CadStyleSample,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobType
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_progress, cad_style_preview, cad_style_profiles
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)

SAMPLES_SCHEMA: Final = "cad_engine.style_samples.v1"
# Служебный номер версии для скрипта: настоящий номер назначит сервер при принятии профиля.
SERVICE_PROFILE_VERSION: Final = 1
# Runner сам ограничивает скрипт (120 с); это страховка исполнителя поверх, с запасом на
# проверку архива и распаковку.
RUNNER_LIMIT_SECONDS: Final = 240.0
_SAMPLES: Final = TypeAdapter(list[CadStyleSample])


def _runner_failure(code: int, output: bytes) -> CadError:
    """Отказ runner: код выхода -> код ошибки Quantor; текст - из строки `{"error": ...}` runner."""
    mapped = _EXIT_CODES.get(code, ErrorCode.CAD_ENGINE_FAILED)
    message = "снятие профиля оформления не удалось"
    detail: dict[str, Any] = {}
    for line in reversed(output.decode(errors="replace").strip().splitlines()):
        try:
            error = json.loads(line).get("error")
        except (ValueError, AttributeError):
            continue
        if isinstance(error, dict):
            text = error.get("message")
            engine_code = error.get("code")
            if isinstance(text, str) and text:
                message = text[:300]
            if isinstance(engine_code, str):
                detail["engine_error"] = engine_code[:64]
            break
    # Код 4 - и время, и предел входа: время отличается кодом ошибки runner.
    if code == 4 and detail.get("engine_error") == "timeout":
        mapped = ErrorCode.JOB_TIMEOUT
    return CadError(mapped, message, detail)


def _positive_scale(value: object) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    ):
        return float(value)
    raise CadError(ErrorCode.CAD_PARAMS_INVALID, "масштаб листа в задании задан неверно")


def _read_json_object(path: Path, what: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{what}: файла нет или он вне контракта")
    if path.stat().st_size > cad_style_preview.PREVIEW_MAX_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{what} больше допустимого размера")
    try:
        raw = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{what} не разобран") from error
    if not isinstance(raw, dict) or _has_nul(raw):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{what} вне контракта")
    return raw


def _verified_output(out: Path) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """(статус, тело профиля или None, предпросмотр); состав out/ и согласие с pins - строго."""
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if (
        not {"result.json", "preview.json"}
        <= present
        <= {
            "result.json",
            "preview.json",
            "style_profile.json",
        }
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом runner")
    result = _read_json_object(out / "result.json", "result.json")
    status = result.get("status")
    if (
        status not in ("profile", "no_signature")
        or result.get("engine_version") != cad_service.ENGINE_VERSION
        or result.get("archive_sha256") != cad_service.ENGINE_ARCHIVE_SHA256
        or (status == "profile") != ("style_profile.json" in present)
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "result.json не согласован с файлами")
    preview = _read_json_object(out / "preview.json", "preview.json")
    if status == "no_signature":
        return "no_signature", None, preview
    style = _read_json_object(out / "style_profile.json", "style_profile.json")
    body = style.get("profile")
    if style.get("schema") != STYLE_SCHEMA or not isinstance(body, dict):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "style_profile.json вне контракта")
    return "profile", body, preview


MAX_REASONS: Final = 20
MAX_REASON_LENGTH: Final = 200


def _limit_reasons(profile: dict[str, Any]) -> list[str]:
    """Причины, по которым тело профиля не проходит контракт API: поле и правило, без значений."""
    try:
        CadStyleProfileBody.model_validate(profile)
    except ValidationError as error:
        return [
            f"{'.'.join(str(part) for part in row['loc'])}: {row['type']}"[:MAX_REASON_LENGTH]
            for row in error.errors(include_input=False, include_url=False, include_context=False)
        ][:MAX_REASONS]
    return []


class _Inputs(NamedTuple):
    document_id: uuid.UUID
    revision_id: uuid.UUID
    page_index: int
    samples: list[CadStyleSample]
    mm_per_pt: float | None
    base_version: int | None


def _payload_inputs(job: Job) -> _Inputs:
    payload = job.payload
    try:
        document_id = uuid.UUID(str(payload.get("document_id")))
        revision_id = uuid.UUID(str(payload.get("revision_id")))
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "в задании нет тома или ревизии") from error
    page_index = payload.get("page_index")
    base_version = payload.get("base_version")
    if type(page_index) is not int or page_index < 0:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "страница в задании задана неверно")
    if base_version is not None and (type(base_version) is not int or base_version < 1):
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "версия профиля в задании задана неверно")
    try:
        samples = _SAMPLES.validate_python(payload.get("samples"))
    except ValidationError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "образцы в задании заданы неверно") from error
    if not samples:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "в задании нет образцов")
    return _Inputs(
        document_id,
        revision_id,
        page_index,
        samples,
        _positive_scale(payload.get("mm_per_pt")),
        base_version,
    )


async def execute_cad_style_preview(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    try:
        inputs = _payload_inputs(job)
    except CadError as failure:
        return await _fail(session, job, failure)
    document_id, revision_id, page_index = inputs.document_id, inputs.revision_id, inputs.page_index
    samples, mm_per_pt, base_version = inputs.samples, inputs.mm_per_pt, inputs.base_version
    revision = await session.get(DocumentRevision, revision_id)
    if (
        revision is None
        or revision.document_id != document_id
        or job.workspace_id is None
        or job.project_id is None
    ):
        return await _fail(session, job, CadError(ErrorCode.CAD_PARAMS_INVALID, "нет ревизии"))
    workspace_id = job.workspace_id

    owner, attempt = job.worker_id, job.attempt
    await jobs_service.start(session, job=job, stage=JobType.CAD_STYLE_PREVIEW.value)
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        command = EngineCommand.from_settings(settings)
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "work", "out"):
            (attempt_dir / sub).mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "Исходный PDF ревизии: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
        pdf = attempt_dir / "in" / "source.pdf"
        await _download(storage, revision, pdf)

        samples_document: dict[str, Any] = {
            "schema": SAMPLES_SCHEMA,
            "page_index": page_index,
            "profile_id": cad_style_profiles.profile_key_for(document_id),
            "profile_version": SERVICE_PROFILE_VERSION,
            "samples": [item.model_dump(mode="json", by_alias=True) for item in samples],
        }
        if mm_per_pt is not None:
            samples_document["mm_per_pt"] = mm_per_pt
        samples_file = attempt_dir / "in" / "samples.json"
        samples_file.write_text(json.dumps(samples_document, ensure_ascii=False), encoding="utf-8")
        args = [
            "style",
            "--input",
            str(pdf),
            "--samples",
            str(samples_file),
            "--work",
            str(attempt_dir / "work"),
            "--out",
            str(attempt_dir / "out"),
            "--max-memory-mb",
            str(settings.cad_max_memory_mb),
        ]
        if base_version is not None:
            base = await cad_style_profiles.get_version(
                session, workspace_id=workspace_id, document_id=document_id, version=base_version
            )
            if base is None:
                raise CadError(ErrorCode.CAD_PARAMS_INVALID, "базовая версия профиля не найдена")
            base_file = attempt_dir / "in" / "base_profile.json"
            base_file.write_text(json.dumps(base.style, ensure_ascii=False), encoding="utf-8")
            args += ["--base-profile", str(base_file)]

        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "worker",
            "Снятие профиля оформления по образцам на листе",
            cad_progress.now(),
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            command.argv(*args),
            limit_seconds=RUNNER_LIMIT_SECONDS,
            poll_interval=settings.worker_heartbeat_interval_seconds,
        )
        if outcome is None:
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        code, output = outcome
        if code != 0:
            raise _runner_failure(code, output)
        status, profile, preview = _verified_output(attempt_dir / "out")
        reasons: list[str] = []
        if profile is not None:
            reasons = _limit_reasons(profile)
            if reasons:
                status, profile = "profile_out_of_limits", None
        if not await _still_owned(session, job, owner, attempt, lock=True):
            log.warning("cad_lease_lost_before_publish", job_id=str(job.id))
            return job
    except CadError as failure:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        return await _fail(session, job, failure)
    finally:
        if attempt_dir is not None:
            shutil.rmtree(attempt_dir, ignore_errors=True)

    raw_source = job.payload.get("scale_source")
    scale_source = (
        raw_source
        if raw_source in (cad_style_preview.SCALE_CALIBRATION, cad_style_preview.SCALE_CAD_AUTO)
        else cad_style_preview.SCALE_NONE
    )
    result = {
        "result_status": status,
        "attempt": attempt,
        "profile": profile,
        "preview": preview,
        "base_version": base_version,
        "engine_version": cad_service.ENGINE_VERSION,
        "mm_per_pt": mm_per_pt,
        "scale_source": scale_source,
        "revision_id": str(revision.id),
        "page_index": page_index,
        "reasons": reasons,
    }
    log.info("cad_style_preview_finished", job_id=str(job.id), result=status)
    job.payload = cad_progress.finish_attempt(
        job.payload, attempt, cad_progress.now(), outcome="succeeded", result_status=status
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
