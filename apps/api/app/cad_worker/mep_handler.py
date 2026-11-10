"""Тело задания `cad_mep_route`: одобренный вид -> генератор tools/cad_mep -> проверка -> хранилище.

Генератор не импортируется: он работает подпроцессом интерпретатора движка (`-I`, пустое
окружение, новая группа процессов, пределы времени и памяти) по CLI-контракту:

    <python> -I run_mep.py --pdf --page-index --view-dxf --scale --preview --params --out
        --view-folder [--floor-elevation-mm] [--floor-height-mm]

Отметка пола и высота этажа в аргументы попадают только если их задал человек (запрос или
пересчёт); иначе генератор определяет их по тексту документации.

Коды выхода: 0 - готово; 2 - ошибка входа; 3 - трассы не построены (причина - одной строкой JSON
`{"code", "message"}` в stderr). Общие части (аренда, загрузка, отказ задания) - из `handler`.
Вход проверяется до запуска: PDF ревизии, plan_candidates.dxf, scale.json и preview.json родителя
сверяются по sha256, а одобрение вида должно существовать.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import update
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
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import CadDecision, CadRemark, DocumentRevision, Job
from app.models.cad_decision import DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_progress
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

_ERROR_MESSAGE_LIMIT = 400
_DXF_HEAD_BYTES = 4096
_DXF_R2018 = b"AC1032"


class _Input:
    """Проверенный вход задания: родитель, вид, одобрение."""

    def __init__(self, job: Job, parent: Job, folder: str, page_index: int, view: int) -> None:
        self.job, self.parent, self.folder = job, parent, folder
        self.page_index, self.view = page_index, view


def _generator_argv(
    settings: Settings,
    *,
    source: Path,
    parent_files: dict[str, Path],
    params: Path,
    out: Path,
    job: Job,
    folder: str,
    page_index: int,
) -> list[str]:
    python, runner = settings.cad_engine_python.strip(), settings.cad_mep_runner.strip()
    if not (python and runner) or not (Path(python).is_file() and Path(runner).is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "генератор трасс механики не настроен")
    manual: list[str] = []
    for flag, key in (
        ("--floor-elevation-mm", "floor_elevation_mm"),
        ("--floor-height-mm", "floor_height_mm"),
    ):
        value = cad_mep_service.payload_int(job, key)
        if value is not None:
            manual += [flag, str(value)]
    return [
        python,
        "-I",
        runner,
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
        "--view-folder",
        folder.removeprefix("views/"),
        *manual,
        "--approval-id",
        str(job.payload["approval_id"]),
    ]


async def _checked_input(session: AsyncSession, job: Job) -> _Input:
    payload = job.payload
    parent_id = cad_mep_service.parent_job_id_of(job)
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    parent_attempt = cad_mep_service.payload_int(job, "parent_attempt")
    if parent_id is None or page_index is None or view is None or parent_attempt is None:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "задание трасс заполнено не полностью")
    for key in ("floor_elevation_mm", "floor_height_mm"):
        if key not in payload or (payload[key] is not None and type(payload[key]) is not int):
            raise CadError(ErrorCode.CAD_PARAMS_INVALID, "отметки этажа заданы неверно")
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
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "результат родителя недоступен для трасс")
    try:
        folder = cad_service.view_folder(page_index, view)
        approval_id = uuid.UUID(str(payload.get("approval_id")))
    except ValueError as error:
        raise CadError(ErrorCode.CAD_PARAMS_INVALID, "вид или одобрение заданы неверно") from error
    approval = await session.get(CadDecision, approval_id)
    if (
        approval is None
        or approval.kind != DECISION_VIEW_APPROVAL
        or approval.job_id != parent.id
        or (approval.attempt, approval.page_index, approval.view)
        != (parent_attempt, page_index, view)
        or approval.artifact_sha256 != payload.get("view_dxf_sha256")
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "вид не одобрен для построения трасс")
    if approval.revoked_at is not None:
        raise CadError(ErrorCode.CAD_VIEW_APPROVAL_REVOKED, "одобрение вида отозвано")
    return _Input(job, parent, folder, page_index, view)


async def _download_artifact(
    storage: ObjectStorage,
    parent: Job,
    revision_id: uuid.UUID,
    name: str,
    expected_sha256: str | None,
    target: Path,
) -> None:
    """Артефакт родителя в файл попытки; sha256 сверяется с результатом родителя."""
    artifact = cad_service.find_artifact(parent, name)
    attempt = cad_service.result_of(parent).get("attempt")
    if artifact is None or type(attempt) is not int:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, f"у родителя нет {name}")
    key = cad_service.artifact_storage_key(revision_id, parent.id, attempt, name)
    if artifact.get("key") != key or (
        expected_sha256 and artifact.get("sha256") != expected_sha256
    ):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, f"{name} родителя не совпал с одобренным")
    digest = hashlib.sha256()
    try:
        with target.open("xb") as sink:
            async for chunk in storage.iter_stream(key):
                digest.update(chunk)
                sink.write(chunk)
    except ObjectNotFoundError as error:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, f"{name} родителя не найден") from error
    except StorageUnavailableError as error:
        raise CadError(ErrorCode.STORAGE_UNAVAILABLE, "хранилище недоступно") from error
    if digest.hexdigest() != artifact.get("sha256"):
        raise CadError(ErrorCode.CAD_INPUT_INVALID, f"SHA256 {name} родителя не совпал")


def _generator_failure(code: int, output: bytes) -> CadError:
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
    message = message[:_ERROR_MESSAGE_LIMIT]
    by_generator_code = {
        "elevation_not_found": ErrorCode.CAD_ELEVATION_NOT_FOUND,
        "floor_height_not_found": ErrorCode.CAD_FLOOR_HEIGHT_NOT_FOUND,
    }
    mapped = by_generator_code.get(generator_code) or {
        2: ErrorCode.CAD_INPUT_INVALID,
        3: ErrorCode.CAD_MEP_NOT_BUILT,
    }.get(code, ErrorCode.CAD_ENGINE_FAILED)
    return CadError(mapped, message, {"generator_error": generator_code})


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{path.name} не читается") from error
    if not isinstance(value, dict):
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, f"{path.name} не объект JSON")
    return value


def _provenance_value(candidate: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Отметка или высота из candidate.json: значение, источник и доказательство."""
    provenance = candidate.get("provenance")
    raw = provenance.get(key) if isinstance(provenance, dict) else None
    if not isinstance(raw, dict) or type(raw.get("value_mm")) is not int:
        return None
    return {
        "value_mm": raw["value_mm"],
        "source": str(raw.get("source", ""))[:32],
        "evidence": str(raw.get("evidence", ""))[:400],
    }


def _verified_route_outputs(
    out: Path, source: _Input, revision: DocumentRevision, params_sha: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Состав out/ строго по контракту; пишет report.json и manifest.json исполнителя.

    Обязательны три файла вида: `mep_routes.dxf` (R2018), `preview.json` и `candidate.json`
    нужных схем. `report.json` генератора, если он есть, сохраняется; `manifest.json` всегда
    свой: список файлов с sha256 и размером.
    """
    folder = source.folder
    required = {f"{folder}/{name}" for name in (cad_mep_service.ROUTES_DXF, "preview.json")} | {
        f"{folder}/candidate.json"
    }
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    extra = present - required - {"report.json", "manifest.json"}
    if extra or not required <= present:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом генератора")
    for name in sorted(present):
        path = out / name
        if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "генератор выдал файл вне контракта")
    with (out / folder / cad_mep_service.ROUTES_DXF).open("rb") as handle:
        if _DXF_R2018 not in handle.read(_DXF_HEAD_BYTES):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "DXF трасс не формата R2018")
    preview = _read_json_file(out / folder / "preview.json")
    if preview.get("schema") != cad_mep_service.PREVIEW_SCHEMA or preview.get("units") != "mm":
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "preview.json вне контракта")
    candidate = _read_json_file(out / folder / "candidate.json")
    if candidate.get("schema") != cad_mep_service.CANDIDATE_SCHEMA:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "candidate.json вне контракта")
    if "report.json" not in present:
        report = {
            "schema": "quantor.cad_mep.report.v1",
            "status": cad_service.RESULT_WITH_CAD,
            "review_required": True,
            "generator_version": source.job.payload.get("generator_version"),
            "params_sha256": params_sha,
            "input_sha256": revision.source_sha256,
            "view_dxf_sha256": source.job.payload.get("view_dxf_sha256"),
            "approval_id": source.job.payload.get("approval_id"),
            "parent_job_id": str(source.parent.id),
            "page_index": source.page_index,
            "view": source.view,
            "floor_elevation": _provenance_value(candidate, "floor_elevation"),
            "floor_height": _provenance_value(candidate, "floor_height"),
            "finished_at": datetime.now(UTC).isoformat(),
        }
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
    else:
        _read_json_file(out / "report.json")
    files = [
        {"name": name, "sha256": _sha256(out / name), "size": (out / name).stat().st_size}
        for name in sorted(required | {"report.json"})
    ]
    manifest = {
        "schema": "quantor.cad_mep.manifest.v1",
        "generator_version": source.job.payload.get("generator_version"),
        "params_sha256": params_sha,
        "input": {"sha256": revision.source_sha256},
        "files": files,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    manifest_path = out / "manifest.json"
    files.append(
        {
            "name": "manifest.json",
            "sha256": _sha256(manifest_path),
            "size": manifest_path.stat().st_size,
        }
    )
    return files, candidate


def _parent_view_row(parent: Job, page_index: int, view: int) -> dict[str, Any]:
    for page in cad_service.result_of(parent).get("pages", []):
        if page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if isinstance(row, dict) and row.get("view") == view:
                return row
    return {}


async def _bind_remarks_to_result(
    session: AsyncSession, job: Job, source: _Input, attempt: int, result: dict[str, Any]
) -> None:
    """Замечания, перенесённые пересчётом, привязываются к DXF трасс новой попытки."""
    artifact = next(
        (
            a
            for a in result["artifacts"]
            if a["name"] == f"{source.folder}/{cad_mep_service.ROUTES_DXF}"
        ),
        None,
    )
    if artifact is None:
        return
    await session.execute(
        update(CadRemark)
        .where(
            CadRemark.job_id == job.id,
            CadRemark.attempt == attempt,
            CadRemark.page_index == source.page_index,
            CadRemark.view == source.view,
            CadRemark.dxf_sha256.is_(None),
        )
        .values(dxf_sha256=str(artifact["sha256"]))
    )


async def execute_cad_mep_route(
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
    await jobs_service.start(session, job=job, stage="cad_mep_route")
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
        pdf = attempt_dir / "in" / "source.pdf"
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "download",
            "Исходный PDF и файлы вида родителя: чтение из хранилища и сверка SHA256",
            cad_progress.now(),
        )
        await session.commit()
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
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            _generator_argv(
                settings,
                source=pdf,
                parent_files=parent_files,
                params=params_file,
                out=out,
                job=job,
                folder=source.folder,
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
        files, candidate = _verified_route_outputs(out, source, revision, params.sha256)
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "publish",
            f"Файлы трасс сверены, загрузка: {len(files)}",
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

    parent_row = _parent_view_row(source.parent, source.page_index, source.view)
    result = {
        "result_status": cad_service.RESULT_WITH_CAD,
        "review_required": True,
        "engine_version": job.payload["generator_version"],
        "generator_version": job.payload["generator_version"],
        "input_sha256": revision.source_sha256,
        "params_sha256": job.payload["params_sha256"],
        "view_dxf_sha256": job.payload["view_dxf_sha256"],
        "approval_id": job.payload["approval_id"],
        # Итог генератора: отметка пола и высота этажа с источником и доказательством.
        "floor_elevation": _provenance_value(candidate, "floor_elevation"),
        "floor_height": _provenance_value(candidate, "floor_height"),
        "attempt": attempt,
        "dxf_count": 1,
        "pages": [
            {
                "index": source.page_index,
                "legacy_pdf_page": source.page_index + 1,
                "intake_selected": None,
                "views": [
                    {
                        "view": source.view,
                        "status": "needs_review",
                        "scale_status": parent_row.get("scale_status"),
                        "scale_source": parent_row.get("scale_source"),
                        "scale_deviation": parent_row.get("scale_deviation"),
                        "failure_code": None,
                        "failure_reason": None,
                        "dxf": f"{source.folder}/{cad_mep_service.ROUTES_DXF}",
                        "dxf_entities": None,
                    }
                ],
            }
        ],
        "artifacts": artifacts,
    }
    log.info("cad_mep_route_finished", job_id=str(job.id))
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=cad_service.RESULT_WITH_CAD,
    )
    await _bind_remarks_to_result(session, job, source, attempt, result)
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
