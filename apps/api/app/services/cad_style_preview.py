"""Предпросмотр профиля оформления по образцам и его принятие (ADR-0049, решения 3-7).

Сервер ничего не снимает: щелчки-образцы уходят заданием `cad_style_preview` в исполнитель CAD,
скрипт движка читает векторы листа и возвращает кандидат профиля и предпросмотр. Профиль тома
появляется только когда человек принял результат: тело берётся из результата доверенного
исполнителя, не от клиента, и проходит тот же строгий контракт, что ручная запись.

Масштаб листа - только из калибровки человека или из масштаба преобразования по размерным цепочкам
(`dimension_checks_passed`, ADR-0045); иначе `null`, площади в предпросмотре не считаются.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_style_profiles import (
    CadStylePreviewRead,
    CadStylePreviewResult,
    CadStyleProfileBody,
    CadStyleSample,
    CadStyleSamplesSource,
    CadStyleVersionFromPreview,
    CadStyleVersionRead,
    CadStyleVersionWrite,
)
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job, Project, ScaleCalibration, Sheet
from app.services import cad as cad_service
from app.services import cad_style_profiles, cad_views
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

# Предел размера предпросмотра в payload задания: он малый JSON (классы, предупреждения, источники
# полей); больше - признак порчи, а не данных (ограничение Quantor, не контракт движка).
PREVIEW_MAX_BYTES: Final = 256 * 1024
SCALE_CALIBRATION: Final = "calibration"
SCALE_CAD_AUTO: Final = "cad_auto"
SCALE_NONE: Final = "none"
_AUTO_SCALE_STATUS: Final = "dimension_checks_passed"
_AUTO_SCALE_SOURCE: Final = "dimension_chains"
# Виды одного листа, прошедшие проверку, должны давать один масштаб; расхождение свыше 0.1 % -
# масштаб листа не определён, молча выбирать один из видов нельзя.
_AUTO_SCALE_REL_TOLERANCE: Final = 1e-3


def _positive(value: float | None) -> float | None:
    if value is not None and math.isfinite(value) and value > 0:
        return value
    return None


async def _read_scale_json(
    storage: ObjectStorage, job: Job, revision_id: uuid.UUID, attempt: int, folder: str
) -> Any:
    name = f"{folder}/scale.json"
    artifact = cad_service.find_artifact(job, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    if artifact.get("key") != key:
        return None
    try:
        return await cad_views.read_json(storage, key)
    except ObjectNotFoundError:
        return None
    except StorageUnavailableError as error:
        raise DomainError(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (cad_views.ArtifactTooLargeError, ValueError):
        return None


async def _auto_scale(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project: Project,
    revision: DocumentRevision,
    page_index: int,
) -> float | None:
    """Масштаб листа по размерным цепочкам - как в гейте преобразования (ADR-0045).

    Берётся только последнее успешное преобразование, в котором лист есть в `params.pages`, и
    только если этот лист шёл без калибровки человека (`params.scales[лист] = {"auto": true}`);
    масштаб подтверждает вид со статусом `dimension_checks_passed` и источником
    `dimension_chains`. Иначе - нет масштаба: старые преобразования не перебираются.
    """
    job = (
        await session.execute(
            select(Job)
            .where(
                Job.workspace_id == project.workspace_id,
                Job.project_id == project.id,
                Job.job_type == JobType.CAD_PDF_CONVERT,
                Job.status == JobStatus.SUCCEEDED,
                Job.payload["revision_id"].astext == str(revision.id),
                Job.payload["params"]["pages"].contains([page_index]),
            )
            .order_by(Job.created_at.desc(), Job.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None or page_index not in auto_pages(job):
        return None
    result = cad_service.current_result(job)
    attempt = result.get("attempt")
    if type(attempt) is not int:
        return None
    values: list[float] = []
    for page in result.get("pages", []):
        if not isinstance(page, dict) or page.get("index") != page_index:
            continue
        for view in page.get("views", []):
            if (
                not isinstance(view, dict)
                or type(view.get("view")) is not int
                or view.get("scale_status") != _AUTO_SCALE_STATUS
                or view.get("scale_source") != _AUTO_SCALE_SOURCE
            ):
                continue
            try:
                folder = cad_service.view_folder(page_index, int(view["view"]))
            except ValueError:
                return None
            scale = cad_views.scale_from(
                await _read_scale_json(storage, job, revision.id, attempt, folder)
            )
            if scale is None or scale.status != _AUTO_SCALE_STATUS:
                continue
            factor = _positive(scale.mm_per_pdf_point)
            if factor is not None:
                values.append(factor)
    if values and all(
        math.isclose(v, values[0], rel_tol=_AUTO_SCALE_REL_TOLERANCE) for v in values
    ):
        return values[0]
    return None


def auto_pages(job: Job) -> list[int]:
    """Страницы преобразования без калибровки человека: `scales[i] == {"auto": true}`."""
    params = job.payload.get("params")
    scales = params.get("scales") if isinstance(params, dict) else None
    if not isinstance(scales, dict):
        return []
    return [
        int(key)
        for key, entry in scales.items()
        if isinstance(entry, dict) and entry.get("auto") is True and str(key).isdigit()
    ]


async def resolve_scale(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project: Project,
    revision: DocumentRevision,
    page_index: int,
) -> tuple[float | None, str]:
    """(мм на точку PDF, источник): калибровка листа, затем автомасштаб, иначе (None, none)."""
    calibration = (
        await session.execute(
            select(ScaleCalibration)
            .join(Sheet, ScaleCalibration.sheet_id == Sheet.id)
            .where(
                Sheet.revision_id == revision.id,
                Sheet.page_index == page_index,
                ScaleCalibration.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if calibration is not None:
        return cad_service.page_scale_of(calibration).mm_per_pt, SCALE_CALIBRATION
    auto = await _auto_scale(
        session, storage, project=project, revision=revision, page_index=page_index
    )
    if auto is not None:
        return auto, SCALE_CAD_AUTO
    return None, SCALE_NONE


def _payload_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def schedule(
    session: AsyncSession,
    *,
    project: Project,
    revision: DocumentRevision,
    samples: list[CadStyleSample],
    page_index: int,
    mm_per_pt: float | None,
    scale_source: str,
    base_version: int | None,
    settings: Settings,
) -> Job:
    """Задание предпросмотра; тот же вход (образцы, лист, масштаб, база, движок) - то же задание."""
    if not cad_service.is_pdf(revision):
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Источник ревизии не PDF")
    payload: dict[str, object] = {
        "document_id": str(revision.document_id),
        "revision_id": str(revision.id),
        "page_index": page_index,
        "samples": [item.model_dump(mode="json", by_alias=True) for item in samples],
        "mm_per_pt": mm_per_pt,
        "scale_source": scale_source,
        "base_version": base_version,
        "engine_version": cad_service.ENGINE_VERSION,
        "engine_archive_sha256": cad_service.ENGINE_ARCHIVE_SHA256,
    }
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_STYLE_PREVIEW,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=f"cad-style:{revision.document_id}:{_payload_hash(payload)[:32]}",
        payload=payload,
    )
    return await cad_service.requeue_if_retryable_failure(
        session, job, settings=settings, refresh=False
    )


async def get_preview_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Задание видно только своего пространства, проекта, тома и типа; иначе None (404)."""
    job = await jobs_service.get_job(session, workspace_id=workspace_id, job_id=job_id)
    if (
        job is None
        or job.job_type is not JobType.CAD_STYLE_PREVIEW
        or job.project_id != project_id
        or job.payload.get("document_id") != str(document_id)
    ):
        return None
    return job


def _result_of(job: Job) -> CadStylePreviewResult | None:
    result = cad_service.current_result(job)
    if job.status is not JobStatus.SUCCEEDED or not result:
        return None
    try:
        return CadStylePreviewResult.model_validate(result)
    except ValidationError as error:
        raise DomainError(
            ErrorCode.CAD_ENGINE_FAILED, "Результат предпросмотра вне контракта"
        ) from error


def read_of(job: Job) -> CadStylePreviewRead:
    return CadStylePreviewRead(
        job_id=job.id,
        status=job.status,
        error_code=job.error_code,
        error_message=job.error_message,
        result=_result_of(job),
    )


async def accept(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    job: Job,
    body: CadStyleVersionFromPreview,
    created_by: uuid.UUID | None,
) -> CadStyleVersionRead:
    """Новая версия профиля тома из результата предпросмотра."""
    result = _result_of(job)
    if result is None or result.result_status != "profile" or result.profile is None:
        raise DomainError(ErrorCode.CAD_STYLE_PREVIEW_NOT_READY)
    current = await cad_style_profiles.current_version(
        session, workspace_id=workspace_id, document_id=document_id
    )
    # Предпросмотр снят поверх `base_version`: профиль с тех пор изменился - он устарел.
    if result.base_version != body.expected_current_version or result.base_version != current:
        raise cad_style_profiles.conflict(current)
    try:
        profile = CadStyleProfileBody.model_validate(result.profile)
    except ValidationError as error:
        # Результат, подменённый после исполнителя, принять нельзя: как «профиля нет».
        raise DomainError(ErrorCode.CAD_STYLE_PREVIEW_NOT_READY) from error
    try:
        source = CadStyleSamplesSource.model_validate(
            {
                "kind": "samples",
                "revision_id": result.revision_id,
                "page_index": result.page_index,
                "samples": job.payload.get("samples"),
                "mm_per_pt": result.mm_per_pt,
            }
        )
    except ValidationError as error:
        raise DomainError(
            ErrorCode.CAD_ENGINE_FAILED, "Образцы задания предпросмотра вне контракта"
        ) from error
    return await cad_style_profiles.create_version(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        body=CadStyleVersionWrite(
            title=body.title,
            profile=profile,
            source=source,
            expected_current_version=body.expected_current_version,
        ),
        created_by=created_by,
        preview_job_id=job.id,
    )
