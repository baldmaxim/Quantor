"""Тело задания `cad_zones`: DXF вида -> CLI cad_mep/run_zones.py -> зоны листа.

CLI не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти) по контракту, общему с генератором трасс:

    <python> -I run_zones.py --pdf --page-index --view-dxf --scale --preview --params --out

`--out` - файл `zones.json`. Вход берётся у родителя `cad_pdf_convert` (PDF ревизии, DXF, scale.json
и preview.json вида) и сверяется по sha256 до запуска. Код выхода 2 - ошибка входа, причина -
одной строкой JSON `{"code", "message"}` в stderr. Общие части (аренда, загрузка, отказ задания) -
из `handler`.

Разметка человека неприкосновенна: если на листе есть зоны (до запуска или перед записью), зоны не
создаются, задание завершается успешно со статусом `zones_skipped_existing`. Зоны пишутся через
общий сервис зон: площадь и периметр считает сервер по калибровке листа, как у ручных зон.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
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
from app.contracts.cad_zones import MAX_TEXT, CadZoneCreate
from app.contracts.cad_zones_auto import PARKING_TYPE_LABELS, ZonesFile
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_progress, cad_walls
from app.services import cad_zones as cad_zones_service
from app.services import cad_zones_auto as auto
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)


class _Input:
    """Проверенный вход задания: родитель и каталог вида."""

    def __init__(
        self,
        parent: Job,
        folder: str,
        page_index: int,
        view: int,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        self.parent, self.folder = parent, folder
        self.page_index, self.view = page_index, view
        self.workspace_id, self.project_id = workspace_id, project_id


def _argv(
    settings: Settings,
    *,
    source: Path,
    parent_files: dict[str, Path],
    params: Path,
    out: Path,
    page_index: int,
) -> list[str]:
    python, runner = settings.cad_engine_python.strip(), auto.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "разметка зон не настроена")
    return [
        python,
        "-I",
        str(runner),
        "--pdf",
        str(source),
        "--page-index",
        str(page_index),
        "--view-dxf",
        str(parent_files["plan_candidates.dxf"]),
        "--scale",
        str(parent_files["scale.json"]),
        "--preview",
        str(parent_files["preview.json"]),
        "--params",
        str(params),
        "--out",
        str(out),
    ]


async def _checked_input(session: AsyncSession, job: Job) -> _Input:
    payload = job.payload
    try:
        parent_id = uuid.UUID(str(payload.get("parent_job_id")))
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание зон заполнено неверно") from error
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    parent_attempt = cad_mep_service.payload_int(job, "parent_attempt")
    if page_index is None or view is None or parent_attempt is None:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание зон заполнено не полностью")
    parent = await session.get(Job, parent_id)
    if (
        parent is None
        or parent.workspace_id is None
        or parent.project_id is None
        or parent.job_type is not JobType.CAD_PDF_CONVERT
        or parent.workspace_id != job.workspace_id
        or parent.project_id != job.project_id
        or parent.payload.get("revision_id") != payload.get("revision_id")
        or parent.status is not JobStatus.SUCCEEDED
        or cad_service.result_of(parent).get("attempt") != parent_attempt
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "результат родителя недоступен для зон")
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "вид задан неверно") from error
    dxf = cad_service.find_artifact(parent, f"{folder}/plan_candidates.dxf")
    if dxf is None or dxf.get("sha256") != payload.get("view_dxf_sha256"):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "DXF вида не совпал с заданием")
    return _Input(parent, folder, page_index, view, parent.workspace_id, parent.project_id)


def _verified_output(out: Path, source: _Input) -> tuple[list[dict[str, Any]], ZonesFile]:
    """В out/ строго один файл вида; схема и страница совпадают с заданием."""
    name = f"{source.folder}/{auto.ZONES_JSON}"
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    if present != {name}:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом CLI")
    path = out / name
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "CLI выдал файл вне контракта")
    if path.stat().st_size > cad_service.MAX_JSON_ARTIFACT_BYTES:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "zones.json больше допустимого размера")
    raw = _read_json_file(path)
    if raw.get("schema") != auto.ZONES_SCHEMA:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "zones.json вне контракта")
    try:
        document = ZonesFile.model_validate(raw)
    except ValidationError as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "zones.json вне контракта") from error
    if document.page_index != source.page_index:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "zones.json не относится к этому заданию")
    return [{"name": name, "sha256": _sha256(path), "size": path.stat().st_size}], document


async def _insert_zones(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision: DocumentRevision,
    document: ZonesFile,
) -> tuple[int, int, int]:
    """Зоны и машино-места файла -> зоны листа через сервис зон.

    Невалидная для сервера зона пропускается. Возвращает: создано всего, отклонено, из созданных -
    помещений квартир и МОП (машино-места на стены и конструкции не влияют).
    """
    created = rejected = rooms = 0
    bodies: list[CadZoneCreate] = []
    for zone in document.zones:
        try:
            bodies.append(
                CadZoneCreate(
                    revision_id=revision.id,
                    page_index=document.page_index,
                    kind=zone.kind,
                    apartment_no=(
                        None
                        if zone.kind == "room_mop" or zone.apartment_no is None
                        else zone.apartment_no[:MAX_TEXT]
                    ),
                    room_mark=None if zone.room_mark is None else zone.room_mark[:MAX_TEXT],
                    name=None if zone.name is None else zone.name[:MAX_TEXT],
                    points=zone.points,
                )
            )
        except ValidationError:
            rejected += 1
    for space in document.parking_spaces:
        label = None if space.label is None else space.label.strip()[:MAX_TEXT]
        try:
            bodies.append(
                CadZoneCreate(
                    revision_id=revision.id,
                    page_index=document.page_index,
                    kind="parking_space",
                    name=label or PARKING_TYPE_LABELS[space.parking_type],
                    parking_type=space.parking_type,
                    points=space.points,
                )
            )
        except ValidationError:
            rejected += 1
    for body in bodies:
        try:
            await cad_zones_service.create_zone(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                body=body,
                user_id=None,
            )
        except DomainError:
            rejected += 1
            continue
        created += 1
        if body.kind in ("room_apartment", "room_mop"):
            rooms += 1
    return created, rejected, rooms


async def execute_cad_zones(
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
    await jobs_service.start(session, job=job, stage="cad_zones")
    job.payload = cad_progress.begin_attempt(job.payload, attempt, cad_progress.now())
    await session.commit()

    attempt_dir: Path | None = None
    try:
        source = await _checked_input(session, job)
        # Зоны человека уже есть - генератор не запускается совсем.
        if await auto.page_zone_count(
            session, revision_id=revision.id, page_index=source.page_index
        ):
            if not await _still_owned(session, job, owner, attempt, lock=True):
                return job
            return await _finish(session, job, revision, source, attempt, skipped=True)
        work_root = Path(settings.cad_work_root or Path(tempfile.gettempdir()) / "quantor-cad")
        await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True, mode=0o700)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{job.id}-attempt-{attempt}-", dir=work_root))
        for sub in ("in", "out"):
            (attempt_dir / sub).mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "Исходный PDF и файлы вида родителя: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
        pdf = attempt_dir / "in" / "source.pdf"
        await _download(storage, revision, pdf)
        parent_files: dict[str, Path] = {}
        for name in ("plan_candidates.dxf", "scale.json", "preview.json"):
            target = attempt_dir / "in" / name
            await _download_artifact(
                storage,
                source.parent,
                revision.id,
                f"{source.folder}/{name}",
                str(job.payload["view_dxf_sha256"]) if name == "plan_candidates.dxf" else None,
                target,
            )
            parent_files[name] = target

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
        zones_file = out / source.folder / auto.ZONES_JSON
        zones_file.parent.mkdir(parents=True, mode=0o700)
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "worker", "Разметка зон по DXF вида", cad_progress.now()
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
                parent_files=parent_files,
                params=params_file,
                out=zones_file,
                page_index=source.page_index,
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
        files, document = _verified_output(out, source)
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload, attempt, "publish", "zones.json сверен, загрузка", cad_progress.now()
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

    # Строка задания под блокировкой. Зоны могли появиться, пока работал CLI: тогда - ничего.
    skipped = bool(
        await auto.page_zone_count(session, revision_id=revision.id, page_index=source.page_index)
    )
    created, rejected, rooms = (
        (0, 0, 0)
        if skipped
        else await _insert_zones(
            session,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            revision=revision,
            document=document,
        )
    )
    if rooms:
        await _recompute_walls(session, storage, source, settings)
    return await _finish(
        session,
        job,
        revision,
        source,
        attempt,
        skipped=skipped,
        files=files,
        counts={
            "in_file": len(document.zones) + len(document.parking_spaces),
            "created": created,
            "rejected": rejected,
        },
        artifacts=artifacts,
    )


async def _recompute_walls(
    session: AsyncSession, storage: ObjectStorage, source: _Input, settings: Settings
) -> None:
    """Появились зоны листа: конструкции вида пересчитываются с зонами (контур плиты).

    Постановка идёт в транзакции записи успеха; сбой её не рушит, разметка остаётся.
    """
    try:
        async with session.begin_nested():
            await cad_walls.schedule_after_auto_zones(
                session,
                storage,
                parent=source.parent,
                page_index=source.page_index,
                view=source.view,
                settings=settings,
            )
    except (DomainError, HTTPException, SQLAlchemyError):
        log.warning(
            "cad_walls_recompute_after_zones_failed",
            job_id=str(source.parent.id),
            page_index=source.page_index,
            view=source.view,
        )


async def _finish(
    session: AsyncSession,
    job: Job,
    revision: DocumentRevision,
    source: _Input,
    attempt: int,
    *,
    skipped: bool,
    files: list[dict[str, Any]] | None = None,
    counts: dict[str, int] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> Job:
    """Итог попытки: `zones_ready` либо `zones_skipped_existing` (на листе уже есть зоны)."""
    status = auto.RESULT_SKIPPED_EXISTING if skipped else auto.RESULT_READY
    result = {
        "result_status": status,
        "attempt": attempt,
        "generator_version": job.payload.get("generator_version"),
        "params_sha256": job.payload.get("params_sha256"),
        "dxf_sha256": job.payload.get("view_dxf_sha256"),
        "zones_sha256": files[0]["sha256"] if files else None,
        "input_sha256": revision.source_sha256,
        "parent_job_id": str(source.parent.id),
        "page_index": source.page_index,
        "view": source.view,
        "counts": counts or {"in_file": 0, "created": 0, "rejected": 0},
        "artifacts": artifacts or [],
    }
    log.info("cad_zones_finished", job_id=str(job.id), result_status=status)
    job.payload = cad_progress.finish_attempt(
        job.payload, attempt, cad_progress.now(), outcome="succeeded", result_status=status
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
