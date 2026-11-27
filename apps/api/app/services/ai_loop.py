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

Круг считается по виду цепочки преобразований листа (ревизия, страница, вид), а не по одному
заданию конструкций. Цепочка начинается с последнего преобразования без подсказок (корень):
проверки более старых прогонов того же вида в счёт кругов не входят. Модель только
классифицирует подписи и находит замечания; метры, площади и объёмы считает движок.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
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
from app.models import CadRemark, Job, PageGeometry, Sheet
from app.services import cad as cad_service
from app.services import (
    cad_ai_feedback,
    cad_convert_hints,
    cad_remarks,
    cad_walls,
)
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
COORDINATION_ROLE: Final = "coordination"
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


async def _chain_root(session: AsyncSession, convert: Job, page_index: int) -> Job | None:
    """Корень цепочки: последнее преобразование страницы без подсказок не позже `convert`."""
    if is_first_convert(convert):
        return convert
    revision_id = convert.payload.get("revision_id")
    if revision_id is None:
        return None
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_PDF_CONVERT,
            Job.project_id == convert.project_id,
            Job.workspace_id == convert.workspace_id,
            Job.payload["revision_id"].astext == str(revision_id),
            ~Job.payload["params"].has_key("convert_hints"),
            Job.payload["params"]["pages"].contains([page_index]),
            Job.created_at <= convert.created_at,
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )
    return rows.first()


async def _chain_reviews(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    revision_id: str,
    page_index: int,
    view: int,
    since: datetime | None = None,
) -> list[Job]:
    """Проверки правщика и проверщика вида по цепочке от корня (`since`): новые первыми.

    `since` - время постановки корня цепочки (см. `_chain_root`); без него берётся вся история.
    """
    conditions = [
        Job.job_type == JobType.CAD_AI_REVIEW,
        Job.project_id == project_id,
        Job.payload["role"].astext.in_(("corrector", "verifier")),
        Job.payload["revision_id"].astext == revision_id,
        Job.payload["page_index"].astext == str(page_index),
        Job.payload["view"].astext == str(view),
    ]
    if since is not None:
        conditions.append(Job.created_at >= since)
    rows = await session.scalars(
        select(Job).where(*conditions).order_by(Job.created_at.desc(), Job.id)
    )
    return list(rows)


def _of_role(jobs: Iterable[Job], role: str) -> list[Job]:
    return [job for job in jobs if job.payload.get("role") == role]


def _rounds(jobs: Iterable[Job], role: str) -> list[Job]:
    """Круги роли: проваленные и отменённые проверки в счёт кругов не входят.

    Повтор по тем же конструкциям они всё равно не порождают - это проверяет `_of_role`.
    """
    return [
        job
        for job in _of_role(jobs, role)
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED)
    ]


async def _read_json_artifact(storage: ObjectStorage, job: Job, name: str) -> dict[str, Any] | None:
    """Читает JSON-артефакт задания из хранилища с ограничением памяти."""
    artifact = cad_service.find_artifact(job, name)
    key = artifact.get("key") if isinstance(artifact, dict) else None
    if not isinstance(key, str) or not key:
        return None
    buf = bytearray()
    async for chunk in storage.iter_stream(key):
        buf.extend(chunk)
        if len(buf) > cad_service.MAX_JSON_ARTIFACT_BYTES:
            return None
    data = json.loads(bytes(buf))
    return data if isinstance(data, dict) else None


async def _read_walls_json(
    storage: ObjectStorage, walls: Job, page_index: int, view: int
) -> dict[str, Any] | None:
    """Читает `walls.json` задания конструкций из хранилища с ограничением памяти."""
    return await _read_json_artifact(
        storage, walls, f"{cad_service.view_folder(page_index, view)}/{cad_walls.WALLS_JSON}"
    )


async def _read_convert_checks(
    storage: ObjectStorage, convert: Job, page_index: int, view: int
) -> dict[str, Any] | None:
    """Читает `checks.json` задания преобразования (подсказки `missing_wall`/`missing_door`)."""
    return await _read_json_artifact(
        storage, convert, f"{cad_service.view_folder(page_index, view)}/checks.json"
    )


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
    root = await _chain_root(session, convert, position[0])
    reviews = await _chain_reviews(
        session,
        project_id=walls.project_id,
        revision_id=str(convert.payload.get("revision_id")),
        page_index=position[0],
        view=position[1],
        since=root.created_at if root is not None else None,
    )
    verifiers = _of_role(reviews, "verifier")
    if any(job.payload.get("walls_job_id") == str(walls.id) for job in verifiers):
        return None
    rounds = len(_rounds(reviews, "verifier"))
    if rounds >= pilot.max_iterations:
        return None
    return await ai_review.enqueue_for_walls(
        session, walls, settings, "verifier", iteration=rounds + 1
    )


async def _start_corrector(
    session: AsyncSession, walls: Job, convert: Job, pilot: AiLoopPilot, settings: Settings
) -> Job | None:
    """Правщик по заданию конструкций; круги по цепочке от последнего преобразования без подсказок.

    Корень цепочки - `_chain_root`: проверки старых прогонов вида в счёт кругов не входят.
    """
    from app.cad_worker import ai_review  # цикл: handler -> ai_loop -> ai_review

    position = _view_of(walls)
    if position is None or walls.project_id is None:
        return None
    root = await _chain_root(session, convert, position[0])
    reviews = await _chain_reviews(
        session,
        project_id=walls.project_id,
        revision_id=str(convert.payload.get("revision_id")),
        page_index=position[0],
        view=position[1],
        since=root.created_at if root is not None else None,
    )
    correctors = _of_role(reviews, "corrector")
    if any(job.payload.get("walls_job_id") == str(walls.id) for job in correctors):
        return None
    rebuilt = _loop_marker(walls).get("rebuild_of") is not None
    if not rebuilt and any(job.payload.get("cad_job_id") == str(convert.id) for job in correctors):
        # Второе задание конструкций того же преобразования (пересчёт после авто-зон): правщик
        # у этого преобразования уже был, второго круга пересчёт не порождает.
        return None
    rounds = len(_rounds(reviews, "corrector"))
    if rounds >= pilot.max_iterations:
        return await _start_verifier(session, walls, convert, pilot, settings)
    return await ai_review.enqueue_for_walls(
        session, walls, settings, "corrector", iteration=rounds + 1
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


async def after_walls(
    session: AsyncSession,
    walls: Job,
    settings: Settings,
    storage: ObjectStorage | None = None,
) -> None:
    """Успех `cad_walls` пилота: правщик, если у преобразования не ждут классов оформления, и
    лёгкое задание координации осей (эталон «Здания» ищет его исполнитель; отдельный ход: сбой
    одного не мешает другому)."""
    try:
        await _after_walls_impl(session, walls, settings)
    except _HOOK_ERRORS:
        log.warning("ai_loop_hook_failed", hook="after_walls", job_id=str(walls.id))
    if storage is None:
        return
    from app.cad_worker.handler import CadError  # цикл: исполнитель сам вызывает этот хук

    try:
        await _coordinate_after_walls(session, storage, walls, settings)
    except (*_HOOK_ERRORS, OSError, CadError, TypeError):
        # Чтение осей вида и постановка задания не должны ронять уже завершённые конструкции.
        log.warning("ai_loop_hook_failed", hook="after_walls_coordination", job_id=str(walls.id))


async def _coordinate_after_walls(
    session: AsyncSession, storage: ObjectStorage, walls: Job, settings: Settings
) -> None:
    if pilot_for_project(walls.project_id, settings) is None or walls.job_type is not (
        JobType.CAD_WALLS
    ):
        return
    from app.services import cad_axis_coordination_jobs  # цикл: модуль берёт пилот отсюда

    async with session.begin_nested():
        await cad_axis_coordination_jobs.coordinate_for_walls(session, storage, walls, settings)


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


async def _resolve_best_for_verifier(
    session: AsyncSession,
    current_walls: Job,
    current_convert: Job,
    best_walls_id: uuid.UUID | None,
) -> tuple[Job, Job]:
    """Возвращает `(walls, convert)` лучшего успешного снимка цепочки (или текущего)."""
    if best_walls_id is not None and best_walls_id != current_walls.id:
        candidate = await session.get(Job, best_walls_id)
        if (
            candidate is not None
            and candidate.job_type is JobType.CAD_WALLS
            and candidate.status is JobStatus.SUCCEEDED
        ):
            ctx = await _walls_context(session, candidate)
            if ctx is not None:
                return candidate, ctx[0]
    return current_walls, current_convert


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
    ai_result = AiReviewResult.model_validate(raw)
    report = ai_result.report
    verdict = report.verdict
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
    revision_id_str = str(convert.payload.get("revision_id"))
    root = await _chain_root(session, convert, page_index)
    reviews = await _chain_reviews(
        session,
        project_id=review.project_id,
        revision_id=revision_id_str,
        page_index=page_index,
        view=view,
        since=root.created_at if root is not None else None,
    )
    progress: cad_ai_feedback.RoundProgress | None = None
    best_walls_id: uuid.UUID | None = walls.id
    try:
        curr_walls_data = await _read_walls_json(storage, walls, page_index, view)
        curr_checks = await _read_convert_checks(storage, convert, page_index, view)
        if curr_walls_data is not None:
            prev_walls_data: dict[str, Any] | None = None
            prev_checks: dict[str, Any] | None = None
            prev_walls_id: uuid.UUID | None = None
            prev_marker: dict[str, Any] = {}
            for prev_row in _of_role(reviews, "corrector"):
                if prev_row.id == review.id or prev_row.status is not JobStatus.SUCCEEDED:
                    continue
                prev_raw = prev_row.payload.get("ai_review")
                if isinstance(prev_raw, dict):
                    prev_res = AiReviewResult.model_validate(prev_raw)
                    prev_walls_id = prev_res.walls_job_id
                    prev_marker = _loop_marker(prev_row)
                    prev_walls_job = await session.get(Job, prev_walls_id)
                    if prev_walls_job is not None:
                        prev_walls_data = await _read_walls_json(
                            storage, prev_walls_job, prev_res.page_index, prev_res.view
                        )
                    prev_convert_job = await session.get(Job, prev_res.cad_job_id)
                    if prev_convert_job is not None:
                        prev_checks = await _read_convert_checks(
                            storage, prev_convert_job, prev_res.page_index, prev_res.view
                        )
                    break
            progress = cad_ai_feedback.check_round_progress(
                prev_walls_data,
                curr_walls_data,
                convert_checks=curr_checks,
                prev_convert_checks=prev_checks,
            )
            prev_best_id = prev_walls_id
            raw_best_id = prev_marker.get("best_walls_job_id")
            if isinstance(raw_best_id, str):
                try:
                    prev_best_id = uuid.UUID(raw_best_id)
                except ValueError:
                    prev_best_id = prev_walls_id
            raw_best_score = prev_marker.get("best_quality_score")
            prev_best_score: float | None = (
                float(raw_best_score)
                if isinstance(raw_best_score, int | float)
                else progress.prev_score
            )
            if (
                prev_best_score is not None
                and prev_best_id is not None
                and progress.curr_score < prev_best_score
            ):
                best_walls_id = prev_best_id
                best_score = prev_best_score
            else:
                best_walls_id = walls.id
                best_score = progress.curr_score
            _with_marker(
                review,
                quality_score=progress.curr_score,
                progress_status=progress.status,
                best_walls_job_id=str(best_walls_id),
                best_quality_score=best_score,
            )
    except Exception:
        log.warning("ai_loop_progress_check_failed", job_id=str(review.id), exc_info=True)

    # Кандидаты зон плиты сохраняются только в маркере задания для подтверждения человеком в UI/API
    # и никогда не пишутся автоматически в `cad_zones` (иначе попали бы в отделку МОП / ВОР).
    if any(f.kind == "slab_missing_area" for f in report.slab_findings):
        try:
            rev_uuid = uuid.UUID(revision_id_str)
            geometry = await session.scalar(
                select(PageGeometry)
                .join(Sheet, PageGeometry.sheet_id == Sheet.id)
                .where(Sheet.revision_id == rev_uuid, Sheet.page_index == page_index)
            )
            if geometry is not None:
                zone_creates = cad_ai_feedback.slab_findings_to_zone_creates(
                    report,
                    ai_result.render,
                    page_width_pt=float(geometry.display_width_pt),
                    page_height_pt=float(geometry.display_height_pt),
                    revision_id=rev_uuid,
                    page_index=page_index,
                )
                if zone_creates:
                    _with_marker(
                        review,
                        pending_slab_zones=[z.model_dump(mode="json") for z in zone_creates],
                    )
        except Exception:
            log.warning("ai_loop_pending_slab_zones_failed", job_id=str(review.id), exc_info=True)

    if verdict == "ready_for_human_review":
        v_walls, v_convert = (
            await _resolve_best_for_verifier(session, walls, convert, best_walls_id)
            if progress is not None and progress.status == "regressed"
            else (walls, convert)
        )
        await _start_verifier(session, v_walls, v_convert, pilot, settings)
        return
    if verdict != "needs_correction":
        return  # insufficient_evidence: решает человек
    if len(_rounds(reviews, "corrector")) >= pilot.max_iterations:
        v_walls, v_convert = await _resolve_best_for_verifier(
            session, walls, convert, best_walls_id
        )
        await _start_verifier(session, v_walls, v_convert, pilot, settings)
        return
    remarks = await cad_remarks.list_remarks(
        session, job=convert, attempt=attempt, page_index=page_index, view=view
    )
    has_open_false_wall = any(row.status == _OPEN and row.type == "false_wall" for row in remarks)
    hints = cad_convert_hints.hints_from_remarks(remarks, page_index + 1)
    reconvert_params: dict[str, Any] | None = None
    has_new_reconvert = False
    if hints is not None:
        merged_hints = cad_convert_hints.merge_hints(
            cad_convert_hints.previous_hints_of(convert), hints.hints
        )
        reconvert_params = cad_convert_hints.reconvert_params(
            convert,
            page_index,
            hints=merged_hints,
            hatch_classes=cad_convert_hints.hatch_classes_of(convert),
        )
        key = cad_service.idempotency_key(uuid.UUID(revision_id_str), reconvert_params)
        has_new_reconvert = (
            await jobs_service.find_by_idempotency_key(session, idempotency_key=key) is None
        )

    if progress is not None and progress.status == "stagnated" and not has_open_false_wall:
        _with_marker(review, stop_reason="engine_blocked")
        v_walls, v_convert = await _resolve_best_for_verifier(
            session, walls, convert, best_walls_id
        )
        await _start_verifier(session, v_walls, v_convert, pilot, settings)
        return

    if hints is not None and reconvert_params is not None:
        if has_new_reconvert:
            job = await cad_convert_hints.enqueue_reconvert(
                session, convert, reconvert_params, settings
            )
            _with_marker(
                job,
                reason="remarks",
                review_job_id=str(review.id),
                carry_from={"job_id": str(convert.id), "attempt": attempt},
            )
            return
        # Те же подсказки уже были: повтор вернул бы то же задание, цикл не продвинется.
        log.warning("ai_loop_reconvert_same_hints", job_id=str(convert.id))
    if has_open_false_wall:
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
    v_walls, v_convert = await _resolve_best_for_verifier(session, walls, convert, best_walls_id)
    await _start_verifier(session, v_walls, v_convert, pilot, settings)
