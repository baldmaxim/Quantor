"""Тело задания `cad_facades`: исходный PDF ревизии -> run_facades.py -> виды (ADR-0048).

CLI не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти):

    <python> -I run_facades.py --pdf [--pages i j ...] --params --out

`--out` - файл `facades.json` (схема `cad_facades.v1`). Код выхода 2 - ошибка входа, причина -
одной строкой JSON `{"code", "message"}` в stderr; `facades_not_found` - в PDF нет видов фасада с
заголовком. Общие части (аренда, загрузка, отказ задания) - из `handler`. Параметры и версия -
пин генератора `cad_facades` из pins.json.

Результат публикуется одной транзакцией с успехом задания: артефакт `facades.json` и строки
`cad_facade_views` (прежние строки ревизии заменяются, решения переносятся). Ошибка генератора или
файл вне контракта - задание failed, ничего не публикуется.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import (
    CadError,
    _discard,
    _download,
    _fail,
    _run_while_owned,
    _sha256,
    _still_owned,
    _upload,
)
from app.cad_worker.mep_handler import _generator_failure, _read_json_file
from app.contracts.cad_facades import FACADES_SCHEMA, FacadesFile
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobType
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_facades, cad_progress
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)

NOT_FOUND_MESSAGE = "В PDF не найдено видов фасада с заголовком"


def _requested_pages(job: Job) -> list[int] | None:
    """Страницы из задания: `None` - все; иное, чем список неотрицательных int, - отказ."""
    raw = job.payload.get("page_indexes")
    if raw is None:
        return None
    if (
        not isinstance(raw, list)
        or not raw
        or not all(type(item) is int and item >= 0 for item in raw)
        or len(set(raw)) != len(raw)
    ):
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "страницы фасадов заданы неверно")
    return [int(item) for item in raw]


def _argv(
    settings: Settings, *, source: Path, params: Path, out: Path, pages: list[int] | None
) -> list[str]:
    python, runner = settings.cad_engine_python.strip(), cad_facades.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "генератор фасадов не настроен")
    return [
        python,
        "-I",
        str(runner),
        "--pdf",
        str(source),
        *(["--pages", *(str(index) for index in pages)] if pages else []),
        "--params",
        str(params),
        "--out",
        str(out),
    ]


def _failure(code: int, output: bytes) -> CadError:
    """Отказ генератора; `facades_not_found` получает понятный текст вместо английского."""
    failure = _generator_failure(code, output)
    if failure.detail.get("generator_error") == "facades_not_found":
        return CadError(failure.code, NOT_FOUND_MESSAGE, failure.detail)
    return failure


def _has_nul(value: object) -> bool:
    """Символ `\u0000` в любой строке (в том числе в ключах) - PostgreSQL его не принимает."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, list):
        return any(_has_nul(item) for item in value)
    if isinstance(value, dict):
        return any(_has_nul(key) or _has_nul(item) for key, item in value.items())
    return False


def _verified_output(
    out: Path, revision: DocumentRevision, pages: list[int] | None, generator_version: object
) -> tuple[list[dict[str, Any]], FacadesFile]:
    """В out/ строго один файл; схема, sha256 PDF и страницы совпадают с заданием."""
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if present != {cad_facades.FACADES_JSON}:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом CLI")
    path = out / cad_facades.FACADES_JSON
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "CLI выдал файл вне контракта")
    if path.stat().st_size > cad_service.MAX_JSON_ARTIFACT_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json больше допустимого размера")
    raw = _read_json_file(path)
    if raw.get("schema") != FACADES_SCHEMA or _has_nul(raw):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json вне контракта")
    try:
        document = FacadesFile.model_validate(raw)
    except ValidationError as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json вне контракта") from error
    if document.generator_version != generator_version:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json выдан другой версией генератора")
    if document.source.pdf_sha256 != revision.source_sha256:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json относится к другому PDF")
    if pages is not None and any(item.page_index not in pages for item in document.views):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "facades.json содержит страницы вне задания")
    return [{"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}], document


async def execute_cad_facades(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    revision_id = job.payload.get("revision_id")
    revision = (
        await session.get(DocumentRevision, uuid.UUID(revision_id))
        if isinstance(revision_id, str)
        else None
    )
    if revision is None or job.workspace_id is None or job.project_id is None:
        return await _fail(session, job, CadError(ErrorCode.CAD_PARAMS_INVALID, "нет ревизии"))
    workspace_id, project_id = job.workspace_id, job.project_id

    owner, attempt = job.worker_id, job.attempt
    await jobs_service.start(session, job=job, stage=JobType.CAD_FACADES.value)
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        pages = _requested_pages(job)
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "out"):
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

        # Пин сверяется с заданием: образ исполнителя не должен разойтись с тем, что поставил API.
        try:
            params = cad_facades.load_params(settings)
        except DomainError as error:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, error.detail) from error
        try:
            raw_params = params.path.read_bytes()
            params_valid = cad_service.params_sha256(json.loads(raw_params)) == params.sha256
        except OSError as error:
            raise CadError(
                ErrorCode.CAD_ENGINE_UNAVAILABLE, "параметры генератора фасадов не читаются"
            ) from error
        except ValueError as error:
            raise CadError(
                ErrorCode.CAD_PARAMS_INVALID, "параметры генератора фасадов не разобраны"
            ) from error
        if (
            not params_valid
            or params.sha256 != job.payload.get("params_sha256")
            or params.generator_version != job.payload.get("generator_version")
        ):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "параметры или версия генератора изменены")
        params_file = attempt_dir / "in" / "params.json"
        params_file.write_bytes(raw_params)

        out = attempt_dir / "out"
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "worker",
            "Распознавание видов фасадов по векторам и тексту PDF",
            cad_progress.now(),
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            _argv(
                settings,
                source=pdf,
                params=params_file,
                out=out / cad_facades.FACADES_JSON,
                pages=pages,
            ),
            limit_seconds=float(settings.cad_total_timeout_seconds),
            poll_interval=settings.worker_heartbeat_interval_seconds,
            memory_limit_mb=settings.cad_max_memory_mb,
        )
        if outcome is None:
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        code, output = outcome
        if code != 0:
            raise _failure(code, output)
        files, document = _verified_output(
            out, revision, pages, job.payload.get("generator_version")
        )
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "publish", "facades.json сверен, загрузка", cad_progress.now()
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

    # Строка задания под блокировкой: строки видов и успех - одной транзакцией.
    views = await cad_facades.publish_views(
        session,
        job=job,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision.id,
        document=document,
    )
    windows = sum(len(view.windows) for view in document.views)
    result = {
        "result_status": cad_facades.RESULT_READY,
        "attempt": attempt,
        "generator_version": job.payload.get("generator_version"),
        "params_sha256": job.payload.get("params_sha256"),
        "input_sha256": revision.source_sha256,
        "facades_sha256": files[0]["sha256"],
        "page_indexes": pages,
        "counts": {"views": views, "windows": windows, "issues": len(document.issues)},
        "artifacts": artifacts,
    }
    log.info("cad_facades_finished", job_id=str(job.id), views=views, windows=windows)
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=cad_facades.RESULT_READY,
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
