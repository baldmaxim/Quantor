"""Автоход петли ИИ-обводки пилота `cad_ai_loop`: оформление, правщик, перестроение, проверщик.

Человек в петле - только приёмка. Каждый переход ставит новое задание в той же транзакции, что и
успех предыдущего (как `cad_walls.enqueue_after_convert`); любой сбой постановки (в том числе
отказ домена) откатывается савепоинтом и родителя не роняет. Повторов упавших заданий автоход не
делает: упавшее звено оставляет цепочку на месте до решения человека.

```text
convert (первое, без подсказок) -> style (по виду) -> classes? -> convert с hatch_classes
convert/walls -> corrector (<= max_iterations на вид) -> needs_correction ->
  open missing_wall/missing_door -> convert с подсказками (+ классы + перенос замечаний)
  иначе open false_wall -> walls по замечаниям (cad_walls --hints)
  иначе -> verifier
corrector ready_for_human_review или круги исчерпаны -> verifier
```

Круг считается по виду всей цепочки преобразований листа (ревизия, страница, вид), а не по
одному заданию конструкций. Модель только классифицирует подписи и находит замечания; метры,
площади и объёмы считает движок.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from typing import Any, Final

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import MAX_COMMENT_LENGTH, CadRemarkWrite
from app.contracts.cad_ai_review import AiLoopPilot, AiReviewResult
from app.contracts.cad_ai_style import AiStyleResult
from app.contracts.cad_convert_hints import CadHatchClass
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import CadRemark, Job
from app.services import cad as cad_service
from app.services import cad_convert_hints, cad_remarks, cad_walls
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

# Сбой хука автохода не должен откатывать успех родительского задания: хранилище, HTTP-ошибки
# подготовки зон и битые полезные нагрузки ловятся наравне с ошибками домена и базы.
_HOOK_ERRORS: Final = (
    DomainError,
    SQLAlchemyError,
    ValueError,
    KeyError,
    HTTPException,
    StorageUnavailableError,
)

STYLE_ROLE: Final = "style"
LOOP_KEY: Final = "ai_loop"
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)
_OPEN: Final = "open"
# Замечания пишет система (ИИ), а не пользователь портала: автор - нулевой идентификатор.
SYSTEM_USER: Final = uuid.UUID(int=0)
_CONFIDENT: Final = ("high", "medium")
SIGNATURES_NAME: Final = "hatch_signatures.json"


def pilot_for_project(project_id: uuid.UUID | None, settings: Settings) -> AiLoopPilot | None:
    """Пилот ИИ из настройки `cad_ai_loop`, если он включён для этого проекта; иначе None."""
    if project_id is None or not settings.cad_ai_loop:
        return None
    try:
        pilot = AiLoopPilot.model_validate_json(settings.cad_ai_loop)
    except ValidationError:
        log.error("cad_ai_loop_pilot_invalid")
        return None
    return pilot if pilot.project_id == project_id else None


# ------------------------------------------------------------------ чтение цепочки


def _convert_hints_of(job: Job) -> dict[str, Any] | None:
    params = job.payload.get("params")
    hints = params.get("convert_hints") if isinstance(params, dict) else None
    return hints if isinstance(hints, dict) else None


def is_first_convert(job: Job) -> bool:
    """Преобразование без подсказок: исходный прогон листа, а не перестроение."""
    return _convert_hints_of(job) is None


def _loop_marker(job: Job) -> dict[str, Any]:
    marker = job.payload.get(LOOP_KEY)
    return marker if isinstance(marker, dict) else {}


def _with_marker(job: Job, **fields: Any) -> None:
    job.payload = {**job.payload, LOOP_KEY: {**_loop_marker(job), **fields}}


def _view_of(job: Job) -> tuple[int, int] | None:
    page_index, view = job.payload.get("page_index"), job.payload.get("view")
    if type(page_index) is not int or type(view) is not int:
        result = cad_service.result_of(job)
        page_index, view = result.get("page_index"), result.get("view")
    if type(page_index) is not int or type(view) is not int:
        return None
    return page_index, view


async def _style_jobs(session: AsyncSession, convert: Job, page_index: int) -> list[Job]:
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.project_id == convert.project_id,
            Job.payload["role"].astext == STYLE_ROLE,
            Job.payload["cad_job_id"].astext == str(convert.id),
            Job.payload["page_index"].astext == str(page_index),
        )
        .order_by(Job.created_at.desc(), Job.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _chain_reviews(
    session: AsyncSession, *, project_id: uuid.UUID, revision_id: str, page_index: int, view: int
) -> list[Job]:
    """Проверки правщика и проверщика вида по всей цепочке преобразований: новые первыми."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.project_id == project_id,
            Job.payload["role"].astext.in_(("corrector", "verifier")),
            Job.payload["revision_id"].astext == revision_id,
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    return list(rows)


def _of_role(jobs: Iterable[Job], role: str) -> list[Job]:
    return [job for job in jobs if job.payload.get("role") == role]


def _style_result(job: Job) -> AiStyleResult | None:
    raw = job.payload.get("ai_style")
    if job.status is not JobStatus.SUCCEEDED or not isinstance(raw, dict):
        return None
    try:
        return AiStyleResult.model_validate(raw)
    except ValidationError:
        return None


def merge_classes(results: Sequence[AiStyleResult]) -> list[CadHatchClass]:
    """Классы подписей видов страницы -> один список для преобразования страницы.

    Уверенность `low` отбрасывается. Подпись с теми же числами, но разным классом у разных видов
    считается спорной и не передаётся. Больше 20 - берутся первые по порядку видов.
    """
    chosen: dict[tuple[float, ...], tuple[str, CadHatchClass]] = {}
    disputed: set[tuple[float, ...]] = set()
    for result in results:
        for item in result.classes:
            if item.confidence not in _CONFIDENT:
                continue
            key = (*(round(value, 3) for value in item.color), round(item.pen_pt, 3))
            key = (*key, round(item.angle_deg, 1), round(item.pitch_pt, 2))
            hatch = CadHatchClass.model_validate(
                {
                    "signature_id": item.signature_id,
                    "color": list(item.color),
                    "pen_pt": item.pen_pt,
                    "angle_deg": item.angle_deg,
                    "pitch_pt": item.pitch_pt,
                    "class": item.class_name,
                }
            )
            known = chosen.get(key)
            if known is None:
                chosen[key] = (item.class_name, hatch)
            elif known[0] != item.class_name:
                disputed.add(key)
    classes = [pair[1] for key, pair in chosen.items() if key not in disputed]
    return classes[:20]


# ------------------------------------------------------------------ звено 1: оформление


def _result_views(convert: Job) -> list[tuple[int, int]]:
    """Виды результата преобразования, у которых есть DXF."""
    views: list[tuple[int, int]] = []
    for page in cad_service.result_of(convert).get("pages", []):
        for row in page.get("views", []):
            page_index, view = page.get("index"), row.get("view")
            if type(page_index) is not int or type(view) is not int:
                continue
            if cad_walls.view_has_dxf(convert, page_index, view) is not None:
                views.append((page_index, view))
    return views


def _plan_views(convert: Job) -> list[tuple[int, int]]:
    """Виды результата преобразования, у которых есть DXF и статистика подписей."""
    return [
        (page_index, view)
        for page_index, view in _result_views(convert)
        if cad_service.find_artifact(
            convert, f"{cad_service.view_folder(page_index, view)}/{SIGNATURES_NAME}"
        )
        is not None
    ]


async def _enqueue_style(
    session: AsyncSession, convert: Job, pilot: AiLoopPilot, page_index: int, view: int
) -> Job:
    attempt = cad_service.result_of(convert).get("attempt")
    payload: dict[str, object] = {
        "role": STYLE_ROLE,
        "cad_job_id": str(convert.id),
        "cad_attempt": attempt,
        "revision_id": str(convert.payload.get("revision_id")),
        "page_index": page_index,
        "pdf_page": page_index + 1,
        "view": view,
        "iteration": 1,
        "model": pilot.model,
        "sources": pilot.sources,
    }
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_AI_REVIEW,
        project_id=convert.project_id,
        workspace_id=convert.workspace_id,
        idempotency_key=f"cad-ai-style:v1:{convert.id}:{attempt}:{page_index}:{view}",
        payload=payload,
    )


async def carry_remarks(session: AsyncSession, new_convert: Job, source: dict[str, Any]) -> int:
    """Открытые ИИ-замечания вида со старого преобразования - на новое (ключи `carry-…`).

    Движок строит заново из PDF: без переноса подсказки прежних кругов (и находки `false_wall`)
    потерялись бы. Замечания пишутся на попытку нового задания с DXF нового результата.
    """
    try:
        old_id = uuid.UUID(str(source.get("job_id")))
    except ValueError:
        return 0
    old_attempt = source.get("attempt")
    new_attempt = cad_service.result_of(new_convert).get("attempt")
    if type(old_attempt) is not int or type(new_attempt) is not int:
        return 0
    copied = 0
    for page_index, view in _result_views(new_convert):
        artifact = cad_service.find_artifact(
            new_convert, f"{cad_service.view_folder(page_index, view)}/plan_candidates.dxf"
        )
        rows = await session.scalars(
            select(CadRemark)
            .where(
                CadRemark.job_id == old_id,
                CadRemark.attempt == old_attempt,
                CadRemark.page_index == page_index,
                CadRemark.view == view,
                CadRemark.status == _OPEN,
                CadRemark.created_by == SYSTEM_USER,
            )
            .order_by(CadRemark.created_at, CadRemark.remark_key)
        )
        for row in rows:
            key = (
                "carry-"
                + hashlib.sha1(f"{row.remark_key}:{new_convert.id}".encode()).hexdigest()[:20]  # noqa: S324
            )
            body = CadRemarkWrite.model_validate(
                {
                    "type": row.type,
                    "comment": row.comment[:MAX_COMMENT_LENGTH],
                    "reviewer": row.reviewer or "",
                    "status": _OPEN,
                    "bbox_pt": [row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1],
                    "dxf_sha256": str(artifact["sha256"]) if artifact is not None else None,
                }
            )
            await cad_remarks.upsert_remark(
                session,
                job=new_convert,
                attempt=new_attempt,
                page_index=page_index,
                view=view,
                remark_key=key,
                body=body,
                user_id=SYSTEM_USER,
            )
            copied += 1
    return copied


# ------------------------------------------------------------------ постановка проверок


async def _latest_walls(
    session: AsyncSession, convert: Job, page_index: int, view: int
) -> Job | None:
    """Последнее успешное задание конструкций вида преобразования (свежее состояние из базы)."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_WALLS,
            Job.workspace_id == convert.workspace_id,
            Job.payload["parent_job_id"].astext == str(convert.id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return rows.first()


async def _walls_context(session: AsyncSession, walls: Job) -> tuple[Job, int, int] | None:
    """Преобразование-родитель и вид задания конструкций."""
    position = _view_of(walls)
    try:
        parent_id = uuid.UUID(str(walls.payload.get("parent_job_id")))
    except ValueError:
        return None
    convert = await session.get(Job, parent_id)
    if convert is None or position is None or convert.job_type is not JobType.CAD_PDF_CONVERT:
        return None
    return convert, position[0], position[1]


async def _start_verifier(
    session: AsyncSession, walls: Job, convert: Job, pilot: AiLoopPilot, settings: Settings
) -> Job | None:
    from app.cad_worker import ai_review  # цикл: handler -> ai_loop -> ai_review

    position = _view_of(walls)
    if position is None or walls.project_id is None:
        return None
    reviews = await _chain_reviews(
        session,
        project_id=walls.project_id,
        revision_id=str(convert.payload.get("revision_id")),
        page_index=position[0],
        view=position[1],
    )
    verifiers = _of_role(reviews, "verifier")
    if any(job.payload.get("walls_job_id") == str(walls.id) for job in verifiers):
        return None
    if len(verifiers) >= pilot.max_iterations:
        return None
    return await ai_review.enqueue_for_walls(
        session, walls, settings, "verifier", iteration=len(verifiers) + 1
    )


async def _start_corrector(
    session: AsyncSession, walls: Job, convert: Job, pilot: AiLoopPilot, settings: Settings
) -> Job | None:
    """Правщик по заданию конструкций; круги считаются по виду всей цепочки преобразований."""
    from app.cad_worker import ai_review  # цикл: handler -> ai_loop -> ai_review

    position = _view_of(walls)
    if position is None or walls.project_id is None:
        return None
    reviews = await _chain_reviews(
        session,
        project_id=walls.project_id,
        revision_id=str(convert.payload.get("revision_id")),
        page_index=position[0],
        view=position[1],
    )
    correctors = _of_role(reviews, "corrector")
    if any(job.payload.get("walls_job_id") == str(walls.id) for job in correctors):
        return None
    rebuilt = _loop_marker(walls).get("rebuild_of") is not None
    if not rebuilt and any(job.payload.get("cad_job_id") == str(convert.id) for job in correctors):
        # Второе задание конструкций того же преобразования (пересчёт после авто-зон): правщик
        # у этого преобразования уже был, второго круга пересчёт не порождает.
        return None
    if len(correctors) >= pilot.max_iterations:
        return await _start_verifier(session, walls, convert, pilot, settings)
    return await ai_review.enqueue_for_walls(
        session, walls, settings, "corrector", iteration=len(correctors) + 1
    )


# ------------------------------------------------------------------ хуки автохода


async def after_convert(session: AsyncSession, convert: Job, settings: Settings) -> None:
    """Успех `cad_pdf_convert`: перенос замечаний; у первого прогона плана - роль «оформление»."""
    try:
        await _after_convert_impl(session, convert, settings)
    except _HOOK_ERRORS:
        log.warning("ai_loop_hook_failed", hook="after_convert", job_id=str(convert.id))


async def _after_convert_impl(session: AsyncSession, convert: Job, settings: Settings) -> None:
    pilot = pilot_for_project(convert.project_id, settings)
    if pilot is None or convert.job_type is not JobType.CAD_PDF_CONVERT:
        return
    carry = _loop_marker(convert).get("carry_from")
    if isinstance(carry, dict):
        try:
            async with session.begin_nested():
                await carry_remarks(session, convert, carry)
        except _HOOK_ERRORS:
            log.warning("ai_loop_carry_failed", job_id=str(convert.id))
    if not is_first_convert(convert):
        return
    not_plans = await cad_walls._not_plan_pages(session, convert)
    for page_index, view in _plan_views(convert):
        if page_index in not_plans:
            continue
        try:
            async with session.begin_nested():
                await _enqueue_style(session, convert, pilot, page_index, view)
        except _HOOK_ERRORS:
            log.warning("ai_loop_style_enqueue_failed", job_id=str(convert.id), view=view)


def _classes_reconvert_params(
    convert: Job, page_index: int, classes: list[CadHatchClass]
) -> dict[str, Any]:
    return cad_convert_hints.reconvert_params(convert, page_index, hints=[], hatch_classes=classes)


async def _classes_reconvert_exists(
    session: AsyncSession, convert: Job, page_index: int, classes: list[CadHatchClass]
) -> bool:
    """Есть ли уже задание преобразования с классами оформления этой страницы (по ключу)."""
    params = _classes_reconvert_params(convert, page_index, classes)
    key = cad_service.idempotency_key(uuid.UUID(str(convert.payload["revision_id"])), params)
    return await jobs_service.find_by_idempotency_key(session, idempotency_key=key) is not None


async def after_style(session: AsyncSession, style: Job, settings: Settings) -> None:
    """Успех роли «оформление»: классы -> преобразование с `hatch_classes`, иначе сразу правщик."""
    try:
        await _after_style_impl(session, style, settings)
    except _HOOK_ERRORS:
        log.warning("ai_loop_hook_failed", hook="after_style", job_id=str(style.id))


async def _after_style_impl(session: AsyncSession, style: Job, settings: Settings) -> None:
    pilot = pilot_for_project(style.project_id, settings)
    if pilot is None or style.payload.get("role") != STYLE_ROLE:
        return
    async with session.begin_nested():
        await _after_style(session, style, pilot, settings)


async def _after_style(
    session: AsyncSession, style: Job, pilot: AiLoopPilot, settings: Settings
) -> None:
    convert = await session.get(Job, uuid.UUID(str(style.payload.get("cad_job_id"))))
    page_index = style.payload.get("page_index")
    if convert is None or type(page_index) is not int:
        return
    # Блокировка преобразования: оформление видов одной страницы завершается в разных
    # транзакциях, а страницу ведёт тот, кто закончил последним.
    await session.refresh(convert, with_for_update=True)
    styles = await _style_jobs(session, convert, page_index)
    if any(job.status in _ACTIVE for job in styles):
        return
    if any(job.status is not JobStatus.SUCCEEDED for job in styles):
        log.warning("ai_loop_style_failed_chain_stands", job_id=str(convert.id))
        return
    results = [result for job in styles if (result := _style_result(job)) is not None]
    classes = merge_classes(results)
    if classes:
        if not await _classes_reconvert_exists(session, convert, page_index, classes):
            params = _classes_reconvert_params(convert, page_index, classes)
            try:
                async with session.begin_nested():
                    job = await cad_convert_hints.enqueue_reconvert(
                        session, convert, params, settings
                    )
                    _with_marker(job, reason="style", style_job_id=str(style.id))
            except _HOOK_ERRORS:
                # Преобразования с классами не будет, `after_walls` его не ждёт: правщик - ниже.
                log.warning("ai_loop_style_reconvert_failed", job_id=str(convert.id))
            else:
                return
        else:
            log.warning("ai_loop_style_reconvert_exists", job_id=str(convert.id))
    # Классов нет (или преобразование с ними не поставлено): правщик по существующим конструкциям.
    for view in sorted({int(job.payload["view"]) for job in styles}):
        walls = await _latest_walls(session, convert, page_index, view)
        if walls is not None:
            await _start_corrector(session, walls, convert, pilot, settings)


async def after_walls(session: AsyncSession, walls: Job, settings: Settings) -> None:
    """Успех `cad_walls` пилота: правщик, если у преобразования не ждут классов оформления."""
    try:
        await _after_walls_impl(session, walls, settings)
    except _HOOK_ERRORS:
        log.warning("ai_loop_hook_failed", hook="after_walls", job_id=str(walls.id))


async def _after_walls_impl(session: AsyncSession, walls: Job, settings: Settings) -> None:
    pilot = pilot_for_project(walls.project_id, settings)
    if pilot is None or walls.job_type is not JobType.CAD_WALLS:
        return
    async with session.begin_nested():
        context = await _walls_context(session, walls)
        if context is None:
            return
        convert, page_index, _ = context
        if is_first_convert(convert):
            # Та же блокировка, что у `_after_style`: правщика ставит тот, кто закончил
            # позже, и без неё оба при одновременном завершении увидели бы друг друга идущими.
            await session.refresh(convert, with_for_update=True)
            styles = await _style_jobs(session, convert, page_index)
            if any(job.status in _ACTIVE for job in styles):
                return  # оформление ещё идёт: ход продолжит его хук
            if any(job.status is not JobStatus.SUCCEEDED for job in styles):
                return  # оформление упало: цепочка стоит до решения человека
            results = [r for job in styles if (r := _style_result(job)) is not None]
            classes = merge_classes(results)
            if classes and await _classes_reconvert_exists(session, convert, page_index, classes):
                return  # идёт или уже создано преобразование с классами
        await _start_corrector(session, walls, convert, pilot, settings)


async def after_review(
    session: AsyncSession, storage: ObjectStorage, review: Job, settings: Settings
) -> None:
    """Успех правщика: проверщик или перестроение по замечаниям; проверщик ход не продолжает."""
    try:
        await _after_review_impl(session, storage, review, settings)
    except _HOOK_ERRORS:
        log.warning("ai_loop_hook_failed", hook="after_review", job_id=str(review.id))


async def _after_review_impl(
    session: AsyncSession, storage: ObjectStorage, review: Job, settings: Settings
) -> None:
    pilot = pilot_for_project(review.project_id, settings)
    if pilot is None or review.payload.get("role") != "corrector":
        return
    async with session.begin_nested():
        await _after_corrector(session, storage, review, pilot, settings)


async def _after_corrector(
    session: AsyncSession,
    storage: ObjectStorage,
    review: Job,
    pilot: AiLoopPilot,
    settings: Settings,
) -> None:
    raw = review.payload.get("ai_review")
    if review.status is not JobStatus.SUCCEEDED or not isinstance(raw, dict):
        return
    verdict = AiReviewResult.model_validate(raw).report.verdict
    walls = await session.get(Job, uuid.UUID(str(review.payload.get("walls_job_id"))))
    convert = await session.get(Job, uuid.UUID(str(review.payload.get("cad_job_id"))))
    page_index, view = review.payload.get("page_index"), review.payload.get("view")
    attempt = review.payload.get("cad_attempt")
    if (
        walls is None
        or convert is None
        or type(page_index) is not int
        or type(view) is not int
        or type(attempt) is not int
        or review.project_id is None
    ):
        return
    if verdict == "ready_for_human_review":
        await _start_verifier(session, walls, convert, pilot, settings)
        return
    if verdict != "needs_correction":
        return  # insufficient_evidence: решает человек
    reviews = await _chain_reviews(
        session,
        project_id=review.project_id,
        revision_id=str(convert.payload.get("revision_id")),
        page_index=page_index,
        view=view,
    )
    if len(_of_role(reviews, "corrector")) >= pilot.max_iterations:
        await _start_verifier(session, walls, convert, pilot, settings)
        return
    remarks = await cad_remarks.list_remarks(
        session, job=convert, attempt=attempt, page_index=page_index, view=view
    )
    hints = cad_convert_hints.hints_from_remarks(remarks, page_index + 1)
    if hints is not None:
        merged_hints = cad_convert_hints.merge_hints(
            cad_convert_hints.previous_hints_of(convert), hints.hints
        )
        params = cad_convert_hints.reconvert_params(
            convert,
            page_index,
            hints=merged_hints,
            hatch_classes=cad_convert_hints.hatch_classes_of(convert),
        )
        key = cad_service.idempotency_key(uuid.UUID(str(convert.payload["revision_id"])), params)
        if await jobs_service.find_by_idempotency_key(session, idempotency_key=key) is None:
            job = await cad_convert_hints.enqueue_reconvert(session, convert, params, settings)
            _with_marker(
                job,
                reason="remarks",
                review_job_id=str(review.id),
                carry_from={"job_id": str(convert.id), "attempt": attempt},
            )
            return
        # Те же подсказки уже были: повтор вернул бы то же задание, цикл не продвинется.
        log.warning("ai_loop_reconvert_same_hints", job_id=str(convert.id))
    if any(row.status == _OPEN and row.type == "false_wall" for row in remarks):
        try:
            rebuilt = await cad_walls.schedule_rebuild_by_remarks(
                session, storage, walls_job=walls, settings=settings
            )
        except DomainError:
            log.warning("ai_loop_rebuild_refused", job_id=str(walls.id))
        else:
            _with_marker(rebuilt, reason="false_wall", rebuild_of=str(review.id))
            return
    # Движку подсказывать нечего (прочие типы замечаний): итог за проверщиком.
    await _start_verifier(session, walls, convert, pilot, settings)
