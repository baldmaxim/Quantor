"""Задание `cad_floor3d_dxf`: 3D-модель этажа в 3D DXF для AutoCAD (ADR-0036 п. 6, ADR-0039).

API собирает ту же модель этажа, что отдаёт `GET .../floor3d`, кладёт её JSON в хранилище как вход
и ставит задание. DXF пишет cad-worker скриптом `tools/cad_walls/run_floor3d_dxf.py` (ezdxf в
процессе API запрещён). Модуль стандартный: ни ezdxf, ни Shapely сюда не импортируются.

Вход адресуется содержимым: ключ объекта содержит sha256 канонического JSON модели, поэтому та же
модель — тот же объект, а повторная постановка находит прежнее задание.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_floor3d import CadFloor3dRead
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, http_error, not_found
from app.models import Job
from app.services import cad as cad_service
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage, StorageUnavailableError

# Версия скрипта `tools/cad_walls/cad_walls/floor3d_dxf.py` (`GENERATOR_VERSION`). В образе API
# файла скрипта нет, поэтому константа дублируется; исполнитель сверяет её с ответом скрипта, а
# тест репозитория — с исходником.
GENERATOR_VERSION: Final = "cad_floor3d_dxf.v2"
DXF_NAME: Final = "floor3d.dxf"
# Сколько раз за ту же модель можно заново ставить отказавшее или отменённое задание.
_MAX_SEQUENCE: Final = 20
_RETRY_STATUSES: Final = (JobStatus.FAILED, JobStatus.CANCELLED)


def model_bytes(model: CadFloor3dRead) -> bytes:
    """Канонический JSON модели: одна и та же модель даёт те же байты и тот же sha256."""
    return json.dumps(
        model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def model_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def input_key(revision_id: uuid.UUID, sha256: str) -> str:
    """Ключ входного объекта в хранилище; адрес по содержимому, вне каталогов попыток."""
    return f"revisions/{revision_id}/cad/floor3d-input/{sha256}.json"


def output_name(page_index: int, view: int) -> str:
    return f"{cad_service.view_folder(page_index, view)}/{DXF_NAME}"


def idempotency_key(
    parent_id: uuid.UUID,
    *,
    parent_attempt: int,
    page_index: int,
    view: int,
    sha256: str,
    sequence: int,
) -> str:
    """Тот же вид, модель и версия скрипта — то же задание; новая попытка после отказа — номер."""
    digest = hashlib.sha256(
        "|".join(
            (
                str(parent_id),
                str(parent_attempt),
                str(page_index),
                str(view),
                sha256,
                GENERATOR_VERSION,
                str(sequence),
            )
        ).encode()
    ).hexdigest()
    return f"cadfloor3ddxf:{digest[:48]}"


async def schedule(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    model: CadFloor3dRead,
) -> Job:
    """Кладёт модель в хранилище и ставит задание.

    Идемпотентно: пока есть задание с той же моделью и версией скрипта (в очереди, выполняется
    или успешное) — возвращается оно. Отказавшее или отменённое не мешает: ставится новое.
    """
    attempt = cad_service.result_of(parent).get("attempt")
    revision_id = parent.payload.get("revision_id")
    if type(attempt) is not int or not isinstance(revision_id, str):
        raise not_found("Задание")
    raw = model_bytes(model)
    sha256 = model_sha256(raw)
    key = input_key(uuid.UUID(revision_id), sha256)
    try:
        stored = await storage.put_bytes(
            key,
            raw,
            content_type="application/json",
            metadata={"sha256": sha256, "parent-job-id": str(parent.id)},
        )
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    if stored.sha256 != sha256 or stored.size != len(raw):
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "хранилище получило другую модель")

    sequence = 0
    while True:
        existing = await jobs_service.find_by_idempotency_key(
            session,
            idempotency_key=idempotency_key(
                parent.id,
                parent_attempt=attempt,
                page_index=page_index,
                view=view,
                sha256=sha256,
                sequence=sequence,
            ),
        )
        if existing is None or existing.status not in _RETRY_STATUSES or sequence >= _MAX_SEQUENCE:
            break
        sequence += 1
    if existing is not None:
        return existing
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_FLOOR3D_DXF,
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        idempotency_key=idempotency_key(
            parent.id,
            parent_attempt=attempt,
            page_index=page_index,
            view=view,
            sha256=sha256,
            sequence=sequence,
        ),
        payload={
            "revision_id": revision_id,
            "parent_job_id": str(parent.id),
            "parent_attempt": attempt,
            "page_index": page_index,
            "view": view,
            "model_sha256": sha256,
            "model_size": len(raw),
            "generator_version": GENERATOR_VERSION,
            "engine_version": GENERATOR_VERSION,
        },
    )
