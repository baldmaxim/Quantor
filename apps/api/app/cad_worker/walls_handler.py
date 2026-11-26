"""Тело задания `cad_walls`: DXF вида -> скрипт cad_walls -> проверка walls.json -> хранилище.

Скрипт не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое окружение,
новая группа процессов, пределы времени и памяти) по CLI-контракту:

    <python> -I run_walls.py --dxf --params --out --pdf --page [--zones] [--view-zone=X0,Y0,X1,Y1]
    [--frame=OX,OY,K] [--control] [--hints]

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
import math
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import znaki_corner_door
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
from app.services import ai_loop, cad_progress, cad_quality, cad_walls_zones
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_requeue as requeue
from app.services import cad_walls as cad_walls_service
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

RESULT_READY = "walls_ready"
_RENDER_CLI = Path(__file__).with_name("view_render_cli.py")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_RENDER_TIMEOUT_SECONDS = 60.0


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
    view_zone: tuple[float, float, float, float] | None = None,
    control: Path | None = None,
    frame: tuple[float, float, float] | None = None,
    hints: Path | None = None,
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
    if view_zone is not None:
        x0, y0, x1, y1 = (round(v, 2) for v in view_zone)
        argv += [f"--view-zone={x0},{y0},{x1},{y1}"]
    if frame is not None:
        ox, oy, k = frame
        argv += [f"--frame={round(ox, 4)},{round(oy, 4)},{round(k, 6)}"]
    if control is not None:
        argv += ["--control", str(control)]
    if hints is not None:
        argv += ["--hints", str(hints)]
    return argv


def _view_zone_of(payload: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Зона вида из задания: четыре конечных числа и x1 > x0, y1 > y0; иначе — без аргумента."""
    raw = payload.get("view_zone")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        return None
    x0, y0, x1, y1 = (float(v) for v in raw)
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _view_frame_of(payload: dict[str, Any]) -> tuple[float, float, float] | None:
    """Кадр вида из задания: три конечных числа и мм на пт > 0; иначе — без аргумента."""
    raw = payload.get("view_frame")
    if not isinstance(raw, list) or len(raw) != 3:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        return None
    ox, oy, k = (float(v) for v in raw)
    if not all(math.isfinite(v) for v in (ox, oy, k)) or k <= 0:
        return None
    return (ox, oy, k)


HINTS_SCHEMA = "quantor.cad_walls_hints.v1"


def bbox_pt_to_view_mm(
    bbox_pt: tuple[float, float, float, float], frame: tuple[float, float, float]
) -> tuple[float, float, float, float]:
    """Рамка замечания (пт PDF от левого верхнего угла) -> мм DXF вида (X вправо, Y вверх).

    Обратное к кадру движка `pt = origin + (x_mm, -y_mm) / k`: `x_mm = (x_pt - ox) * k`,
    `y_mm = (oy - y_pt) * k`. Ось Y переворачивается, поэтому нижний край в мм берётся от
    нижнего (большего) края в пт; порядок углов нормализуется: x0 < x1, y0 < y1.
    """
    ox, oy, k = frame
    x0_pt, y0_pt, x1_pt, y1_pt = bbox_pt
    xa, xb = (x0_pt - ox) * k, (x1_pt - ox) * k
    ya, yb = (oy - y0_pt) * k, (oy - y1_pt) * k
    return (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))


def _hints_document(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Файл подсказок для `--hints` из задания; нет `hints` - `None`.

    Подсказки есть, а кадр вида или рамка негодны - отказ, а не молчаливый обычный пересчёт.
    """
    if "hints" not in payload:
        return None
    raw = payload["hints"]
    frame = _view_frame_of(payload)
    if not isinstance(raw, list) or frame is None:
        raise CadError(
            ErrorCode.CAD_PARAMS_INVALID, "подсказки задания конструкций заполнены неверно"
        )
    items: list[dict[str, Any]] = []
    for row in raw:
        bbox = row.get("bbox_pt") if isinstance(row, dict) else None
        if (
            not isinstance(row, dict)
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
            or not all(math.isfinite(v) for v in bbox)
            or not isinstance(row.get("id"), str)
            or not isinstance(row.get("type"), str)
        ):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "подсказка задания заполнена неверно")
        x0, y0, x1, y1 = bbox_pt_to_view_mm((bbox[0], bbox[1], bbox[2], bbox[3]), frame)
        items.append(
            {
                "id": row["id"],
                "type": row["type"],
                "bbox_mm": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                "construction_ids": [
                    v for v in row.get("construction_ids", []) if isinstance(v, str)
                ],
                "comment": row.get("comment") if isinstance(row.get("comment"), str) else "",
            }
        )
    if not items:
        return None
    return {"schema": HINTS_SCHEMA, "hints": items}


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


def _render_argv(
    settings: Settings,
    job: Job,
    *,
    pdf: Path,
    walls_file: Path,
    source: _Input,
) -> list[str] | None:
    frame = _view_frame_of(job.payload)
    python = settings.cad_engine_python.strip()
    if frame is None or not python or not Path(python).is_file():
        return None
    ox, oy, k = frame
    argv = [
        python,
        "-I",
        str(_RENDER_CLI),
        "--pdf",
        str(pdf),
        "--walls",
        str(walls_file),
        "--out-dir",
        str(walls_file.parent),
        "--page",
        str(source.page_index),
        "--ox",
        str(ox),
        "--oy",
        str(oy),
        "--k",
        str(k),
    ]
    zone = _view_zone_of(job.payload)
    if zone is not None:
        argv += ["--view-zone", ",".join(str(v) for v in zone)]
    return argv


def _collect_rendered_images(
    job_id: uuid.UUID, walls_dir: Path, folder: str
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for filename, is_png, required in (
        ("plan.png", True, True),
        ("overlay.png", True, True),
        ("slab_overlay.png", True, False),
        ("render.json", False, True),
    ):
        path = walls_dir / filename
        if not path.is_file() or path.is_symlink():
            if not required:
                continue
            log.warning("cad_walls_render_missing", job_id=str(job_id), file=filename)
            return []
        size = path.stat().st_size
        limit = (
            cad_service.MAX_PNG_ARTIFACT_BYTES if is_png else cad_service.MAX_JSON_ARTIFACT_BYTES
        )
        if size <= 0 or size > limit:
            if not required:
                continue
            log.warning("cad_walls_render_oversized", job_id=str(job_id), file=filename, size=size)
            return []
        if is_png and path.read_bytes()[: len(_PNG_MAGIC)] != _PNG_MAGIC:
            if not required:
                continue
            log.warning("cad_walls_render_invalid_png", job_id=str(job_id), file=filename)
            return []
        rendered.append({"name": f"{folder}/{filename}", "sha256": _sha256(path), "size": size})
    return rendered


async def _render_view_images(
    session: AsyncSession,
    job: Job,
    owner: str | None,
    attempt: int,
    settings: Settings,
    *,
    pdf: Path,
    walls_file: Path,
    source: _Input,
) -> list[dict[str, Any]] | None:
    """Рендер `plan.png`, `overlay.png`, `render.json` в подпроцессе движка; сбой не роняет walls.

    Возвращает `None`, только если во время рендера потеряна аренда задания.
    """
    argv = _render_argv(settings, job, pdf=pdf, walls_file=walls_file, source=source)
    if argv is None:
        return []
    outcome = await _run_while_owned(
        session,
        job,
        owner,
        attempt,
        argv,
        limit_seconds=_RENDER_TIMEOUT_SECONDS,
        poll_interval=settings.worker_heartbeat_interval_seconds,
        memory_limit_mb=settings.cad_max_memory_mb,
    )
    if outcome is None:
        return None
    code, _ = outcome
    if code != 0:
        log.warning("cad_walls_render_skipped", job_id=str(job.id), exit_code=code)
        return []
    return _collect_rendered_images(job.id, walls_file.parent, source.folder)


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

        # Контроль движка — необязательный вход: нет среди артефактов родителя — без аргумента.
        control_name = f"{source.folder}/{cad_walls_service.CONTROL_ARTIFACT}"
        control_file: Path | None = None
        if cad_service.find_artifact(source.parent, control_name) is not None:
            control_file = attempt_dir / "in" / cad_walls_service.CONTROL_ARTIFACT
            await _download_artifact(
                storage, source.parent, revision.id, control_name, None, control_file
            )

        params = cad_walls_service.load_params(settings)
        raw_params = params.path.read_bytes()
        if cad_service.params_sha256(json.loads(raw_params)) != params.sha256:
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "файл параметров не совпал с закреплением")
        if (
            params.sha256 != job.payload.get("params_sha256")
            or params.generator_version != job.payload.get("generator_version")
            or params.params_version != job.payload.get("params_version")
        ):
            # Пин сменился после постановки: то же задание ставится с действующими параметрами.
            if not requeue.can_requeue(job):
                raise CadError(
                    ErrorCode.CAD_PARAMS_INVALID, "параметры или версия скрипта изменены"
                )
            if not await _still_owned(session, job, owner, attempt, lock=True):
                return job
            replacement = await cad_walls_service.requeue_with_current_params(
                session,
                job=job,
                parent=source.parent,
                params=params,
            )
            return await requeue.supersede(session, job, replacement, attempt)
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

        hints_file: Path | None = None
        hints_document = _hints_document(job.payload)
        if hints_document is not None:
            hints_file = attempt_dir / "in" / "hints.json"
            hints_file.write_text(json.dumps(hints_document, ensure_ascii=False), encoding="utf-8")

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
                view_zone=_view_zone_of(job.payload),
                control=control_file,
                frame=_view_frame_of(job.payload),
                hints=hints_file,
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
        dxf_sha256 = _sha256(dxf)
        files, document = _verified_output(out, source, job, params, dxf_sha256)
        if znaki_corner_door.applies(
            str(job.project_id), revision.source_sha256, dxf_sha256, source.page_index, source.view
        ):
            corrected = await _run_while_owned(
                session,
                job,
                owner,
                attempt,
                [
                    settings.cad_engine_python,
                    "-I",
                    znaki_corner_door.__file__,
                    str(walls_file),
                    str(dxf),
                ],
                limit_seconds=30,
                poll_interval=settings.worker_heartbeat_interval_seconds,
                memory_limit_mb=settings.cad_max_memory_mb,
            )
            if corrected is None:
                return job
            if corrected[0] != 0:
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED, "Не подтверждены откосы двери на листе 32"
                )
            files, document = _verified_output(out, source, job, params, dxf_sha256)
        rendered = await _render_view_images(
            session,
            job,
            owner,
            attempt,
            settings,
            pdf=pdf,
            walls_file=walls_file,
            source=source,
        )
        if rendered is None:
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        files = [*files, *rendered]
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
        # Порог качества: итог остаётся `walls_ready`, а причины «на проверку» идут отдельным
        # блоком - потребители результата (3D, итоги, отделка) его не читают и не ломаются.
        "quality": cad_quality.walls_quality(document),
        "artifacts": artifacts,
    }
    log.info("cad_walls_finished", job_id=str(job.id))
    job.payload = cad_progress.finish_attempt(
        job.payload, attempt, cad_progress.now(), outcome="succeeded", result_status=RESULT_READY
    )
    done = await jobs_service.succeed(session, job=job, payload={"cad_result": result})
    # Автоход петли ИИ пилота: правщик по готовым конструкциям вида (в той же транзакции).
    await ai_loop.after_walls(session, done, settings)
    return done
