"""Тело задания `cad_pdf_convert`: PDF ревизии -> runner движка -> проверка -> хранилище.

Движок не импортируется: он работает подпроцессом своего интерпретатора (`-I`, пустое
окружение, новая группа процессов, предел времени). Артефакты загружаются только после того,
как каждый файл `out/` совпал с `manifest.json`; неудачная попытка в хранилище ничего не
оставляет. Каталог попытки создаётся заново и удаляется в конце при любом исходе.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import signal
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_progress
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

# Коды возврата runner (tools/cad_engine/quantor_cad_runner.py).
_EXIT_CODES: dict[int, ErrorCode] = {
    1: ErrorCode.CAD_ENGINE_FAILED,
    2: ErrorCode.CAD_INPUT_INVALID,
    3: ErrorCode.CAD_PARAMS_INVALID,
    4: ErrorCode.CAD_INPUT_LIMIT_EXCEEDED,
    5: ErrorCode.CAD_ENGINE_UNAVAILABLE,
}
# Запас поверх предела runner: он сам убивает worker и пишет отчёт; это — страховка.
_GRACE_SECONDS = 60
_CHUNK = 1024 * 1024
# Как часто исполнитель переносит снимок хода runner в задание. Аренда сверяется реже.
_PROGRESS_TICK_SECONDS = 1.0
_LEASE_CHECK_SECONDS = 5.0


class CadError(Exception):
    def __init__(self, code: ErrorCode, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail or {}


@dataclass(frozen=True, slots=True)
class EngineCommand:
    python: Path
    runner: Path
    archive: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> EngineCommand:
        paths = (
            settings.cad_engine_python,
            settings.cad_engine_runner,
            settings.cad_engine_archive,
        )
        if not all(value.strip() for value in paths):
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "движок CAD не настроен")
        python, runner, archive = (Path(value) for value in paths)
        if not (python.is_file() and runner.is_file() and archive.is_file()):
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "файлы движка CAD не найдены")
        return cls(python=python, runner=runner, archive=archive)

    def argv(self, *args: str) -> list[str]:
        return [
            str(self.python),
            "-I",
            str(self.runner),
            *args,
            "--archive",
            str(self.archive),
            "--expect-archive-sha256",
            cad_service.ENGINE_ARCHIVE_SHA256,
        ]


async def _run(argv: list[str], limit_seconds: float) -> tuple[int, bytes]:
    """Подпроцесс в своей группе: по таймауту убивается вся группа, включая worker движка."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(limit_seconds):
            output, _ = await process.communicate()
    except (TimeoutError, asyncio.CancelledError) as error:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise CadError(ErrorCode.JOB_TIMEOUT, "движок CAD не уложился во время") from None
    return process.returncode if process.returncode is not None else -1, output


async def verify_engine(settings: Settings) -> dict[str, Any]:
    """Проверка установки перед запуском исполнителя: окружение, SHA архива, манифест, файлы."""
    command = EngineCommand.from_settings(settings)
    code, output = await _run(command.argv("verify"), limit_seconds=120)
    if code != 0:
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, output.decode(errors="replace")[-400:])
    result: dict[str, Any] = json.loads(output)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _download(storage: ObjectStorage, revision: DocumentRevision, target: Path) -> None:
    digest = hashlib.sha256()
    try:
        with target.open("xb") as sink:
            async for chunk in storage.iter_stream(revision.storage_key):
                digest.update(chunk)
                sink.write(chunk)
    except ObjectNotFoundError as error:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "исходный PDF ревизии не найден") from error
    except StorageUnavailableError as error:
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    if digest.hexdigest() != revision.source_sha256:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "SHA256 исходного PDF не совпал с ревизией")


def _verified_outputs(
    out: Path, revision: DocumentRevision, params_sha: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Сверяет out/ с manifest.json и гейтами контракта. Возвращает отчёт и список файлов."""
    try:
        manifest = json.loads((out / "manifest.json").read_bytes())
        report = json.loads((out / "report.json").read_bytes())
    except (OSError, ValueError) as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "нет report.json/manifest.json") from error
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    listed = {row["name"]: row for row in manifest.get("files", [])}
    if present - {"manifest.json"} != set(listed):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с манифестом")
    engine = manifest.get("engine") or {}
    if (
        engine.get("archive_sha256") != cad_service.ENGINE_ARCHIVE_SHA256
        or engine.get("version") != cad_service.ENGINE_VERSION
        or (manifest.get("input") or {}).get("sha256") != revision.source_sha256
        or manifest.get("params_sha256") != params_sha
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "манифест не относится к этому заданию")
    files: list[dict[str, Any]] = []
    for name in sorted(present):
        path = out / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(out.resolve())
            or not cad_service.ARTIFACT_NAME.fullmatch(name)
        ):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "runner выдал файл вне контракта")
        entry = {"name": name, "sha256": _sha256(path), "size": path.stat().st_size}
        if name != "manifest.json" and (
            listed[name]["sha256"] != entry["sha256"] or listed[name]["size"] != entry["size"]
        ):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "SHA256 файла не совпал с манифестом")
        files.append(entry)
    status = report.get("status")
    dxf_count = sum(1 for row in files if row["name"].endswith(".dxf"))
    if (
        status not in cad_service.RESULT_STATUSES
        or (status == cad_service.RESULT_WITH_CAD) != (dxf_count > 0)
        or not {"finishes", "schedules"} <= set(report.get("disabled") or [])
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "статус отчёта не согласован с файлами")
    return report, files


def _page_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page in report.get("pages", []):
        views = [
            {
                "view": view["view"],
                "status": view["status"],
                "scale_status": view.get("scale_status"),
                "dxf": (view.get("dxf") or {}).get("file"),
                "dxf_entities": (view.get("dxf") or {}).get("entities"),
            }
            for view in page.get("views", [])
        ]
        pages.append(
            {"index": page["index"], "legacy_pdf_page": page["legacy_pdf_page"], "views": views}
        )
    return pages


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            yield chunk


async def _upload(
    storage: ObjectStorage,
    job: Job,
    revision_id: uuid.UUID,
    attempt: int,
    out: Path,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    uploaded: list[dict[str, Any]] = []
    try:
        for row in files:
            key = cad_service.artifact_storage_key(revision_id, job.id, attempt, row["name"])
            uploaded.append({**row, "key": key})
            stored = await storage.put_stream(
                key,
                _file_chunks(out / row["name"]),
                content_type=cad_service.content_type_for(row["name"]),
                metadata={"sha256": row["sha256"], "job-id": str(job.id)},
            )
            if stored.sha256 != row["sha256"] or stored.size != row["size"]:
                raise CadError(ErrorCode.CAD_ENGINE_FAILED, "хранилище получило другой файл")
    except StorageUnavailableError as error:
        await _discard(storage, uploaded)
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    except (CadError, asyncio.CancelledError):
        await _discard(storage, uploaded)
        raise
    return uploaded


async def _discard(storage: ObjectStorage, uploaded: list[dict[str, Any]]) -> None:
    for row in uploaded:
        with contextlib.suppress(Exception):
            await storage.delete(row["key"])


async def _still_owned(
    session: AsyncSession, job: Job, owner: str | None, attempt: int, *, lock: bool = False
) -> bool:
    """Проверяет аренду. Перед записью результата удерживает блокировку строки до commit."""
    await session.refresh(job, with_for_update=lock)
    return (
        owner is not None
        and job.status is JobStatus.RUNNING
        and job.worker_id == owner
        and job.attempt == attempt
        and job.lease_expires_at is not None
        and job.lease_expires_at > datetime.now(UTC)
    )


async def _sync_progress(
    session: AsyncSession, job: Job, attempt: int, progress_path: Path | None
) -> None:
    """Переносит свежий снимок runner в задание. Вызывается, пока аренда наша."""
    if progress_path is None:
        return
    try:
        raw = await asyncio.to_thread(progress_path.read_bytes)
    except OSError:
        return
    snapshot = cad_progress.parse_snapshot(raw)
    if snapshot is None:
        return
    payload, added = cad_progress.apply_snapshot(job.payload, attempt, snapshot, cad_progress.now())
    if added:
        job.payload = payload


async def _run_while_owned(
    session: AsyncSession,
    job: Job,
    owner: str | None,
    attempt: int,
    argv: list[str],
    limit_seconds: float,
    poll_interval: float,
    progress_path: Path | None = None,
) -> tuple[int, bytes] | None:
    running = asyncio.create_task(_run(argv, limit_seconds))
    loop = asyncio.get_running_loop()
    next_lease_check = loop.time()
    lease_every = min(_LEASE_CHECK_SECONDS, poll_interval)
    try:
        while True:
            done, _ = await asyncio.wait({running}, timeout=_PROGRESS_TICK_SECONDS)
            if done:
                return await running
            if loop.time() >= next_lease_check:
                next_lease_check = loop.time() + lease_every
                if not await _still_owned(session, job, owner, attempt):
                    return None
            await _sync_progress(session, job, attempt, progress_path)
            await session.commit()
    finally:
        if not running.done():
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running


async def execute_cad_pdf_convert(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    revision_id = job.payload.get("revision_id")
    params = job.payload.get("params")
    revision = (
        await session.get(DocumentRevision, uuid.UUID(revision_id))
        if isinstance(revision_id, str)
        else None
    )
    if revision is None or not isinstance(params, dict):
        return await _fail(session, job, CadError(ErrorCode.CAD_PARAMS_INVALID, "нет ревизии"))

    owner, attempt = job.worker_id, job.attempt
    await jobs_service.start(session, job=job, stage="cad_engine")
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
        source = attempt_dir / "in" / "source.pdf"
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "Исходный PDF ревизии: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
        await _download(storage, revision, source)
        raw_params = cad_service.params_bytes(params)
        if hashlib.sha256(raw_params).hexdigest() != job.payload.get("params_sha256"):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "параметры задания изменены")
        (attempt_dir / "in" / "params.json").write_bytes(raw_params)
        out = attempt_dir / "out"
        # Снимок хода — вне out/ и work/: runner требует их пустыми, а манифест — только out/.
        progress_path = attempt_dir / "progress.json"
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            command.argv(
                "run",
                "--input",
                str(source),
                "--params",
                str(attempt_dir / "in" / "params.json"),
                "--work",
                str(attempt_dir / "work"),
                "--out",
                str(out),
                "--progress",
                str(progress_path),
            ),
            limit_seconds=float(settings.cad_total_timeout_seconds + _GRACE_SECONDS),
            poll_interval=settings.worker_heartbeat_interval_seconds,
            progress_path=progress_path,
        )
        if outcome is None:
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        code, _ = outcome
        # Последний снимок: финальные этапы видов, записанные уже после последнего опроса.
        if await _still_owned(session, job, owner, attempt):
            await _sync_progress(session, job, attempt, progress_path)
            await session.commit()
        if code != 0:
            raise _failure_from_report(out, code)
        report, files = _verified_outputs(out, revision, str(job.payload["params_sha256"]))
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "publish",
            f"Манифест сверен, загрузка файлов попытки: {len(files)}",
            cad_progress.now(),
        )
        await session.commit()
        artifacts = await _upload(storage, job, revision.id, attempt, out, files)
        if not await _still_owned(session, job, owner, attempt, lock=True):
            await _discard(storage, artifacts)
            log.warning("cad_lease_lost_before_publish", job_id=str(job.id))
            return job
    except CadError as failure:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        return await _fail(session, job, failure)
    finally:
        if attempt_dir is not None:
            shutil.rmtree(attempt_dir, ignore_errors=True)

    result = {
        "result_status": report["status"],
        "review_required": True,
        "engine_version": cad_service.ENGINE_VERSION,
        "engine_archive_sha256": cad_service.ENGINE_ARCHIVE_SHA256,
        "runner_sha256": (report.get("runner") or {}).get("sha256"),
        "input_sha256": revision.source_sha256,
        "params_sha256": job.payload["params_sha256"],
        "attempt": attempt,
        "dxf_count": sum(1 for row in artifacts if row["name"].endswith(".dxf")),
        "pages": _page_summary(report),
        "artifacts": artifacts,
    }
    log.info("cad_convert_finished", job_id=str(job.id), result=report["status"])
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=str(report["status"]),
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})


def _failure_from_report(out: Path, code: int) -> CadError:
    try:
        report = json.loads((out / "report.json").read_bytes())
    except (OSError, ValueError):
        return CadError(ErrorCode.CAD_ENGINE_FAILED, f"runner завершился кодом {code} без отчёта")
    error = report.get("error") or {}
    mapped = _EXIT_CODES.get(code, ErrorCode.CAD_ENGINE_FAILED)
    if code == 4 and error.get("code") == "timeout":
        mapped = ErrorCode.JOB_TIMEOUT
    detail = {
        "engine_error": error.get("code"),
        "known_limitation": error.get("known_limitation"),
        # Этапы видов неудачной попытки: где именно остановился движок. DXF здесь нет никогда.
        "pages": _page_summary(report),
    }
    message = str(error.get("message") or mapped.value)
    if detail["known_limitation"]:
        message = f"{message} (известное ограничение: {detail['known_limitation']})"
    return CadError(mapped, message, detail)


async def _fail(session: AsyncSession, job: Job, failure: CadError) -> Job:
    log.warning("cad_convert_failed", job_id=str(job.id), code=failure.code.value)
    attempt = job.attempt
    payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="failed",
        error_code=failure.code.value,
        result_status="failed",
    )
    job.payload = {
        **payload,
        "cad_result": {
            "result_status": "failed",
            "error_code": failure.code.value,
            "attempt": attempt,
            **failure.detail,
        },
    }
    return await jobs_service.fail(
        session, job=job, error_code=failure.code.value, error_message=failure.message
    )
