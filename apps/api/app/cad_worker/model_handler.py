"""Тело задания `model_ifc_import`: IFC проекта -> генератор cad_model -> проверка -> версия модели.

Вход: ревизии IFC из `payload.inputs` (последние ревизии IFC проекта на момент постановки): каждая
сверяется по sha256 с тем, что поставили. Генератор не импортируется: он работает подпроцессом
интерпретатора движка (`-I`, пустое окружение, пределы времени и памяти) по CLI-контракту:

    <python> -I run_model.py --ifc <файл> [--ifc <файл> ...] --params <params.json> --out <каталог>

Коды выхода: 0 - готово; 2 - ошибка входа (IFC не читается); 3 - модель не построена (причина -
одной строкой JSON `{"code", "message"}` в stderr). Выход - пакет QMP v1 (docs/building-model/
07-model-package-qmp-v1.md): `manifest.json` и части. Пакет проверяется тем же модулем, что
принимает пакеты по HTTP (`model_package`), и сохраняется версией модели (кандидат): её
утверждает человек.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import (
    CadError,
    _download,
    _fail,
    _file_chunks,
    _run_while_owned,
    _still_owned,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import ModelVersionStatus
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job
from app.services import building_models as models_service
from app.services import cad as cad_service
from app.services import cad_progress
from app.services import jobs as jobs_service
from app.services import model_import as model_import_service
from app.services import model_package as qmp
from app.storage.base import ObjectStorage

log = get_logger(__name__)

_ERROR_MESSAGE_LIMIT = 400
_UNSAFE = re.compile(r"[^A-Za-z0-9._() -]")


def _local_name(index: int, filename: str) -> str:
    """Имя файла в каталоге попытки: номер и очищенное имя; суффикс имени остаётся целым."""
    stem = _UNSAFE.sub("_", filename.rsplit("/", maxsplit=1)[-1])[-120:]
    return f"{index:02d}_{stem}"


def generator_argv(
    settings: Settings, *, sources: list[Path], params: Path, out: Path
) -> list[str]:
    python = (settings.cad_model_python or settings.cad_engine_python).strip()
    runner = model_import_service.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "генератор модели из IFC не настроен")
    argv = [python, "-I", str(runner)]
    for source in sources:
        argv += ["--ifc", str(source)]
    return [*argv, "--params", str(params), "--out", str(out)]


def generator_failure(code: int, output: bytes) -> CadError:
    """Код выхода генератора -> отказ задания; текст берётся из JSON в конце вывода."""
    tail = output.decode(errors="replace").strip()
    parsed: dict[str, Any] = {}
    for line in reversed(tail.splitlines()):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and "code" in candidate:
            parsed = candidate
            break
    generator_code = str(parsed.get("code") or f"exit_{code}")[:64]
    message = str(parsed.get("message") or tail[-_ERROR_MESSAGE_LIMIT:] or f"код {code}")
    mapped = {2: ErrorCode.CAD_INPUT_INVALID, 3: ErrorCode.MODEL_IFC_NOT_BUILT}.get(
        code, ErrorCode.CAD_ENGINE_FAILED
    )
    return CadError(mapped, message[:_ERROR_MESSAGE_LIMIT], {"generator_error": generator_code})


def checked_package(out: Path) -> tuple[bytes, qmp.Manifest]:
    """Пакет в `out/` проходит ту же проверку, что пакеты по HTTP; ошибка - отказ задания."""
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "генератор не записал manifest.json")
    data = manifest_path.read_bytes()
    report, manifest = qmp.validate_package(data, qmp.DirectoryReader(out))
    if not report.ok or manifest is None:
        first = report.errors[0]
        raise CadError(
            ErrorCode.CAD_ENGINE_FAILED,
            f"пакет модели не прошёл проверку: {first.code} @ {first.where}"[:_ERROR_MESSAGE_LIMIT],
            {"errors": len(report.errors)},
        )
    return data, manifest


async def _register(
    session: AsyncSession,
    storage: ObjectStorage,
    job: Job,
    out: Path,
    data: bytes,
    manifest: qmp.Manifest,
) -> tuple[Any, bool]:
    """Версия модели из пакета: части в хранилище, фиксация; повторный пакет - прежняя версия."""
    if job.workspace_id is None or job.project_id is None:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "у задания нет проекта")
    version, created = await models_service.start_version(
        session,
        storage,
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        user_id=uuid.UUID(str(job.payload["requested_by"])),
        manifest_bytes=data,
        comment=f"Из IFC проекта, задание {job.id}",
    )
    if version.status is ModelVersionStatus.UPLOADING:
        missing = set(await models_service.missing_parts(session, storage, version))
        for part in manifest.parts:
            if part.path in missing:
                await models_service.store_part(
                    session, storage, version, part.path, _file_chunks(out / part.path)
                )
        await models_service.commit_version(session, storage, version)
    return version, created


async def execute_model_ifc_import(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    inputs = job.payload.get("inputs")
    if not isinstance(inputs, list) or not inputs or "requested_by" not in job.payload:
        return await _fail(session, job, CadError(ErrorCode.CAD_PARAMS_INVALID, "нет входных IFC"))

    owner, attempt = job.worker_id, job.attempt
    await jobs_service.start(session, job=job, stage="model_ifc_import")
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "out"):
            (attempt_dir / sub).mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            f"IFC проекта: чтение из хранилища и сверка SHA256, файлов {len(inputs)}",
            cad_progress.now(),
        )
        await session.commit()
        sources: list[Path] = []
        for index, item in enumerate(inputs):
            revision = (
                await session.get(DocumentRevision, uuid.UUID(str(item.get("revision_id"))))
                if isinstance(item, dict)
                else None
            )
            if revision is None or revision.source_sha256 != item.get("sha256"):
                raise CadError(ErrorCode.CAD_INPUT_INVALID, "ревизия IFC удалена или изменилась")
            target = attempt_dir / "in" / _local_name(index, revision.source_filename)
            await _download(storage, revision, target)
            sources.append(target)

        params = model_import_service.load_params(settings)
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
            job.payload, attempt, "worker", "Генератор модели из IFC", cad_progress.now()
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            generator_argv(settings, sources=sources, params=params_file, out=out),
            limit_seconds=float(settings.cad_total_timeout_seconds),
            poll_interval=settings.worker_heartbeat_interval_seconds,
            memory_limit_mb=settings.cad_model_max_memory_mb,
        )
        if outcome is None:
            log.warning("model_lease_lost", job_id=str(job.id))
            return job
        code, output = outcome
        if code != 0:
            raise generator_failure(code, output)
        data, manifest = await asyncio.to_thread(checked_package, out)
        if not await _still_owned(session, job, owner, attempt, lock=True):
            log.warning("model_lease_lost_before_publish", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "publish",
            f"Пакет модели сверен, сохранение версии: частей {len(manifest.parts)}",
            cad_progress.now(),
        )
        await session.commit()
        try:
            version, created = await _register(session, storage, job, out, data, manifest)
        except DomainError as error:
            raise CadError(
                ErrorCode.CAD_ENGINE_FAILED, error.detail[:_ERROR_MESSAGE_LIMIT]
            ) from error
    except CadError as failure:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        return await _fail(session, job, failure)
    finally:
        if attempt_dir is not None:
            shutil.rmtree(attempt_dir, ignore_errors=True)

    log.info("model_ifc_import_finished", job_id=str(job.id), version=str(version.id))
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=cad_service.RESULT_WITH_CAD,
    )
    result = {
        "version_id": str(version.id),
        "version_number": version.number,
        "created": created,
        "generator_version": job.payload["generator_version"],
        "params_sha256": job.payload["params_sha256"],
        "inputs": len(inputs),
        "counts": manifest.counts.model_dump(),
        "attempt": attempt,
    }
    return await jobs_service.succeed(session, job=job, payload={"model_result": result})
