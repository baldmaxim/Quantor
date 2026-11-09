"""PDF -> CAD в QA-контуре: постановка задания и доступ к артефактам.

Контракт — `docs/building-model/cad-engine-integration-contract.md`, исполнитель —
`app/cad_worker`, движок — отдельный процесс `tools/cad_engine/quantor_cad_runner.py` в своём
окружении. Этот модуль стандартный: ни PyMuPDF, ни Shapely, ни ezdxf сюда не импортируются.

Страницы: в Quantor `page_index` с 0 (как `Sheet.page_index`), legacy worker движка считает
страницы с 1; перевод `index + 1` делает только runner и пишет обе нумерации в отчёт.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Job, Project
from app.services import jobs as jobs_service

# Закрепление движка: архив сверяется и здесь (передаётся runner'у), и в tools/cad_engine/pins.json.
ENGINE_VERSION: Final = "2026.11.09+80cc6563f45a"
ENGINE_ARCHIVE_SHA256: Final = "2757a9edc2b95ae1a79b8915643d78b4a10801d8830b5f9d3514f31ee7890de4"
PARAMS_SCHEMA: Final = "quantor.cad_engine.params.v1"
MAX_PAGES: Final = 50

# Статусы результата. Ни один не означает «принято»: DXF — кандидат для проверки инженером.
RESULT_WITH_CAD: Final = "completed_requires_review"
RESULT_NO_CAD: Final = "no_cad_review_required"
RESULT_STATUSES: Final = frozenset({RESULT_WITH_CAD, RESULT_NO_CAD})

# Имена, которые runner может выдать. Всё прочее — нарушение контракта, а не новый файл.
ARTIFACT_NAME: Final = re.compile(
    r"^(?:report\.json|manifest\.json|"
    r"views/p\d{3}_v\d{2}/"
    r"(?:plan_candidates\.dxf|scale\.json|cad_checks\.json|checks\.json|preview\.json))$"
)
CONTENT_TYPES: Final = {".dxf": "application/dxf", ".json": "application/json"}


def build_params(pages: list[int] | None, settings: Settings) -> dict[str, Any]:
    """Параметры движка. Отделка и ведомости объёмов выключены всегда."""
    return {
        "schema": PARAMS_SCHEMA,
        "mode": "architecture",
        "pages": sorted(pages) if pages is not None else None,
        "finishes": False,
        "schedules": False,
        "limits": {
            "max_pages": MAX_PAGES,
            "total_timeout_s": settings.cad_total_timeout_seconds,
            "max_memory_mb": settings.cad_max_memory_mb,
        },
    }


def params_bytes(params: dict[str, Any]) -> bytes:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def params_sha256(params: dict[str, Any]) -> str:
    return hashlib.sha256(params_bytes(params)).hexdigest()


def idempotency_key(revision_id: uuid.UUID, params: dict[str, Any]) -> str:
    """Тот же PDF, движок и параметры — то же задание; новый движок — новое."""
    return f"cad:{revision_id}:{ENGINE_VERSION}:{params_sha256(params)[:16]}"


def artifact_storage_key(revision_id: uuid.UUID, job_id: uuid.UUID, attempt: int, name: str) -> str:
    if attempt < 1 or not ARTIFACT_NAME.fullmatch(name):
        raise ValueError("недопустимое имя артефакта или номер попытки CAD")
    return f"revisions/{revision_id}/cad/{job_id}/attempt-{attempt}/{name}"


def content_type_for(name: str) -> str:
    return CONTENT_TYPES[name[name.rindex(".") :]]


def validate_request(
    pages: list[int] | None, *, finishes: bool, schedules: bool
) -> list[int] | None:
    """Проверка до постановки: параметры вне контракта задание не создают."""
    if finishes or schedules:
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID, "Отделка и ведомости объёмов в CAD выключены"
        )
    if pages is not None and (
        not pages or len(set(pages)) != len(pages) or any(p < 0 for p in pages)
    ):
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID, "pages — null или непустой список индексов с 0"
        )
    if pages is not None and len(pages) > MAX_PAGES:
        raise DomainError(ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, f"Не больше {MAX_PAGES} страниц")
    return pages


def is_pdf(revision: DocumentRevision) -> bool:
    return revision.source_mime == "application/pdf" or revision.source_filename.lower().endswith(
        ".pdf"
    )


async def revision_in_project(
    session: AsyncSession, *, project: Project, revision_id: uuid.UUID
) -> DocumentRevision | None:
    revision = await session.get(DocumentRevision, revision_id)
    if revision is None:
        return None
    document = await session.get(Document, revision.document_id)
    if document is None or document.project_id != project.id:
        return None
    return revision


async def schedule_convert(
    session: AsyncSession,
    *,
    project: Project,
    revision: DocumentRevision,
    pages: list[int] | None,
    settings: Settings,
) -> Job:
    if not is_pdf(revision):
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Источник ревизии не PDF")
    params = build_params(pages, settings)
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_PDF_CONVERT,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=idempotency_key(revision.id, params),
        payload={
            "revision_id": str(revision.id),
            "params": params,
            "params_sha256": params_sha256(params),
            "engine_version": ENGINE_VERSION,
            "engine_archive_sha256": ENGINE_ARCHIVE_SHA256,
        },
    )


async def get_cad_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Задание CAD видно только в своём пространстве, проекте и ревизии; иначе — None (404)."""
    job = await jobs_service.get_job(session, workspace_id=workspace_id, job_id=job_id)
    if (
        job is None
        or job.job_type is not JobType.CAD_PDF_CONVERT
        or job.project_id != project_id
        or job.payload.get("revision_id") != str(revision_id)
    ):
        return None
    return job


def result_of(job: Job) -> dict[str, Any]:
    result = job.payload.get("cad_result")
    return result if isinstance(result, dict) else {}


def find_artifact(job: Job, name: str) -> dict[str, Any] | None:
    artifacts = result_of(job).get("artifacts")
    if not isinstance(artifacts, list):
        return None
    for item in artifacts:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


# ------------------------------------------------------------------ интерфейс QA-контура

# Почему повтор не предлагается. Повтор — то же задание, новая попытка (jobs.retry); он
# разрешён только для отказов из jobs.RETRYABLE_ERROR_CODES: движок детерминирован, и тот же
# PDF с теми же параметрами даст тот же отказ.
_NOT_RETRYABLE_REASONS: Final = {
    ErrorCode.CAD_INPUT_INVALID.value: "PDF не прошёл входной контроль движка: повтор того же "
    "файла даст тот же отказ. Загрузите исправленный PDF новой ревизией.",
    ErrorCode.CAD_PARAMS_INVALID.value: "Параметры вне контракта или страницы вне перечня "
    "плановых листов: поставьте задание с другим выбором страниц.",
    ErrorCode.CAD_INPUT_LIMIT_EXCEEDED.value: "PDF превышает пределы преобразования: уменьшите "
    "число страниц.",
    ErrorCode.CAD_ENGINE_FAILED.value: "Движок детерминирован: на том же PDF и тех же "
    "параметрах повтор даст тот же результат.",
    ErrorCode.CAD_ENGINE_UNAVAILABLE.value: "Движок не установлен или не прошёл проверку: "
    "повтор возможен после исправления установки, через администратора.",
}


def retry_state(job: Job) -> tuple[bool, str | None]:
    """Можно ли повторить задание из интерфейса и, если нет, — почему."""
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return False, "Задание ещё в очереди или выполняется."
    if job.status is JobStatus.SUCCEEDED:
        return False, (
            "Попытка завершена успешно: результат неизменен. Новый прогон — новая ревизия PDF "
            "или другой выбор страниц."
        )
    if job.status is JobStatus.CANCELLED:
        return False, "Задание отменено."
    if jobs_service.is_retryable(job):
        return True, None
    code = job.error_code or ""
    return False, _NOT_RETRYABLE_REASONS.get(
        code, f"Отказ {code or 'без кода'} повтором не чинится."
    )


async def list_cad_jobs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    limit: int = 20,
) -> list[Job]:
    """Задания CAD ревизии, новые сверху. Пространство и проект — в самом запросе."""
    query = (
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_PDF_CONVERT,
            Job.payload["revision_id"].astext == str(revision_id),
        )
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


def current_result(job: Job) -> dict[str, Any]:
    """Результат только текущей попытки. Итог прошлой попытки текущим не выдаётся."""
    # Повтор возвращает задание в очередь, а номер попытки растёт только при захвате:
    # у поставленного задания текущего итога нет, итог прошлой попытки — только в истории.
    if job.status is JobStatus.QUEUED:
        return {}
    result = result_of(job)
    return result if result.get("attempt") == job.attempt else {}


def view_folder(page_index: int, view: int) -> str:
    """Каталог вида в артефактах: legacy-номер страницы с 1, вид с 1 (как у runner)."""
    if page_index < 0 or page_index > 998 or view < 0 or view > 99:
        raise ValueError("недопустимый номер страницы или вида")
    return f"views/p{page_index + 1:03d}_v{view:02d}"


# Ограничение для JSON-артефактов, которые сервер разбирает сам: диагностика вида и превью.
MAX_JSON_ARTIFACT_BYTES: Final = 32 * 1024 * 1024
