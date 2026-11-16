"""Сопровождение пилота CAD с сервера: замечания проверяющего и выгрузка задания для разбора.

Инструмент разработчика, а не возможность продукта: вызывается только командами
`python -m app.cli` внутри контейнера api (доступ — у того, кто вошёл на сервер), HTTP-маршрутов
у него нет. Пишет одно: статус замечания (`open` / `resolved`). Всё остальное — чтение.

Выгрузка повторяет раскладку каталога попытки у исполнителя CAD: `in/` — то, что получил
генератор (PDF ревизии, файлы вида родителя, реестр стояков), `out/` — то, что задание опубликовало.
Каждый файл сверяется с sha256 из итога задания; несовпадение — отказ, а не тихая подмена.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CadRemark, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_risers
from app.storage.base import ObjectStorage

BUNDLE_SCHEMA: Final = "quantor.cad-ops.bundle.v1"
REMARKS_SCHEMA: Final = "quantor.cad-ops.remarks.v1"
# Файлы вида родителя, которые получают задания по виду (трассы, ЭОМ и СС, зоны, конструкции).
PARENT_VIEW_FILES: Final = ("plan_candidates.dxf", "scale.json", "preview.json")
# Ручные отметки этажа: передаются генератору флагами, только если их задал человек.
MANUAL_FLAGS: Final = (
    ("--floor-elevation-mm", "floor_elevation_mm"),
    ("--floor-height-mm", "floor_height_mm"),
    ("--clear-height-mm", "clear_height_mm"),
    ("--slab-thickness-mm", "slab_thickness_mm"),
    ("--ceiling-height-mm", "ceiling_height_mm"),
)
REMARK_STATUSES: Final = ("open", "resolved")


class CadOpsError(Exception):
    """Отказ команды сопровождения: причина — для человека в терминале."""


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# ------------------------------------------------------------------ замечания


async def list_remarks(
    session: AsyncSession,
    *,
    status: str | None,
    project_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Замечания всех пространств, новые сверху, с проектом, файлом ревизии и типом задания.

    `stale` — замечание к попытке, которая уже не текущая у задания: результат пересчитан, и
    замечание могло устареть.
    """
    if status is not None and status not in REMARK_STATUSES:
        raise CadOpsError(f"Статус замечания: {', '.join(REMARK_STATUSES)}")
    query = (
        select(CadRemark, Project.name, DocumentRevision.source_filename, Job)
        .join(Project, Project.id == CadRemark.project_id)
        .join(DocumentRevision, DocumentRevision.id == CadRemark.revision_id)
        .join(Job, Job.id == CadRemark.job_id)
        .order_by(CadRemark.updated_at.desc(), CadRemark.remark_key)
        .limit(limit)
    )
    if status is not None:
        query = query.where(CadRemark.status == status)
    if project_id is not None:
        query = query.where(CadRemark.project_id == project_id)
    if job_id is not None:
        query = query.where(CadRemark.job_id == job_id)
    rows = (await session.execute(query)).all()
    return [
        remark_view(remark, project_name=name, revision_file=filename, job=job)
        for remark, name, filename, job in rows
    ]


def remark_view(
    remark: CadRemark, *, project_name: str | None, revision_file: str | None, job: Job | None
) -> dict[str, Any]:
    current_attempt = cad_service.result_of(job).get("attempt") if job is not None else None
    return {
        "id": str(remark.id),
        "remark_key": remark.remark_key,
        "status": remark.status,
        "type": remark.type,
        "comment": remark.comment,
        "reviewer": remark.reviewer,
        "project_id": str(remark.project_id),
        "project_name": project_name,
        "revision_id": str(remark.revision_id),
        "revision_file": revision_file,
        "job_id": str(remark.job_id),
        "job_type": job.job_type.value if job is not None else None,
        "attempt": remark.attempt,
        "result_attempt": current_attempt,
        "stale": current_attempt is not None and current_attempt != remark.attempt,
        "page_index": remark.page_index,
        "legacy_pdf_page": remark.page_index + 1,
        "view": remark.view,
        "view_folder": cad_service.view_folder(remark.page_index, remark.view),
        "bbox_pt": [remark.bbox_x0, remark.bbox_y0, remark.bbox_x1, remark.bbox_y1],
        "coordinate_system": "pdf_pt_top_left",
        "dxf_sha256": remark.dxf_sha256,
        "created_at": _iso(remark.created_at),
        "updated_at": _iso(remark.updated_at),
    }


async def set_remark_status(
    session: AsyncSession, *, remark_id: uuid.UUID, status: str
) -> dict[str, Any]:
    """Меняет только статус; комментарий, рамка и автор замечания остаются как у человека."""
    if status not in REMARK_STATUSES:
        raise CadOpsError(f"Статус замечания: {', '.join(REMARK_STATUSES)}")
    remark = (
        await session.scalars(
            update(CadRemark)
            .where(CadRemark.id == remark_id)
            .values(status=status, updated_at=func.now())
            .returning(CadRemark)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if remark is None:
        raise CadOpsError(f"Замечание {remark_id} не найдено")
    job = await session.get(Job, remark.job_id)
    return remark_view(remark, project_name=None, revision_file=None, job=job)


# ------------------------------------------------------------------ выгрузка задания


@dataclass(frozen=True, slots=True)
class _Parent:
    job: Job
    attempt: int
    folder: str


def _artifacts(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = result.get("artifacts")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _safe_name(name: str) -> Path:
    """Имя артефакта — относительный путь без выхода из каталога выгрузки."""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise CadOpsError(f"Недопустимое имя артефакта: {name}")
    return path


async def _download(
    storage: ObjectStorage, key: str, target: Path, expected_sha256: str | None
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with target.open("xb") as sink:
        async for chunk in storage.iter_stream(key):
            digest.update(chunk)
            size += len(chunk)
            sink.write(chunk)
    sha = digest.hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise CadOpsError(f"SHA256 не совпал с итогом задания: {key}")
    return {"size": size, "sha256": sha}


async def _parent_of(session: AsyncSession, job: Job) -> _Parent | None:
    """Родитель-преобразование задания по виду: id, вид и попытка — из payload задания."""
    payload = job.payload
    try:
        parent_id = uuid.UUID(str(payload.get("parent_job_id")))
    except ValueError:
        return None
    page_index, view = payload.get("page_index"), payload.get("view")
    if type(page_index) is not int or type(view) is not int:
        return None
    parent = await session.get(Job, parent_id)
    if parent is None:
        return None
    attempt = payload.get("parent_attempt")
    if type(attempt) is not int:
        current = cad_service.result_of(parent).get("attempt")
        if type(current) is not int:
            return None
        attempt = current
    return _Parent(parent, attempt, cad_service.view_folder(page_index, view))


def _generator_flags(job: Job) -> list[str]:
    flags: list[str] = []
    for flag, key in MANUAL_FLAGS:
        value = job.payload.get(key)
        if type(value) is int:
            flags += [flag, str(value)]
    return flags


async def build_bundle(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    job_id: uuid.UUID,
    attempt: int | None,
    include_pdf: bool,
    target: Path,
) -> dict[str, Any]:
    """Пишет выгрузку задания в пустой каталог `target` и возвращает её опись (`job.json`)."""
    job = await session.get(Job, job_id)
    if job is None:
        raise CadOpsError(f"Задание {job_id} не найдено")
    revision_raw = job.payload.get("revision_id")
    if not isinstance(revision_raw, str) or "cad_result" not in job.payload:
        raise CadOpsError(f"Задание {job_id} ({job.job_type.value}) — не задание CAD с итогом")
    revision_id = uuid.UUID(revision_raw)
    attempt_no = attempt if attempt is not None else cad_service.result_of(job).get("attempt")
    if type(attempt_no) is not int:
        raise CadOpsError("У задания нет итога: укажите попытку")
    result = cad_service.result_for_attempt(job, attempt_no)
    if not result:
        raise CadOpsError(f"Итога попытки {attempt_no} у задания нет")

    files: dict[str, dict[str, Any]] = {}
    for item in _artifacts(result):
        name = str(item.get("name"))
        key = cad_service.artifact_storage_key(revision_id, job.id, attempt_no, name)
        if item.get("key") != key:
            raise CadOpsError(f"Ключ артефакта вне контракта: {name}")
        local = Path("out") / _safe_name(name)
        files[local.as_posix()] = await _download(
            storage, key, target / local, str(item.get("sha256"))
        )

    revision = await session.get(DocumentRevision, revision_id)
    if revision is None:
        raise CadOpsError(f"Ревизия {revision_id} не найдена")
    if include_pdf:
        files["in/source.pdf"] = await _download(
            storage, revision.storage_key, target / "in" / "source.pdf", revision.source_sha256
        )

    parent = await _parent_of(session, job)
    if parent is not None:
        for name in PARENT_VIEW_FILES:
            artifact = cad_service.find_artifact(
                parent.job, f"{parent.folder}/{name}", parent.attempt
            )
            if artifact is None:
                continue
            key = cad_service.artifact_storage_key(
                revision_id, parent.job.id, parent.attempt, f"{parent.folder}/{name}"
            )
            if artifact.get("key") != key:
                raise CadOpsError(f"Ключ артефакта родителя вне контракта: {name}")
            files[f"in/{name}"] = await _download(
                storage, key, target / "in" / name, str(artifact.get("sha256"))
            )

    risers = job.payload.get("risers")
    if isinstance(risers, list) and risers:
        data = cad_risers.registry_bytes(risers)
        if hashlib.sha256(data).hexdigest() != job.payload.get("risers_sha256"):
            raise CadOpsError("Реестр стояков в задании не совпал со своим sha256")
        (target / "in").mkdir(parents=True, exist_ok=True)
        (target / "in" / "risers.json").write_bytes(data)
        files["in/risers.json"] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    remarks = await list_remarks(session, status=None, job_id=job.id, limit=1000)
    (target / "remarks.json").write_text(
        json.dumps({"schema": REMARKS_SCHEMA, "remarks": remarks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    project = await session.get(Project, job.project_id) if job.project_id else None
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "job": {
            "id": str(job.id),
            "type": job.job_type.value,
            "status": job.status.value,
            "attempt": job.attempt,
            "bundle_attempt": attempt_no,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "created_at": _iso(job.created_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
        },
        "project": {"id": str(job.project_id), "name": project.name if project else None},
        "revision": {
            "id": str(revision.id),
            "file": revision.source_filename,
            "sha256": revision.source_sha256,
            "size": revision.source_size,
        },
        "parent": (
            {
                "job_id": str(parent.job.id),
                "attempt": parent.attempt,
                "view_folder": parent.folder,
            }
            if parent is not None
            else None
        ),
        "generator_flags": _generator_flags(job),
        "files": files,
        "remarks": len(remarks),
        "payload": job.payload,
    }
    (target / "job.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return manifest
