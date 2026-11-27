"""Координация осей: эталон вида, постановка задания роли `coordination`, смещения для «Здания».

Задание хранит в `payload` вложенные `target` и `reference` (без `walls_job_id` на верхнем уровне:
`ai_review.reviews_of` и конвейер листа ищут проверки вида по этому ключу). Эталон вида - тот же,
что выбирает совмещение «Здания» (`cad_building3d._pick_reference` по группе этажа). Результат
(`ai_coordination`) - кандидат для сборки «Здания», в `plan_alignments` он не пишется.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_ai_coordination import (
    AiCoordinationPair,
    AiCoordinationReport,
    AiCoordinationResult,
    AiCoordinationView,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import AiPromptVersion, Job
from app.services import ai_loop, cad, cad_views
from app.services import cad_axis_coordination as coordination
from app.services import cad_building3d as b3d
from app.services import jobs as jobs_service
from app.storage.base import ObjectNotFoundError, ObjectStorage

log = get_logger(__name__)

ROLE: Final = ai_loop.COORDINATION_ROLE
# Автоповторов упавшего задания на один вид, оси цели и версию промта.
MAX_AUTO_RETRIES: Final = 2
NOT_AVAILABLE: Final = "ИИ-координация для этого проекта недоступна"


@dataclass(frozen=True, slots=True)
class ResolvedPair:
    """Лист-цель и его эталон в «Здании» (с заданиями конструкций, из которых взяты оси)."""

    target: b3d.SheetRef
    reference: b3d.SheetRef
    # Отпечатки текущих осей видов: по ним автоход узнаёт, что координировать заново нечего.
    target_axes_sha256: str | None = None
    reference_axes_sha256: str | None = None


async def resolve_reference(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> ResolvedPair | str:
    """Эталон вида в «Здании» либо причина, по которой координировать нечего.

    Группа этажа - по `group_key` листа, эталон - `_pick_reference` по этажам группы с осями в обоих
    направлениях, как в `align_floors`. Группа «Корпус не указан» делится по сеткам осей отдельно
    (`_split_unnamed`) и здесь не разбирается; сам эталон координации не требует.
    """
    sheets, _, slab = await b3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    wanted = (revision_id, page_index, view)
    position = next(
        (i for i, s in enumerate(sheets) if (s.revision_id, s.page_index, s.view) == wanted), None
    )
    if position is None:
        return "вид не входит в «Здание»"
    gate = asyncio.Semaphore(b3d.READ_CONCURRENCY)
    generation = b3d.floor_cache.begin()
    loaded = await asyncio.gather(
        *(b3d._load_sheet_floor(storage, s, slab, False, gate, generation) for s in sheets)
    )
    own = loaded[position].floor
    if own is None:
        return "лист не план этажа или конструкции не читаются"
    if own.group_key == b3d.GROUP_NONE_KEY:
        return "группа «Корпус не указан» совмещается по сеткам осей отдельно"
    members = [
        (sheet, item)
        for sheet, item in zip(sheets, loaded, strict=True)
        if item.floor is not None and item.floor.group_key == own.group_key
    ]
    built = [b3d.BuiltFloor(item.floor, s.order, item.axes) for s, item in members if item.floor]
    target_sheet = sheets[position]
    own_index = next(i for i, (s, _) in enumerate(members) if s is target_sheet)
    if not built[own_index].axes.usable:
        return "на виде нет осей в обоих направлениях"
    usable = [i for i, floor in enumerate(built) if floor.axes.usable]
    reference_index = b3d._pick_reference(built, usable)
    if reference_index is None:
        return "в группе нет этажа с осями в обоих направлениях"
    reference_sheet = members[reference_index][0]
    if reference_index == own_index:
        return "вид - эталон группы: координировать не с чем"
    if target_sheet.walls_job_id is None or reference_sheet.walls_job_id is None:
        return "у вида или эталона нет готовых конструкций"
    target_axes = loaded[position].coord_axes
    reference_axes = members[reference_index][1].coord_axes
    if not target_axes or not reference_axes:
        return "оси вида или эталона без подтверждённого кадра"
    return ResolvedPair(
        target_sheet,
        reference_sheet,
        coordination.axes_fingerprint(target_axes),
        coordination.axes_fingerprint(reference_axes),
    )


def _view_key(view: dict[str, object]) -> tuple[str, int, int] | None:
    page_index, number = view.get("page_index"), view.get("view")
    if type(page_index) is not int or type(number) is not int:
        return None
    return str(view.get("revision_id")), page_index, number


def _is_skipped(job: Job) -> bool:
    """Задание завершилось без вызова модели (эталона нет): оно новой координации не мешает."""
    result = job.payload.get("ai_coordination")
    return isinstance(result, dict) and result.get("status") == "skipped"


def _rejected(job: Job) -> bool:
    """Задание завершилось, но пары не дали смещения (`rejected`): ручной запуск повторит его."""
    result = job.payload.get("ai_coordination")
    return not isinstance(result, dict) or result.get("status") != "ok"


def walls_view(walls: Job, axes_sha256: str | None = None) -> dict[str, object]:
    result = cad.result_of(walls)
    page_index, view = result.get("page_index"), result.get("view")
    parent = walls.payload.get("parent_job_id")
    if type(page_index) is not int or type(view) is not int or not isinstance(parent, str):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "У конструкций нет адреса вида")
    return {
        "revision_id": str(walls.payload.get("revision_id")),
        "page_index": page_index,
        "view": view,
        "walls_job_id": str(walls.id),
        "cad_job_id": parent,
        "axes_sha256": axes_sha256,
    }


async def target_view_axes(
    session: AsyncSession, storage: ObjectStorage, walls: Job
) -> list[b3d.CoordAxis] | str:
    """Оси вида из его `walls.json` (одно чтение) и кадра: список осей либо причина, по которой
    координировать нечем. Отпечаток считает вызывающий (`cad_axis_coordination.axes_fingerprint`).

    Сбой хранилища не ловится: его видит вызывающий (хук автохода).
    """
    result = cad.result_of(walls)
    page_index, view = result.get("page_index"), result.get("view")
    try:
        revision_id = uuid.UUID(str(walls.payload.get("revision_id")))
        convert_id = uuid.UUID(str(walls.payload.get("parent_job_id")))
    except ValueError:
        return "у конструкций нет адреса вида"
    convert = await session.get(Job, convert_id)
    if type(page_index) is not int or type(view) is not int or convert is None:
        return "у конструкций нет адреса вида"
    folder = cad.view_folder(page_index, view)
    walls_key = b3d._walls_key(walls, revision_id, page_index, view)
    scale_key = b3d._parent_key(convert, revision_id, f"{folder}/scale.json")
    checks_key = b3d._parent_key(convert, revision_id, f"{folder}/cad_checks.json")
    if walls_key is None or scale_key is None or checks_key is None:
        return "конструкции, масштаб или проверки вида не найдены"
    try:
        raw = await cad_views.read_json(storage, walls_key)
        scale = cad_views.scale_from(await cad_views.read_json(storage, scale_key))
        checks = await cad_views.read_json(storage, checks_key)
    except (ObjectNotFoundError, cad_views.ArtifactTooLargeError, ValueError):
        return "walls.json, масштаб или проверки вида не читаются"
    axes = b3d.coordination_axes(raw, cad_views.frame_from(scale, checks))
    if not axes:
        return "оси вида без подтверждённого кадра"
    for orient in (coordination.VERTICAL, coordination.HORIZONTAL):
        if sum(1 for axis in axes if axis.orient == orient) < coordination.MIN_AGREED_PAIRS:
            return "на виде меньше двух осей в одном из направлений"
    return axes


async def _autorun_blocker(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    target: dict[str, object],
    target_sha256: str,
    prompt_id: uuid.UUID,
) -> Job | None:
    """Задание, из-за которого автоход вид заново не ставит; нет - `None`.

    Тот же вид цели, те же оси цели и та же версия промта. Мешают идущее задание и завершённое с
    итогом `ok` или `rejected`; завершённое без вызова модели (`skipped`) не мешает: эталон мог
    появиться позже. Упавшее задание повторяется, но не больше `MAX_AUTO_RETRIES` раз на ту же
    комбинацию (сбой инфраструктуры не блокирует вид навсегда, а поломка не жжёт вызовы).
    """
    key = _view_key(target)
    if key is None:
        return None
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.project_id == project_id,
            Job.payload["role"].astext == ROLE,
            Job.payload["target"]["revision_id"].astext == key[0],
            Job.payload["target"]["page_index"].astext == str(key[1]),
            Job.payload["target"]["view"].astext == str(key[2]),
            Job.payload["target"]["axes_sha256"].astext == target_sha256,
            Job.payload["prompt_version_id"].astext == str(prompt_id),
            Job.status != JobStatus.CANCELLED,
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    failed: list[Job] = []
    for job in rows:
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            return job
        if job.status is JobStatus.FAILED:
            failed.append(job)
        elif not _is_skipped(job):
            return job
    return failed[0] if len(failed) > MAX_AUTO_RETRIES else None


async def enqueue_coordination(
    session: AsyncSession,
    target_walls: Job,
    settings: Settings,
    *,
    retry_failed: bool = False,
    target_axes_sha256: str | None = None,
) -> Job:
    """Ставит лёгкое задание координации вида: эталон, оси эталона и повтор ищет исполнитель.

    Автоход (`retry_failed=False`) вид с теми же осями цели и версией промта не ставит заново
    (`_autorun_blocker`). Ручной запуск (`retry_failed=True`) возвращает идущее задание, иначе
    ставит новое: исполнитель сам не вызовет модель, если для пары видов уже есть результат.
    """
    pilot = ai_loop.pilot_for_project(target_walls.project_id, settings)
    if pilot is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, NOT_AVAILABLE)
    if (
        target_walls.job_type is not JobType.CAD_WALLS
        or target_walls.status is not JobStatus.SUCCEEDED
    ):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "Конструкции вида не готовы")
    prompt = await session.scalar(
        select(AiPromptVersion).where(
            AiPromptVersion.role == ROLE, AiPromptVersion.status == "active"
        )
    )
    if prompt is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "Нет активного промта роли «координация»")
    target_payload = walls_view(target_walls, target_axes_sha256)
    if not retry_failed and target_axes_sha256:
        blocker = await _autorun_blocker(
            session, target_walls.project_id, target_payload, target_axes_sha256, prompt.id
        )
        if blocker is not None:
            return blocker
    # Ключ в базе - до 128 символов: задание конструкций и версия промта сворачиваются в хеш.
    digest = hashlib.sha256(f"{target_walls.id}:{prompt.id}".encode())
    base = f"cad-ai-coordination:v2:{digest.hexdigest()[:40]}"
    existing = list(
        await session.scalars(
            select(Job)
            .where(Job.job_type == JobType.CAD_AI_REVIEW, Job.idempotency_key.startswith(base))
            .order_by(Job.created_at.desc(), Job.id)
        )
    )
    for job in existing:
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            return job
    key = base if not existing else f"{base}:{len(existing)}"
    payload: dict[str, object] = {
        "role": ROLE,
        "project_id": str(target_walls.project_id),
        "model": pilot.model,
        "sources": pilot.sources,
        "prompt_version_id": str(prompt.id),
        "prompt_version": prompt.version,
        "target": target_payload,
    }
    try:
        # Гонка двух постановок одного ключа: проигравшая получает задание победившей.
        async with session.begin_nested():
            return await jobs_service.enqueue(
                session,
                job_type=JobType.CAD_AI_REVIEW,
                project_id=target_walls.project_id,
                workspace_id=target_walls.workspace_id,
                idempotency_key=key,
                payload=payload,
            )
    except IntegrityError:
        winner = await jobs_service.find_by_idempotency_key(session, idempotency_key=key)
        if winner is None or winner.workspace_id != target_walls.workspace_id:
            raise
        return winner


async def start_for_view(
    session: AsyncSession,
    settings: Settings,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> tuple[Job, uuid.UUID]:
    """Ручной запуск: задание и идентификатор заданий конструкций цели.

    Только ставит задание: эталон «Здания» ищет исполнитель (по проекту целиком - в запросе
    этого не делается).
    """
    if ai_loop.pilot_for_project(project_id, settings) is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, NOT_AVAILABLE)
    target_walls = await session.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_WALLS,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["revision_id"].astext == str(revision_id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )
    if target_walls is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "Конструкции вида не найдены")
    job = await enqueue_coordination(session, target_walls, settings, retry_failed=True)
    return job, target_walls.id


async def coordinate_for_walls(
    session: AsyncSession, storage: ObjectStorage, walls: Job, settings: Settings
) -> Job | None:
    """Автоход: лёгкое задание координации по готовым конструкциям вида.

    Читает только оси самого вида (один `walls.json`); эталон в «Здании» и дедуп по нему - дело
    исполнителя задания.
    """
    if (
        ai_loop.pilot_for_project(walls.project_id, settings) is None
        or walls.job_type is not JobType.CAD_WALLS
        or walls.workspace_id is None
        or walls.project_id is None
    ):
        return None
    axes = await target_view_axes(session, storage, walls)
    if isinstance(axes, str):
        log.info("ai_coordination_skipped", job_id=str(walls.id), reason=axes)
        return None
    return await enqueue_coordination(
        session, walls, settings, target_axes_sha256=coordination.axes_fingerprint(axes)
    )


async def reusable_result(
    session: AsyncSession,
    job: Job,
    target: AiCoordinationView,
    reference: AiCoordinationView,
    prompt_id: uuid.UUID,
) -> tuple[Job, AiCoordinationResult] | None:
    """Успешная координация той же пары видов с теми же отпечатками осей и версией промта.

    Только итог `ok`: отклонённый (`rejected`) ручной запуск повторяет моделью. Для исполнителя:
    есть такой итог - модель не вызывается, ссылка и пары копируются.
    """
    if target.axes_sha256 is None or reference.axes_sha256 is None:
        return None
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.project_id == job.project_id,
            Job.workspace_id == job.workspace_id,
            Job.id != job.id,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["role"].astext == ROLE,
            Job.payload["ai_coordination"]["status"].astext == "ok",
            Job.payload["ai_coordination"]["target"]["revision_id"].astext
            == str(target.revision_id),
            Job.payload["ai_coordination"]["target"]["page_index"].astext == str(target.page_index),
            Job.payload["ai_coordination"]["target"]["view"].astext == str(target.view),
            Job.payload["ai_coordination"]["reference"]["revision_id"].astext
            == str(reference.revision_id),
            Job.payload["ai_coordination"]["reference"]["page_index"].astext
            == str(reference.page_index),
            Job.payload["ai_coordination"]["reference"]["view"].astext == str(reference.view),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    for found in rows:
        try:
            result = AiCoordinationResult.model_validate(found.payload.get("ai_coordination"))
        except ValidationError:
            continue
        if (
            result.status == "ok"
            and result.prompt_version_id == prompt_id
            and result.target.axes_sha256 == target.axes_sha256
            and result.reference.axes_sha256 == reference.axes_sha256
        ):
            return found, result
    return None


@dataclass(frozen=True, slots=True)
class StoredCoordination:
    """Успешная координация пары видов (`status = ok`) в том виде, как она хранится в задании."""

    reference_view: b3d.ViewKey
    target_axes_sha256: str
    reference_axes_sha256: str
    pairs: tuple[AiCoordinationPair, ...]


async def load_hints(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict[b3d.ViewKey, tuple[StoredCoordination, ...]]:
    """Сохранённые координации по виду цели (revision, page, view): один запрос на сборку.

    Только успешные задания с итогом `ok` и отпечатками осей; новые первыми. Смещение здесь не
    берётся: `apply_hints` пересчитывает его по парам и текущим осям.
    """
    rows = await session.scalars(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.CAD_AI_REVIEW,
            Job.status == JobStatus.SUCCEEDED,
            Job.payload["role"].astext == ROLE,
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    found: dict[b3d.ViewKey, list[StoredCoordination]] = defaultdict(list)
    for job in rows:
        raw = job.payload.get("ai_coordination")
        if not isinstance(raw, dict):
            continue
        try:
            result = AiCoordinationResult.model_validate(raw)
        except ValidationError:
            continue
        if (
            result.status != "ok"
            or not result.pairs
            or result.target.axes_sha256 is None
            or result.reference.axes_sha256 is None
        ):
            continue
        key = (result.target.revision_id, result.target.page_index, result.target.view)
        found[key].append(
            StoredCoordination(
                reference_view=(
                    result.reference.revision_id,
                    result.reference.page_index,
                    result.reference.view,
                ),
                target_axes_sha256=result.target.axes_sha256,
                reference_axes_sha256=result.reference.axes_sha256,
                pairs=tuple(
                    AiCoordinationPair(
                        target_axis_id=pair.target_axis_id,
                        reference_axis_id=pair.reference_axis_id,
                        confidence=pair.confidence,
                        evidence=pair.evidence,
                    )
                    for pair in result.pairs
                ),
            )
        )
    return {key: tuple(items) for key, items in found.items()}


STALE_NOTE: Final = (
    "оси вида или эталона изменились после координации ИИ: сохранённые пары не применены, "
    "совмещение по подписям осей"
)
RECOMPUTE_NOTE: Final = (
    "пары осей из координации ИИ не дали смещения на текущих осях ({reason}): "
    "совмещение по подписям осей"
)


def apply_hints(
    built: Sequence[b3d.BuiltFloor],
    stored: Mapping[b3d.ViewKey, Sequence[StoredCoordination]],
) -> list[b3d.BuiltFloor]:
    """Подсказки координации для этажей: сохранённые пары применяются к ТЕКУЩИМ осям.

    Для вида цели и каждого эталона берётся новейшая координация, отпечатки осей которой совпали с
    текущими осями обоих видов; смещение пересчитывает `compute_offset` (перестроенные конструкции
    с теми же осями подсказку не теряют). Не совпали или пересчёт отказал - подсказки нет, причина
    уходит в `coordination_notes` и в `alignment_note` этажа.
    """
    if not stored:
        return list(built)
    by_view = {b3d.view_key_of(item.floor): item for item in built}
    out: list[b3d.BuiltFloor] = []
    for item in built:
        candidates = stored.get(b3d.view_key_of(item.floor), ())
        hints: list[b3d.CoordinationHint] = []
        notes: dict[b3d.ViewKey, str] = {}
        for entry in candidates:
            reference = by_view.get(entry.reference_view)
            if (
                reference is None
                or entry.reference_view in notes
                or any(h.reference_view == entry.reference_view for h in hints)
            ):
                continue
            fits = [
                e
                for e in candidates
                if e.reference_view == entry.reference_view
                and e.target_axes_sha256 == coordination.axes_fingerprint(item.coord_axes)
                and e.reference_axes_sha256 == coordination.axes_fingerprint(reference.coord_axes)
            ]
            if not fits:
                notes[entry.reference_view] = STALE_NOTE
                continue
            hint = _hint_of(fits[0], item, reference)
            if isinstance(hint, str):
                notes[entry.reference_view] = RECOMPUTE_NOTE.format(reason=hint)
            else:
                hints.append(hint)
        out.append(
            dataclasses.replace(
                item, coordination=tuple(hints), coordination_notes=tuple(notes.items())
            )
            if hints or notes
            else item
        )
    return out


def _hint_of(
    entry: StoredCoordination, item: b3d.BuiltFloor, reference: b3d.BuiltFloor
) -> b3d.CoordinationHint | str:
    target_axes = {axis.id: axis for axis in item.coord_axes}
    reference_axes = {axis.id: axis for axis in reference.coord_axes}
    report = AiCoordinationReport(pairs=list(entry.pairs), notes="")
    kept, _ = coordination.sanitize_pairs(
        report, list(target_axes.values()), list(reference_axes.values())
    )
    offset = coordination.compute_offset(kept)
    if offset.status != "ok" or offset.offset_mm is None:
        return offset.reason or "нет согласных пар"
    return b3d.CoordinationHint(
        reference_view=entry.reference_view,
        offset_mm=offset.offset_mm,
        pairs=tuple(
            b3d.CoordinationPair(
                orient=p.orient,
                target_label=p.target_label,
                reference_label=p.reference_label,
                target_mm=p.target_mm,
                reference_mm=p.reference_mm,
                residual_mm=p.residual_mm,
            )
            for p in offset.used
        ),
    )
