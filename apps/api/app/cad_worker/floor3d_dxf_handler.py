"""Тело задания `cad_floor3d_dxf`: модель этажа -> скрипт cad_walls -> DXF -> хранилище.

Скрипт не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти) по CLI-контракту:

    <python> -I run_floor3d_dxf.py --model --out

Скрипт лежит рядом со скриптом конструкций (тот же каталог `cad_walls` в `CAD_GENERATORS_ROOT`
репозитория движка), отдельной настройки пути нет. Код выхода 2 - ошибка входа, причина -
одной строкой JSON `{"code", "message"}` в выводе. Общие части (аренда, загрузка, отказ
задания) - из `handler`.

Вход проверяется до запуска: родитель `cad_pdf_convert` успешен, модель из хранилища сверяется по
sha256 с заданием. Результат проверяется после: в `out/` строго один DXF вида, версия скрипта и
sha256 модели и файла в сводке скрипта - те же, что у задания и у файла.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import (
    CadError,
    _discard,
    _fail,
    _run_while_owned,
    _sha256,
    _still_owned,
    _upload,
)
from app.cad_worker.mep_handler import _generator_failure
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_floor3d_dxf as floor3d_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_pins, cad_progress
from app.services import cad_walls as cad_walls_service
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

RESULT_READY: Final = "floor3d_dxf_ready"
SCRIPT_NAME: Final = "run_floor3d_dxf.py"
MODEL_FILE: Final = "floor3d_model.json"
# Предел входной модели и выходного файла: разумный потолок, а не расчётная величина.
MAX_MODEL_BYTES: Final = 32 * 1024 * 1024
MAX_DXF_BYTES: Final = 512 * 1024 * 1024


class _Input:
    """Проверенный вход задания: родитель, страница и вид."""

    def __init__(self, parent: Job, page_index: int, view: int) -> None:
        self.parent, self.page_index, self.view = parent, page_index, view


def _argv(settings: Settings, *, model: Path, out: Path) -> list[str]:
    python = settings.cad_engine_python.strip()
    walls_runner = cad_walls_service.runner_path(settings)
    runner = walls_runner.with_name(SCRIPT_NAME) if walls_runner is not None else None
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "скрипт выгрузки 3D DXF не настроен")
    return [python, "-I", str(runner), "--model", str(model), "--out", str(out)]


async def _checked_input(session: AsyncSession, job: Job, settings: Settings) -> _Input:
    payload = job.payload
    try:
        parent_id = uuid.UUID(str(payload.get("parent_job_id")))
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание 3D DXF заполнено неверно") from error
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    parent_attempt = cad_mep_service.payload_int(job, "parent_attempt")
    sha256, size = payload.get("model_sha256"), cad_mep_service.payload_int(job, "model_size")
    if (
        page_index is None
        or view is None
        or parent_attempt is None
        or not isinstance(sha256, str)
        or size is None
    ):
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание 3D DXF заполнено не полностью")
    try:
        current_version = cad_pins.floor3d_dxf_version(settings)
    except DomainError as error:
        raise CadError(
            ErrorCode.CAD_ENGINE_UNAVAILABLE, "версия скрипта 3D DXF не закреплена"
        ) from error
    if payload.get("generator_version") != current_version:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "версия скрипта 3D DXF изменилась")
    parent = await session.get(Job, parent_id)
    if (
        parent is None
        or parent.job_type is not JobType.CAD_PDF_CONVERT
        or parent.workspace_id != job.workspace_id
        or parent.project_id != job.project_id
        or parent.payload.get("revision_id") != payload.get("revision_id")
        or parent.status is not JobStatus.SUCCEEDED
        or cad_service.result_of(parent).get("attempt") != parent_attempt
        or cad_walls_service.view_has_dxf(parent, page_index, view) is None
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "результат родителя недоступен для 3D DXF")
    return _Input(parent, page_index, view)


async def _download_model(
    storage: ObjectStorage, revision_id: uuid.UUID, sha256: str, size: int, target: Path
) -> None:
    """Модель этажа из хранилища в файл попытки; sha256 и размер сверяются с заданием."""
    if size > MAX_MODEL_BYTES:
        raise CadError(ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, "модель этажа больше допустимого")
    key = floor3d_service.input_key(revision_id, sha256)
    digest, received = hashlib.sha256(), 0
    try:
        with target.open("xb") as sink:
            async for chunk in storage.iter_stream(key):
                received += len(chunk)
                if received > MAX_MODEL_BYTES:
                    raise CadError(
                        ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, "модель этажа больше допустимого"
                    )
                digest.update(chunk)
                sink.write(chunk)
    except ObjectNotFoundError as error:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "модель этажа не найдена") from error
    except StorageUnavailableError as error:
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    if digest.hexdigest() != sha256 or received != size:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "модель этажа не совпала с заданием")


def _summary_of(output: bytes) -> dict[str, Any]:
    """Сводка скрипта: последняя строка вывода, которая разбирается как объект JSON."""
    for line in reversed(output.decode(errors="replace").strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "generator" in value:
            return value
    raise CadError(ErrorCode.CAD_ENGINE_FAILED, "скрипт 3D DXF не выдал сводку")


def _verified_output(
    out: Path, name: str, job: Job, summary: dict[str, Any]
) -> list[dict[str, Any]]:
    """В out/ строго один DXF вида; версия скрипта, sha256 модели и файла совпадают с заданием."""
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if present != {name}:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом скрипта")
    path = out / name
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "скрипт выдал файл вне контракта")
    size = path.stat().st_size
    if size == 0 or size > MAX_DXF_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "DXF пуст или больше допустимого размера")
    sha256 = _sha256(path)
    if (
        summary.get("generator") != job.payload.get("generator_version")
        or summary.get("model_sha256") != job.payload.get("model_sha256")
        or summary.get("dxf_sha256") != sha256
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "3D DXF не относится к этому заданию")
    return [{"name": name, "sha256": sha256, "size": size}]


async def execute_cad_floor3d_dxf(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    revision_id = job.payload.get("revision_id")
    revision = (
        await session.get(DocumentRevision, uuid.UUID(revision_id))
        if isinstance(revision_id, str)
        else None
    )
    if revision is None:
        return await _fail(session, job, CadError(ErrorCode.CAD_PARAMS_INVALID, "нет ревизии"))

    owner, attempt = job.worker_id, job.attempt
    await jobs_service.start(session, job=job, stage="cad_floor3d_dxf")
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        source = await _checked_input(session, job, settings)
        name = floor3d_service.output_name(source.page_index, source.view)
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "out"):
            (attempt_dir / sub).mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "Модель этажа: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
        model = attempt_dir / "in" / MODEL_FILE
        await _download_model(
            storage,
            revision.id,
            str(job.payload["model_sha256"]),
            int(job.payload["model_size"]),
            model,
        )

        out = attempt_dir / "out"
        dxf_file = out / name
        dxf_file.parent.mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "worker", "Выгрузка 3D DXF этажа", cad_progress.now()
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            _argv(settings, model=model, out=dxf_file),
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
        summary = _summary_of(output)
        files = _verified_output(out, name, job, summary)
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "publish", "3D DXF сверен, загрузка", cad_progress.now()
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
        "result_status": RESULT_READY,
        "attempt": attempt,
        "generator_version": job.payload["generator_version"],
        "model_sha256": job.payload["model_sha256"],
        "dxf_sha256": files[0]["sha256"],
        "input_sha256": revision.source_sha256,
        "parent_job_id": str(source.parent.id),
        "page_index": source.page_index,
        "view": source.view,
        "counts": {
            "meshes": summary.get("meshes", {}),
            "outlines": summary.get("outlines", 0),
            "skipped": len(summary.get("skipped", [])),
            "triangulation_mismatch": len(summary.get("triangulation_mismatch", [])),
        },
        "artifacts": artifacts,
    }
    log.info("cad_floor3d_dxf_finished", job_id=str(job.id))
    job.payload = cad_progress.finish_attempt(
        job.payload, attempt, cad_progress.now(), outcome="succeeded", result_status=RESULT_READY
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
