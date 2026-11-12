"""Тело задания `cad_sections`: исходный PDF ревизии -> CLI cad_mep/run_sections.py -> уровни.

CLI не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти):

    <python> -I run_sections.py --pdf [--pages i j ...] --params --out

`--out` - файл `sections.json` (схема `cad_sections.v2`). Код выхода 2 - ошибка входа, причина -
одной строкой JSON `{"code", "message"}` в stderr. Общие части (аренда, загрузка, отказ задания) -
из `handler`. Параметры и версия - пин генератора `cad_mep` (отдельного пина у разрезов нет).

Результат публикуется одной транзакцией с успехом задания: артефакт `sections.json` и строки
`cad_section_levels` (прежние строки ревизии заменяются, решения переносятся). Ошибка генератора
или файл вне контракта - задание failed, ничего не публикуется.
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
from app.contracts.cad_sections import SectionsFile
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobType
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_progress, cad_sections
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)


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
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "страницы разрезов заданы неверно")
    return [int(item) for item in raw]


def _argv(
    settings: Settings, *, source: Path, params: Path, out: Path, pages: list[int] | None
) -> list[str]:
    python, runner = settings.cad_engine_python.strip(), cad_sections.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "генератор разрезов не настроен")
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


def _verified_output(
    out: Path, revision: DocumentRevision, pages: list[int] | None
) -> tuple[list[dict[str, Any]], SectionsFile]:
    """В out/ строго один файл; схема, sha256 PDF и страницы совпадают с заданием."""
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if present != {cad_sections.SECTIONS_JSON}:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом CLI")
    path = out / cad_sections.SECTIONS_JSON
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "CLI выдал файл вне контракта")
    if path.stat().st_size > cad_service.MAX_JSON_ARTIFACT_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "sections.json больше допустимого размера")
    raw = _read_json_file(path)
    if raw.get("schema") != cad_sections.SECTIONS_SCHEMA:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "sections.json вне контракта")
    try:
        document = SectionsFile.model_validate(raw)
    except ValidationError as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "sections.json вне контракта") from error
    if document.source.pdf_sha256 != revision.source_sha256:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "sections.json относится к другому PDF")
    if pages is not None and any(item.page_index not in pages for item in document.sections):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "sections.json содержит страницы вне задания")
    return [{"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}], document


async def execute_cad_sections(
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
    await jobs_service.start(session, job=job, stage=JobType.CAD_SECTIONS.value)
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
        params = cad_mep_service.load_params(settings)
        raw_params = params.path.read_bytes()
        if (
            params.sha256 != job.payload.get("params_sha256")
            or params.generator_version != job.payload.get("generator_version")
            or cad_service.params_sha256(json.loads(raw_params)) != params.sha256
        ):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "параметры или версия генератора изменены")
        params_file = attempt_dir / "in" / "params.json"
        params_file.write_bytes(raw_params)

        out = attempt_dir / "out"
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "worker",
            "Распознавание разрезов по тексту PDF",
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
                out=out / cad_sections.SECTIONS_JSON,
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
            raise _generator_failure(code, output)
        files, document = _verified_output(out, revision, pages)
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "publish", "sections.json сверен, загрузка", cad_progress.now()
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

    # Строка задания под блокировкой: строки уровней и успех - одной транзакцией.
    levels = await cad_sections.publish_levels(
        session,
        job=job,
        workspace_id=workspace_id,
        project_id=project_id,
        revision_id=revision.id,
        document=document,
    )
    result = {
        "result_status": cad_sections.RESULT_READY,
        "attempt": attempt,
        "generator_version": job.payload.get("generator_version"),
        "params_sha256": job.payload.get("params_sha256"),
        "input_sha256": revision.source_sha256,
        "sections_sha256": files[0]["sha256"],
        "page_indexes": pages,
        "counts": {
            "pages": len(document.sections),
            "levels": levels,
            "issues": len(document.issues),
        },
        "artifacts": artifacts,
    }
    log.info("cad_sections_finished", job_id=str(job.id), levels=levels)
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=cad_sections.RESULT_READY,
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
