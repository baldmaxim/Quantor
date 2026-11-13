"""Тело задания `cad_eom_route`: одобренный вид -> генератор cad_eom -> проверка -> хранилище.

Вход и его проверки - те же, что у трасс механики (`mep_handler`): PDF ревизии, файлы одобренного
вида родителя (`plan_candidates.dxf`, `scale.json`, `preview.json`) со сверкой sha256, действующее
одобрение вида. Генератор не импортируется: он работает подпроцессом интерпретатора движка (`-I`,
пустое окружение, пределы времени и памяти) по CLI-контракту:

    <python> -I run_eom.py --pdf --page-index --view-dxf --scale --preview --params --out
        --view-folder [--floor-elevation-mm] [--floor-height-mm] [--clear-height-mm]
        [--slab-thickness-mm] --approval-id

Коды выхода: 0 - готово; 2 - ошибка входа; 3 - ЭОМ и СС не построены (причина - одной строкой
JSON `{"code", "message"}` в stderr). Выход строго по контракту: `views/<вид>/eom_routes3d.json`,
`eom_candidate.json`, `eom_routes.dxf` (R2018), необязательный `report.json`; `manifest.json`
пишет исполнитель.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from app.cad_worker.mep_handler import (
    _checked_input,
    _download_artifact,
    _Input,
    _parent_view_row,
    _read_json_file,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.errors import ErrorCode
from app.models import DocumentRevision, Job
from app.services import cad as cad_service
from app.services import cad_eom as cad_eom_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_progress
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage

log = get_logger(__name__)

_ERROR_MESSAGE_LIMIT = 400
_DXF_HEAD_BYTES = 4096
_DXF_R2018 = b"AC1032"


def generator_argv(
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
    python, runner = settings.cad_engine_python.strip(), cad_eom_service.runner_path(settings)
    if not python or runner is None or not (Path(python).is_file() and runner.is_file()):
        raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "генератор ЭОМ и СС не настроен")
    manual: list[str] = []
    for flag, key in (
        ("--floor-elevation-mm", "floor_elevation_mm"),
        ("--floor-height-mm", "floor_height_mm"),
        ("--clear-height-mm", "clear_height_mm"),
        ("--slab-thickness-mm", "slab_thickness_mm"),
    ):
        value = cad_mep_service.payload_int(job, key)
        if value is not None:
            manual += [flag, str(value)]
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
        "--view-folder",
        folder.removeprefix("views/"),
        *manual,
        "--approval-id",
        str(job.payload["approval_id"]),
    ]


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
    message = message[:_ERROR_MESSAGE_LIMIT]
    by_generator_code = {
        "elevation_not_found": ErrorCode.CAD_ELEVATION_NOT_FOUND,
        "floor_height_not_found": ErrorCode.CAD_FLOOR_HEIGHT_NOT_FOUND,
    }
    mapped = by_generator_code.get(generator_code) or {
        2: ErrorCode.CAD_INPUT_INVALID,
        3: ErrorCode.CAD_EOM_NOT_BUILT,
    }.get(code, ErrorCode.CAD_ENGINE_FAILED)
    return CadError(mapped, message, {"generator_error": generator_code})


def _elevation_value(candidate: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Отметка пола или высота этажа из `eom_candidate.json` (как у `cad_mep`): значение и источник."""
    for section in ("provenance", "elevation"):
        block = candidate.get(section)
        raw = block.get(key) if isinstance(block, dict) else None
        if not isinstance(raw, dict):
            continue
        value = raw.get("value_mm", raw.get("value"))
        if type(value) is int or (isinstance(value, float) and value.is_integer()):
            return {
                "value_mm": int(value),
                "source": str(raw.get("source", ""))[:32],
                "evidence": str(raw.get("evidence", ""))[:400],
            }
    return None


def verified_outputs(
    out: Path, source: _Input, revision: DocumentRevision, params_sha: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Состав out/ строго по контракту; пишет report.json (если его нет) и manifest.json."""
    folder = source.folder
    required = {f"{folder}/{name}" for name in cad_eom_service.OUTPUT_FILES}
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    extra = present - required - {"report.json", "manifest.json"}
    if extra or not required <= present:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "состав out/ не совпал с контрактом генератора")
    for name in sorted(present):
        path = out / name
        if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "генератор выдал файл вне контракта")
    with (out / folder / cad_eom_service.ROUTES_DXF).open("rb") as handle:
        if _DXF_R2018 not in handle.read(_DXF_HEAD_BYTES):
            raise CadError(ErrorCode.CAD_ENGINE_FAILED, "DXF ЭОМ и СС не формата R2018")
    routes3d = _read_json_file(out / folder / cad_eom_service.ROUTES3D_JSON)
    if routes3d.get("schema") != cad_eom_service.ROUTES3D_SCHEMA:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "eom_routes3d.json вне контракта")
    candidate = _read_json_file(out / folder / cad_eom_service.CANDIDATE_JSON)
    if candidate.get("schema") != cad_eom_service.CANDIDATE_SCHEMA:
        raise CadError(ErrorCode.CAD_ENGINE_FAILED, "eom_candidate.json вне контракта")
    if "report.json" not in present:
        report = {
            "schema": "quantor.cad_eom.report.v1",
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
            "floor_elevation": _elevation_value(candidate, "floor_elevation_mm"),
            "floor_height": _elevation_value(candidate, "floor_height_mm"),
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
        "schema": "quantor.cad_eom.manifest.v1",
        "generator_version": source.job.payload.get("generator_version"),
        "params_sha256": params_sha,
        "input": {"sha256": revision.source_sha256},
        "files": files,
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    files.append(
        {"name": "manifest.json", "sha256": _sha256(manifest_path), "size": manifest_path.stat().st_size}
    )
    return files, candidate


async def execute_cad_eom_route(
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
    await jobs_service.start(session, job=job, stage="cad_eom_route")
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

        params = cad_eom_service.load_params(settings)
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
            job.payload, attempt, "worker", "Генератор ЭОМ и СС этажа", cad_progress.now()
        )
        await session.commit()
        outcome = await _run_while_owned(
            session,
            job,
            owner,
            attempt,
            generator_argv(
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
            raise generator_failure(code, output)
        files, candidate = verified_outputs(out, source, revision, params.sha256)
        if not await _still_owned(session, job, owner, attempt):
            log.warning("cad_lease_lost", job_id=str(job.id))
            return job
        job.payload = cad_progress.phase_event(
            job.payload,
            attempt,
            "publish",
            f"Файлы ЭОМ и СС сверены, загрузка: {len(files)}",
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
        "floor_elevation": _elevation_value(candidate, "floor_elevation_mm"),
        "floor_height": _elevation_value(candidate, "floor_height_mm"),
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
                        "dxf": f"{source.folder}/{cad_eom_service.ROUTES_DXF}",
                        "dxf_entities": None,
                    }
                ],
            }
        ],
        "artifacts": artifacts,
    }
    log.info("cad_eom_route_finished", job_id=str(job.id))
    job.payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome="succeeded",
        result_status=cad_service.RESULT_WITH_CAD,
    )
    return await jobs_service.succeed(session, job=job, payload={"cad_result": result})
