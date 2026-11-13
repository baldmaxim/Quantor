"""PDF -> CAD (пилот, ADR-0036): постановка задания и доступ к артефактам.

Контракт — `docs/building-model/cad-engine-integration-contract.md`, исполнитель —
`app/cad_worker`, движок — отдельный процесс `tools/cad_engine/quantor_cad_runner.py` в своём
окружении. Этот модуль стандартный: ни PyMuPDF, ни Shapely, ни ezdxf сюда не импортируются.

Страницы: в Quantor `page_index` с 0 (как `Sheet.page_index`), legacy worker движка считает
страницы с 1; перевод `index + 1` делает только runner и пишет обе нумерации в отчёт.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Job, Project, ScaleCalibration, Sheet
from app.services import jobs as jobs_service

# Закрепление движка: архив сверяется и здесь (передаётся runner'у), и в tools/cad_engine/pins.json.
ENGINE_VERSION: Final = "2026.11.13+1afeca5f32b7"
ENGINE_ARCHIVE_SHA256: Final = "619c3910d0d07b7dfbf531ffa093484a95a0b9fb5acac8abff000b802d963888"
PARAMS_SCHEMA: Final = "quantor.cad_engine.params.v2"
PAGE_SELECTION: Final = "operator"
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
# Артефакты задания трасс механики (`cad_mep_route`, ADR-0036 п. 8): отчёт и манифест как у
# движка, плюс DXF трасс, кандидат и 3D-трассы (`routes3d.json`, ADR-0041) — в каталоге вида.
ROUTE_ARTIFACT_NAME: Final = re.compile(
    r"^(?:report\.json|manifest\.json|"
    r"views/p\d{3}_v\d{2}/(?:mep_routes\.dxf|candidate\.json|preview\.json|routes3d\.json))$"
)
# Артефакт задания конструкций (`cad_walls`, ADR-0038): один файл в каталоге вида.
WALLS_ARTIFACT_NAME: Final = re.compile(r"^views/p\d{3}_v\d{2}/walls\.json$")
# Артефакт задания 3D DXF этажа (`cad_floor3d_dxf`, ADR-0039): один файл в каталоге вида.
FLOOR3D_ARTIFACT_NAME: Final = re.compile(r"^views/p\d{3}_v\d{2}/floor3d\.dxf$")
# Артефакт задания автоматической разметки зон (`cad_zones`): один файл в каталоге вида.
ZONES_ARTIFACT_NAME: Final = re.compile(r"^views/p\d{3}_v\d{2}/zones\.json$")
# Артефакт задания «Разрезы» (`cad_sections`): один файл в корне артефактов задания.
SECTIONS_ARTIFACT_NAME: Final = re.compile(r"^sections\.json$")
# Артефакты задания ЭОМ и СС (`cad_eom_route`): отчёт, манифест и три файла в каталоге вида.
EOM_ARTIFACT_NAME: Final = re.compile(
    r"^(?:report\.json|manifest\.json|"
    r"views/p\d{3}_v\d{2}/(?:eom_routes\.dxf|eom_candidate\.json|eom_routes3d\.json))$"
)
CONTENT_TYPES: Final = {".dxf": "application/dxf", ".json": "application/json"}
# Типы заданий контура CAD: у обоих один и тот же вид доступа (пространство, проект, ревизия).
CAD_JOB_TYPES: Final = (JobType.CAD_PDF_CONVERT, JobType.CAD_MEP_ROUTE)
# Задания, чьи файлы отдаёт скачивание артефактов: к ним добавлено задание 3D DXF этажа. В список
# и историю заданий ревизии оно не входит (у него нет страниц и видов результата).
CAD_ARTIFACT_JOB_TYPES: Final = (*CAD_JOB_TYPES, JobType.CAD_FLOOR3D_DXF)


@dataclass(frozen=True, slots=True)
class PageScale:
    """Масштаб страницы от человека: калибровка листа (ADR-0018).

    `mm_per_pt` — реальные мм на 1 pt пространства страницы PDF (1/72 дюйма). Это ровно
    `ScaleCalibration.mm_per_pt` (мм известного размера / расстояние между точками в pt
    канонической геометрии): пересчёта не требуется. Для масштаба 1:N он равен
    `N * 25.4 / 72` (1:200 -> 70.5556 мм/pt).
    """

    mm_per_pt: float
    calibration_id: str


@dataclass(frozen=True, slots=True)
class AutoScale:
    """Лист без калибровки человека: масштаб определяет движок по размерным цепочкам (ADR-0045).

    Масштаб по надписи «М 1:NN» не принимается никогда (ADR-0018); если цепочки масштаб не
    подтвердили, задание падает с `CAD_AUTO_SCALE_UNCONFIRMED`.
    """


AUTO_SCALE: Final = AutoScale()
# Масштаб страницы в постановке: калибровка человека либо автоопределение движком.
ScaleChoice = PageScale | AutoScale


def page_scale_of(calibration: ScaleCalibration) -> PageScale:
    value = float(calibration.mm_per_pt)
    if not math.isfinite(value) or value <= 0:
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "Коэффициент калибровки вне допустимого")
    return PageScale(mm_per_pt=value, calibration_id=str(calibration.id))


def _scale_entry(scale: ScaleChoice) -> dict[str, Any]:
    if isinstance(scale, AutoScale):
        return {"auto": True}
    return {"mm_per_pt": scale.mm_per_pt, "calibration_id": scale.calibration_id}


def build_limits(settings: Settings) -> dict[str, int]:
    return {
        "max_pages": MAX_PAGES,
        "total_timeout_s": settings.cad_total_timeout_seconds,
        "max_memory_mb": settings.cad_max_memory_mb,
    }


def build_params(
    pages: list[int], scales: Mapping[int, ScaleChoice], settings: Settings
) -> dict[str, Any]:
    """Параметры движка v2. Отделка и ведомости объёмов выключены всегда.

    Лист выбирает человек (`page_selection=operator`), масштаб каждой страницы — его
    калибровка либо пометка `{"auto": true}` (движок определяет сам, ADR-0045). Ключ `scales` —
    индекс страницы с 0 строкой; идентификатор калибровки и пометка входят в параметры, поэтому
    новая калибровка или другой способ масштаба дают новый ключ идемпотентности.
    """
    ordered = sorted(pages)
    if set(scales) != set(ordered):
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "Масштаб нужен ровно для выбранных страниц")
    return {
        "schema": PARAMS_SCHEMA,
        "mode": "architecture",
        "pages": ordered,
        "page_selection": PAGE_SELECTION,
        "scales": {str(index): _scale_entry(scales[index]) for index in ordered},
        "finishes": False,
        "schedules": False,
        "limits": build_limits(settings),
    }


def params_bytes(params: dict[str, Any]) -> bytes:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def params_sha256(params: dict[str, Any]) -> str:
    return hashlib.sha256(params_bytes(params)).hexdigest()


def refresh_limits(job: Job, settings: Settings) -> None:
    """Повтор: лимиты задания берутся из текущих настроек, остальные параметры не меняются.

    Контрольная сумма параметров пересчитывается: исполнитель сверяет её с параметрами.
    Ключ идемпотентности не трогаем. Нет `params` или это не словарь — не трогаем (исполнитель
    сам отклонит задание).
    """
    payload = job.payload
    params = payload.get("params") if isinstance(payload, dict) else None
    if not isinstance(params, dict):
        return
    new_params = {**params, "limits": build_limits(settings)}
    job.payload = {**payload, "params": new_params, "params_sha256": params_sha256(new_params)}


def idempotency_key(revision_id: uuid.UUID, params: dict[str, Any]) -> str:
    """Тот же PDF, движок и параметры — то же задание; новый движок — новое."""
    return f"cad:{revision_id}:{ENGINE_VERSION}:{params_sha256(params)[:16]}"


def artifact_storage_key(revision_id: uuid.UUID, job_id: uuid.UUID, attempt: int, name: str) -> str:
    if attempt < 1 or not (
        ARTIFACT_NAME.fullmatch(name)
        or ROUTE_ARTIFACT_NAME.fullmatch(name)
        or WALLS_ARTIFACT_NAME.fullmatch(name)
        or FLOOR3D_ARTIFACT_NAME.fullmatch(name)
        or ZONES_ARTIFACT_NAME.fullmatch(name)
        or SECTIONS_ARTIFACT_NAME.fullmatch(name)
        or EOM_ARTIFACT_NAME.fullmatch(name)
    ):
        raise ValueError("недопустимое имя артефакта или номер попытки CAD")
    return f"revisions/{revision_id}/cad/{job_id}/attempt-{attempt}/{name}"


def content_type_for(name: str) -> str:
    return CONTENT_TYPES[name[name.rindex(".") :]]


def validate_request(pages: list[int], *, finishes: bool, schedules: bool) -> list[int]:
    """Проверка до постановки: параметры вне контракта задание не создают."""
    if finishes or schedules:
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID, "Отделка и ведомости объёмов в CAD выключены"
        )
    if not pages or len(set(pages)) != len(pages) or any(p < 0 for p in pages):
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID,
            "pages — непустой список индексов страниц с 0 без повторов",
        )
    if len(pages) > MAX_PAGES:
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


async def resolve_scales(
    session: AsyncSession,
    *,
    revision: DocumentRevision,
    pages: list[int],
    auto_scale: bool = False,
) -> dict[int, ScaleChoice]:
    """Масштаб каждой выбранной страницы: калибровка листа (ADR-0018) или автомасштаб.

    Страница ревизии — `Sheet` с тем же `page_index` (с 0); действующая калибровка — та, что
    помечена `is_default`; она берётся всегда. Нет листа или калибровки: при `auto_scale` страница
    идёт без масштаба человека (`AUTO_SCALE`, ADR-0045), иначе — 409 `CAD_CALIBRATION_REQUIRED`
    со списком таких страниц. Клиент масштаб не передаёт; `ScaleCalibration` не создаётся.
    """
    rows = await session.execute(
        select(Sheet.page_index, ScaleCalibration)
        .join(
            ScaleCalibration,
            (ScaleCalibration.sheet_id == Sheet.id) & ScaleCalibration.is_default.is_(True),
        )
        .where(Sheet.revision_id == revision.id, Sheet.page_index.in_(pages))
    )
    found: dict[int, ScaleChoice] = {
        index: page_scale_of(calibration) for index, calibration in rows.all()
    }
    missing = sorted(set(pages) - set(found))
    if missing and auto_scale:
        found.update(dict.fromkeys(missing, AUTO_SCALE))
    elif missing:
        raise DomainError(
            ErrorCode.CAD_CALIBRATION_REQUIRED,
            issue={"pages": ",".join(str(index) for index in missing)},
        )
    return found


async def schedule_convert(
    session: AsyncSession,
    *,
    project: Project,
    revision: DocumentRevision,
    pages: list[int],
    settings: Settings,
    auto_scale: bool = False,
) -> Job:
    if not is_pdf(revision):
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Источник ревизии не PDF")
    scales = await resolve_scales(session, revision=revision, pages=pages, auto_scale=auto_scale)
    params = build_params(pages, scales, settings)
    job = await jobs_service.enqueue(
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
    return await requeue_if_retryable_failure(session, job, settings=settings, refresh=True)


async def requeue_if_retryable_failure(
    session: AsyncSession, job: Job, *, settings: Settings, refresh: bool
) -> Job:
    """Повторная постановка по тому же ключу: упавшее повторяемо — новая попытка того же задания.

    `jobs.enqueue` идемпотентен при любом статусе и возвращает существующее задание; без этого
    «Преобразовать заново» после сбоя инфраструктуры возвращало бы то же упавшее задание.
    Неповторяемый отказ (детерминированный движок) возвращается как есть. Строка берётся под
    блокировкой: два одновременных запроса не ставят задание дважды. `refresh` — подтянуть
    лимиты из текущих настроек (преобразование; у трасс лимиты берутся при выполнении).
    """
    if job.status is not JobStatus.FAILED:
        return job
    await session.refresh(job, with_for_update=True)
    retryable, _reason = retry_state(job)
    if not retryable:
        return job
    if refresh:
        refresh_limits(job, settings)
    return await jobs_service.retry(session, job=job)


async def get_cad_job(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    job_types: tuple[JobType, ...] = CAD_JOB_TYPES,
) -> Job | None:
    """Задание CAD видно только в своём пространстве, проекте и ревизии; иначе — None (404)."""
    job = await jobs_service.get_job(session, workspace_id=workspace_id, job_id=job_id)
    if (
        job is None
        or job.job_type not in job_types
        or job.project_id != project_id
        or job.payload.get("revision_id") != str(revision_id)
    ):
        return None
    return job


def result_of(job: Job) -> dict[str, Any]:
    result = job.payload.get("cad_result")
    return result if isinstance(result, dict) else {}


def result_for_attempt(job: Job, attempt: int) -> dict[str, Any]:
    """Итог указанной попытки: текущий или сохранённый при пересчёте (`cad_results`).

    Прошлая попытка route-задания остаётся только для просмотра; итога нет - пустой словарь.
    """
    result = result_of(job)
    if result.get("attempt") == attempt:
        return result
    stash = job.payload.get("cad_results")
    row = stash.get(str(attempt)) if isinstance(stash, dict) else None
    return row if isinstance(row, dict) else {}


def find_artifact(job: Job, name: str, attempt: int | None = None) -> dict[str, Any] | None:
    """Файл итога: текущего или, если указана попытка, этой попытки."""
    result = result_of(job) if attempt is None else result_for_attempt(job, attempt)
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    for item in artifacts:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


# ------------------------------------------------------------------ интерфейс контура CAD

# Почему повтор не предлагается. Повтор — то же задание, новая попытка (jobs.retry); он
# разрешён только для отказов из jobs.RETRYABLE_ERROR_CODES: движок детерминирован, и тот же
# PDF с теми же параметрами даст тот же отказ.
_NOT_RETRYABLE_REASONS: Final = {
    ErrorCode.CAD_INPUT_INVALID.value: "PDF не прошёл входной контроль движка: повтор того же "
    "файла даст тот же отказ. Загрузите исправленный PDF новой ревизией.",
    ErrorCode.CAD_AUTO_SCALE_UNCONFIRMED.value: "Масштаб не подтверждён размерами чертежа: "
    "повтор даст тот же отказ. Откалибруйте лист вручную и преобразуйте заново.",
    ErrorCode.CAD_PARAMS_INVALID.value: "Параметры вне контракта или страница вне PDF: "
    "поставьте задание с другим выбором страниц.",
    ErrorCode.CAD_INPUT_LIMIT_EXCEEDED.value: "PDF превышает пределы преобразования: уменьшите "
    "число страниц.",
    ErrorCode.CAD_ENGINE_FAILED.value: "Движок детерминирован: на том же PDF и тех же "
    "параметрах повтор даст тот же результат.",
    ErrorCode.CAD_ENGINE_UNAVAILABLE.value: "Движок не установлен или не прошёл проверку: "
    "повтор возможен после исправления установки, через администратора.",
    ErrorCode.CAD_MEP_NOT_BUILT.value: "Генератор детерминирован: на том же виде и тех же "
    "параметрах он даст тот же отказ. Результат изменят другие отметки этажа или новая версия "
    "генератора.",
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
    page_index: int | None = None,
    limit: int = 20,
) -> list[Job]:
    """Задания CAD ревизии, новые сверху. Пространство и проект — в самом запросе.

    С `page_index` (с 0) — только задания этой страницы: преобразование, у которого страница
    входит в `params.pages`, и трассы MEP с `payload.page_index`. Фильтр в SQL: иначе при
    массовом прогоне задание листа не попадает в последние `limit` заданий всей ревизии.
    """
    conditions = [
        Job.workspace_id == workspace_id,
        Job.project_id == project_id,
        Job.job_type.in_(CAD_JOB_TYPES),
        Job.payload["revision_id"].astext == str(revision_id),
    ]
    if page_index is not None:
        conditions.append(
            or_(
                and_(
                    Job.job_type == JobType.CAD_PDF_CONVERT,
                    Job.payload["params"]["pages"].contains([page_index]),
                ),
                and_(
                    Job.job_type == JobType.CAD_MEP_ROUTE,
                    Job.payload["page_index"].astext == str(page_index),
                ),
            )
        )
    query = select(Job).where(*conditions).order_by(Job.created_at.desc()).limit(limit)
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
