"""Тело задания `cad_walls`: DXF вида -> скрипт cad_walls -> проверка walls.json -> хранилище.

Скрипт не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти) по CLI-контракту:

    <python> -I run_walls.py --dxf --params --out --pdf --page [--zones]

PDF ревизии и номер страницы нужны только разбору отметок этажа (как у генератора трасс); не
определились — скрипт пишет в `heights` статус `missing`, и это не отказ. Зоны помещений листа
(`--zones`, мм DXF) берутся из входного объекта хранилища, адресованного sha256 из задания; в
задании их нет — контур плиты строится по стенам. Код выхода 2 — ошибка
входа, причина — одной строкой JSON `{"code", "message"}` в stderr. Общие части (аренда,
загрузка, отказ задания) — из `handler`.

Вход проверяется до запуска: родитель `cad_pdf_convert` успешен, DXF вида сверяется по sha256 с
итогом родителя и с заданием, параметры и версия скрипта не изменились. Результат проверяется
после: схема `quantor.cad_walls.v1`, версия скрипта, sha256 параметров и DXF — те же, что у задания.
"""

from __future__ import annotations

import asyncio
import hashlib
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
from app.cad_worker.mep_handler import _download_artifact, _generator_failure, _read_json_file
from app.contracts.cad_constructions import WALLS_SCHEMA, WallsDocument
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_progress, cad_walls_zones
from app.services import cad_walls as cad_walls_service
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

RESULT_READY = "walls_ready"


class _Input:
    """Проверенный вход задания: родитель и вид."""

    def __init__(self, parent: Job, folder: str, page_index: int, view: int) -> None:
        self.parent, self.folder = parent, folder
        self.page_index, self.view = page_index, view


def _argv(
    settings: Settings,
    *,
    dxf: Path,
    params: Path,
    out: Path,
    pdf: Path,
    page_index: int,
    zones: Path | None = None,
) -> list[str]:
    python, runner = settings.cad_engine_python.strip(), cad_walls_service.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "скрипт подсчёта конструкций не настроен")
    argv = [
        python,
        "-I",
        str(runner),
        "--dxf",
        str(dxf),
        "--params",
        str(params),
        "--out",
        str(out),
        "--pdf",
        str(pdf),
        "--page",
        str(page_index),
    ]
    if zones is not None:
        argv += ["--zones", str(zones)]
    return argv


async def _download_zones(
    storage: ObjectStorage, revision_id: uuid.UUID, sha256: str, size: int, target: Path
) -> None:
    """Зоны помещений из хранилища в файл попытки; sha256 и размер сверяются с заданием."""
    if size > cad_walls_zones.MAX_ZONES_BYTES:
        raise CadError(ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, "зоны листа больше допустимого")
    digest, received = hashlib.sha256(), 0
    try:
        with target.open("xb") as sink:
            async for chunk in storage.iter_stream(cad_walls_zones.input_key(revision_id, sha256)):
                received += len(chunk)
                if received > cad_walls_zones.MAX_ZONES_BYTES:
                    raise CadError(
                        ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, "зоны листа больше допустимого"
                    )
                digest.update(chunk)
                sink.write(chunk)
    except ObjectNotFoundError as error:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "зоны листа не найдены") from error
    except StorageUnavailableError as error:
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    if digest.hexdigest() != sha256 or received != size:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "зоны листа не совпали с заданием")


async def _checked_input(session: AsyncSession, job: Job) -> _Input:
    payload = job.payload
    try:
        parent_id = uuid.UUID(str(payload.get("parent_job_id")))
    except ValueError as error:
        raise CadError(
            ErrorCode.CAD_PARAMS_INVALID, "задание конструкций заполнено неверно"
        ) from error
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    parent_attempt = cad_mep_service.payload_int(job, "parent_attempt")
    if page_index is None or view is None or parent_attempt is None:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание конструкций заполнено не полностью")
    parent = await session.get(Job, parent_id)
    if (
        parent is None
        or parent.job_type is not JobType.CAD_PDF_CONVERT
        or parent.workspace_id != job.workspace_id
        or parent.project_id != job.project_id
        or parent.payload.get("revision_id") != payload.get("revision_id")
        or parent.status is not JobStatus.SUCCEEDED
        or cad_service.result_of(parent).get("attempt") != parent_attempt
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "результат родителя недоступен для конструкций")
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "вид задан неверно") from error
    dxf = cad_service.find_artifact(parent, f"{folder}/plan_candidates.dxf")
    if dxf is None or dxf.get("sha256") != payload.get("view_dxf_sha256"):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "DXF вида не совпал с заданием")
    return _Input(parent, folder, page_index, view)


def _verified_output(
    out: Path, source: _Input, job: Job, params: cad_walls_service.WallsParams, dxf_sha256: str
) -> tuple[list[dict[str, Any]], WallsDocument]:
    """В out/ строго один файл вида; схема, версии и sha256 совпадают с заданием."""
    name = f"{source.folder}/{cad_walls_service.WALLS_JSON}"
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if present != {name}:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом скрипта")
    path = out / name
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "скрипт выдал файл вне контракта")
    if path.stat().st_size > cad_service.MAX_JSON_ARTIFACT_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "walls.json больше допустимого размера")
    raw = _read_json_file(path)
    if (
        raw.get("schema") != WALLS_SCHEMA
        or raw.get("units") != "mm"
        or raw.get("generator") != params.generator_version
        or raw.get("params_version") != params.params_version
        or raw.get("params_sha256") != params.sha256
        or raw.get("dxf_sha256") != dxf_sha256
        or job.payload.get("view_dxf_sha256") != dxf_sha256
    ):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "walls.json не относится к этому заданию")
    try:
        document = WallsDocument.model_validate(raw)
    except ValidationError as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "walls.json вне контракта") from error
    ids = [c.id for c in [*document.constructions, *document.frame_partitions]]
    if len(set(ids)) != len(ids):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "в walls.json повторяются id конструкций")
    return [{"name": name, "sha256": _sha256(path), "size": path.stat().st_size}], document


async def execute_cad_walls(
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
    await jobs_service.start(session, job=job, stage="cad_walls")
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        source = await _checked_input(session, job)
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "out"):
            (attempt_dir / sub).mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "DXF вида и исходный PDF: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
        pdf = attempt_dir / "in" / "source.pdf"
        dxf = attempt_dir / "in" / "plan_candidates.dxf"
        await _download(storage, revision, pdf)
        await _download_artifact(
            storage,
            source.parent,
            revision.id,
            f"{source.folder}/plan_candidates.dxf",
            str(job.payload["view_dxf_sha256"]),
            dxf,
        )

        params = cad_walls_service.load_params(settings)
        raw_params = params.path.read_bytes()
        if (
            params.sha256 != job.payload.get("params_sha256")
            or params.generator_version != job.payload.get("generator_version")
            or params.params_version != job.payload.get("params_version")
            or cad_service.params_sha256(json.loads(raw_params)) != params.sha256
        ):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "параметры или версия скрипта изменены")
        # Имя копии = имя исходного файла: версию параметров скрипт берёт из него.
        params_file = attempt_dir / "in" / params.path.name
        params_file.write_bytes(raw_params)

        zones_file: Path | None = None
        zones_sha = job.payload.get("zones_sha256")
        if isinstance(zones_sha, str) and zones_sha:
            zones_size = cad_mep_service.payload_int(job, "zones_size")
            if zones_size is None:
                raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание конструкций без размера зон")
            zones_file = attempt_dir / "in" / "zones.json"
            await _download_zones(storage, revision.id, zones_sha, zones_size, zones_file)

        out = attempt_dir / "out"
        walls_file = out / source.folder / cad_walls_service.WALLS_JSON
        walls_file.parent.mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "worker", "Подсчёт конструкций по DXF вида", cad_progress.now()
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            _argv(
                settings,
                dxf=dxf,
                params=params_file,
                out=walls_file,
                pdf=pdf,
                page_index=source.page_index,
                zones=zones_file,
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
        files, document = _verified_output(out, source, job, params, _sha256(dxf))
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "publish", "walls.json сверен, загрузка", cad_progress.now()
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
        "generator": document.generator,
        "generator_version": document.generator,
        "params_version": document.params_version,
        "params_sha256": document.params_sha256,
        "dxf_sha256": document.dxf_sha256,
        "walls_sha256": files[0]["sha256"],
        "zones_count": job.payload.get("zones_count", 0),
        # Заголовок плана для подписей листов: конвейер читает его из итога задания, не из файла.
        "floor_title": (
            None
            if document.heights.title is None
            else document.heights.title.model_dump(mode="json")
        ),
        "input_sha256": revision.source_sha256,
        "parent_job_id": str(source.parent.id),
        "page_index": source.page_index,
        "view": source.view,
        "counts": {
            "constructions": len(document.constructions),
            "openings": len(document.openings),
            "thickness_check": sum(
                1 for c in document.constructions if c.thickness_status == "check"
            ),
            "warnings": len(document.checks.warnings),
        },
        "artifacts": artifacts,
    }
    log.info("cad_walls_finished", job_id=str(job.id))
    job.payload = cad_progress.finish_attempt(
        job.payload, attempt, cad_progress.now(), outcome="succeeded", result_status=RESULT_READY
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
