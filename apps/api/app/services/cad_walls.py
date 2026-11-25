"""Задание `cad_walls` (ADR-0038): параметры скрипта, постановка и поиск результата вида.

Задание строит `walls.json` по DXF вида результата `cad_pdf_convert`. Ставится автоматически
после успешной конвертации (для каждого вида с DXF) и вручную — пересчётом. Модуль стандартный:
скрипт `generators/cad_walls` репозитория движка (Shapely, ezdxf, PyMuPDF) запускает только
cad-worker подпроцессом. Версия скрипта и sha256 параметров берутся из pins.json.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadRemark, Job
from app.models.sheet_passport import SheetPassport
from app.services import cad as cad_service
from app.services import cad_pins, cad_remarks, cad_requeue, cad_walls_zones
from app.services import jobs as jobs_service
from app.services.cad_walls_version import parse_walls_version
from app.services.consistency.dictionaries import SheetKind
from app.storage.base import ObjectStorage

log = get_logger(__name__)

WALLS_JSON: Final = "walls.json"
# Контроль движка PDF->DXF (`Контроль_CAD.json`) в артефактах конвертации; вход `--control` скрипта.
CONTROL_ARTIFACT: Final = "cad_checks.json"
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class WallsParams:
    """Параметры скрипта: путь, sha256 канонического JSON, версия скрипта и версия параметров."""

    path: Path
    sha256: str
    generator_version: str
    params_version: str


def runner_path(settings: Settings) -> Path | None:
    """Скрипт конструкций: `CAD_WALLS_RUNNER` или `<CAD_GENERATORS_ROOT>/cad_walls/run_walls.py`."""
    return cad_pins.generator_runner(
        settings, explicit=settings.cad_walls_runner, package="cad_walls", script="run_walls.py"
    )


def load_params(settings: Settings) -> WallsParams:
    """Версия скрипта и sha256 параметров берутся из `pins.json` (раздел `generators`).

    sha256 - канонического JSON параметров (как у скрипта и у параметров движка); версия
    параметров - имя файла без расширения (так её пишет скрипт в walls.json). Файл параметров
    читает только исполнитель; если он настроен (`CAD_WALLS_PARAMS` или `CAD_GENERATORS_ROOT`), его
    байты сверяются с пином. Нет закрепления - отказ, а не умолчание.
    """
    pin = cad_pins.load_generator_pin(settings, "cad_walls")
    path, configured = cad_pins.params_file(settings, settings.cad_walls_params, pin)
    if configured:
        cad_pins.verify_params_file(path, pin, "cad_walls")
    return WallsParams(
        path=path,
        sha256=pin.params_canonical_sha256,
        generator_version=pin.generator_version,
        params_version=path.stem,
    )


REBUILD_REMARK_TYPES: Final = ("missing_wall", "false_wall", "missing_door")
# Первая версия cad_walls, принимающая `--hints`.
HINTS_MIN_VERSION: Final = (1, 26, 0)


def _hints_of(payload: dict[str, Any]) -> list[dict[str, object]] | None:
    raw = payload.get("hints")
    if not isinstance(raw, list) or not raw:
        return None
    return [item for item in raw if isinstance(item, dict)]


def hints_sha256(hints: Sequence[dict[str, object]] | None) -> str:
    """sha256 канонического JSON подсказок; нет подсказок - пустая строка."""
    if not hints:
        return ""
    raw = json.dumps(list(hints), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def hints_from_remarks(remarks: Sequence[CadRemark]) -> list[dict[str, object]]:
    """Открытые замечания подходящих типов -> подсказки: id = ключ замечания, рамка в pt PDF."""
    rows = sorted(
        (r for r in remarks if r.status == "open" and r.type in REBUILD_REMARK_TYPES),
        key=lambda r: r.remark_key,
    )
    return [
        {
            "id": r.remark_key,
            "type": r.type,
            "bbox_pt": [r.bbox_x0, r.bbox_y0, r.bbox_x1, r.bbox_y1],
            "construction_ids": [],
            "comment": r.comment,
        }
        for r in rows
    ]


def ensure_hints_supported(generator_version: str) -> None:
    """Скрипт закреплён версией ниже v1.26 или версия не читается - перестроить нельзя."""
    parsed = parse_walls_version(generator_version)
    if parsed is None or parsed < HINTS_MIN_VERSION:
        raise DomainError(
            ErrorCode.CAD_ENGINE_UNAVAILABLE, "Движок не поддерживает перестроение по замечаниям"
        )


def idempotency_key(
    parent_id: uuid.UUID,
    *,
    parent_attempt: int,
    page_index: int,
    view: int,
    params_sha256: str,
    generator_version: str,
    sequence: int,
    zones_sha256: str = "",
    hints_sha256: str = "",
) -> str:
    """Тот же вид, параметры, зоны и версия скрипта — то же задание; пересчёт — следующий номер.

    Подсказки по замечаниям входят в ключ только когда они есть: без них ключ прежний.
    """
    parts = [
        str(parent_id),
        str(parent_attempt),
        str(page_index),
        str(view),
        params_sha256,
        generator_version,
        zones_sha256,
        str(sequence),
    ]
    if hints_sha256:
        parts.append(hints_sha256)
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"cadwalls:{digest[:48]}"


def view_has_dxf(parent: Job, page_index: int, view: int) -> dict[str, Any] | None:
    """Артефакт DXF вида в текущем итоге родителя; нет вида или DXF — `None`."""
    result = cad_service.current_result(parent)
    for page in result.get("pages", []):
        if page.get("index") != page_index:
            continue
        for row in page.get("views", []):
            if isinstance(row, dict) and row.get("view") == view:
                try:
                    folder = cad_service.view_folder(page_index, view)
                except ValueError:
                    return None
                return cad_service.find_artifact(parent, f"{folder}/plan_candidates.dxf")
    return None


async def walls_jobs_of_view(
    session: AsyncSession, *, parent: Job, page_index: int, view: int
) -> list[Job]:
    """Задания конструкций вида (все попытки родителя), новые сверху."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.job_type == JobType.CAD_WALLS,
            Job.workspace_id == parent.workspace_id,
            Job.payload["parent_job_id"].astext == str(parent.id),
            Job.payload["page_index"].astext == str(page_index),
            Job.payload["view"].astext == str(view),
        )
        .order_by(Job.created_at.desc(), Job.id)
    )
    return list(rows)


def _walls_payload(
    parent: Job,
    *,
    page_index: int,
    view: int,
    dxf_sha256: str,
    params: WallsParams,
    zones: cad_walls_zones.ZonesInput,
    hints: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "revision_id": parent.payload["revision_id"],
        "parent_job_id": str(parent.id),
        "parent_attempt": cad_service.result_of(parent).get("attempt"),
        "page_index": page_index,
        "view": view,
        "view_dxf_sha256": dxf_sha256,
        "params_sha256": params.sha256,
        "params_version": params.params_version,
        "generator_version": params.generator_version,
        "engine_version": params.generator_version,
        # зоны помещений листа для контура плиты: пусты — стены без зон (прежнее поведение)
        "zones_sha256": zones.sha256,
        "zones_size": len(zones.raw),
        "zones_count": zones.count,
    }
    if zones.warning is not None:
        payload["zones_warning"] = zones.warning
    if zones.view_zone is not None:
        # прямоугольник вида в pt PDF: скрипт по центру выбирает заголовок плана (`--view-zone`)
        payload["view_zone"] = list(zones.view_zone)
    if zones.frame is not None:
        # кадр вида: знаки отметок плана -> участки плиты (`--frame`, cad_walls v1.15)
        payload["view_frame"] = list(zones.frame)
    if hints:
        # замечания проверяющего (`--hints`, v1.26): рамки в pt PDF, в мм их переводит исполнитель
        payload["hints"] = hints
    return payload


async def _enqueue(
    session: AsyncSession,
    *,
    parent: Job,
    page_index: int,
    view: int,
    dxf: dict[str, Any],
    params: WallsParams,
    sequence: int,
    zones: cad_walls_zones.ZonesInput = cad_walls_zones.NO_ZONES,
    hints: list[dict[str, object]] | None = None,
) -> Job:
    attempt = cad_service.result_of(parent).get("attempt")
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_WALLS,
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        idempotency_key=idempotency_key(
            parent.id,
            parent_attempt=int(attempt) if type(attempt) is int else 0,
            page_index=page_index,
            view=view,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            sequence=sequence,
            zones_sha256=zones.sha256,
            hints_sha256=hints_sha256(hints),
        ),
        payload=_walls_payload(
            parent,
            page_index=page_index,
            view=view,
            dxf_sha256=str(dxf["sha256"]),
            params=params,
            zones=zones,
            hints=hints,
        ),
    )


# Вход задания, который переносится в перепоставленное задание без изменений.
_INPUT_KEYS: Final = (
    "revision_id",
    "parent_job_id",
    "parent_attempt",
    "page_index",
    "view",
    "view_dxf_sha256",
    "zones_sha256",
    "zones_size",
    "zones_count",
    "zones_warning",
    "view_zone",
    "view_frame",
    "hints",
)


async def requeue_with_current_params(
    session: AsyncSession, *, job: Job, parent: Job, params: WallsParams
) -> Job:
    """То же задание конструкций с действующими параметрами: пин сменился после постановки.

    Вход (вид, DXF, зоны) переносится как есть, меняются только версия скрипта и параметры;
    ключ идемпотентности новый, потому что включает их.
    """
    payload: dict[str, object] = {
        key: job.payload[key] for key in _INPUT_KEYS if key in job.payload
    }
    page_index, view = int(str(payload["page_index"])), int(str(payload["view"]))
    attempt = payload.get("parent_attempt")
    existing = await walls_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    payload.update(
        {
            "params_sha256": params.sha256,
            "params_version": params.params_version,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
            cad_requeue.REQUEUED_FROM: str(job.id),
        }
    )
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_WALLS,
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        idempotency_key=idempotency_key(
            parent.id,
            parent_attempt=attempt if type(attempt) is int else 0,
            page_index=page_index,
            view=view,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            sequence=len(existing),
            zones_sha256=str(payload.get("zones_sha256") or ""),
            hints_sha256=hints_sha256(_hints_of(payload)),
        ),
        payload=payload,
    )


# Виды листа, на которых автопостановка `cad_walls` не нужна: разрез и фасад — не план этажа.
# Кровли — планы, их не трогаем; лист без паспорта или с неподтверждённым видом идёт как раньше.
_NOT_PLAN_KINDS: Final = frozenset({SheetKind.SECTION.value, SheetKind.FACADE.value})


async def _not_plan_pages(session: AsyncSession, parent: Job) -> set[int]:
    """Страницы ревизии конвертации, у которых подтверждённый паспорт — разрез или фасад."""
    raw = parent.payload.get("revision_id")
    try:
        revision_id = uuid.UUID(str(raw))
    except ValueError:
        return set()
    rows = await session.execute(
        select(SheetPassport.page_index).where(
            SheetPassport.revision_id == revision_id,
            SheetPassport.sheet_kind.in_(_NOT_PLAN_KINDS),
            # Только подтверждённый человеком паспорт: вид кандидата по заголовку может ошибаться.
            SheetPassport.status == "confirmed",
        )
    )
    return {int(index) for index in rows.scalars()}


async def enqueue_after_convert(
    session: AsyncSession, storage: ObjectStorage, parent: Job, settings: Settings
) -> list[Job]:
    """Автопостановка: по заданию на каждый вид успешного `cad_pdf_convert`, у которого есть DXF.

    Вызывается в транзакции записи успеха конвертации: задания появляются вместе с результатом.
    Параметры скрипта не нашлись — конвертация остаётся успешной, а конструкции ставятся
    вручную после исправления установки. Зоны помещений листа уходят входом задания, как у
    пересчёта; сбой их чтения конвертацию не рушит (задание без зон, причина в `zones_warning`).
    """
    try:
        params = load_params(settings)
    except DomainError:
        log.warning("cad_walls_params_unavailable", job_id=str(parent.id))
        return []
    jobs: list[Job] = []
    not_plans = await _not_plan_pages(session, parent)
    for page in cad_service.result_of(parent).get("pages", []):
        for row in page.get("views", []):
            page_index, view = page.get("index"), row.get("view")
            if type(page_index) is not int or type(view) is not int:
                continue
            dxf = view_has_dxf(parent, page_index, view)
            if dxf is None:
                continue
            if page_index in not_plans:
                # Разрез или фасад по паспорту листа: конструкций плана этажа там нет, а cad_walls
                # принял бы линии разреза за сотни стен и дверей.
                log.info("cad_walls_skipped_not_plan", job_id=str(parent.id), page_index=page_index)
                continue
            zones = await cad_walls_zones.prepare_or_empty(
                session, storage, parent=parent, page_index=page_index, view=view
            )
            jobs.append(
                await _enqueue(
                    session,
                    parent=parent,
                    page_index=page_index,
                    view=view,
                    dxf=dxf,
                    params=params,
                    sequence=0,
                    zones=zones,
                )
            )
    return jobs


async def schedule_after_auto_zones(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    settings: Settings,
) -> Job | None:
    """Пересчёт конструкций вида после появления зон авторазметки; без 409 и без исключений.

    Первое задание листа без разметки человека уходит до авторазметки, то есть без зон. Нет DXF,
    параметров или самих зон либо уже активно задание вида с теми же зонами — ничего не
    ставится, причина в логе; активное задание без этих зон пересчёт не блокирует. Цикла нет:
    зоны авторазметка создаёт на пустом листе или при ручном пересоздании авто-зон, задание
    конструкций разметку не ставит, а ключ идемпотентности включает хеш зон и номер пересчёта.
    Зоны, отклонённые сверкой с экспликацией, во вход не идут (`cad_zones_review.usable`).
    """
    try:
        params = load_params(settings)
    except DomainError:
        log.warning("cad_walls_params_unavailable", job_id=str(parent.id))
        return None
    await session.refresh(parent, with_for_update=True)
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        return None
    dxf = view_has_dxf(parent, page_index, view)
    if dxf is None:
        return None
    existing = await walls_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    zones = await cad_walls_zones.prepare_or_empty(
        session, storage, parent=parent, page_index=page_index, view=view
    )
    if not zones.present:
        log.info(
            "cad_walls_recompute_skipped_no_zones",
            job_id=str(parent.id),
            page_index=page_index,
            view=view,
        )
        return None
    # Активное задание вида с теми же зонами уже всё сделает. Активное без них (или с другими)
    # не мешает: пересчёт ставится следующим, а API берёт последнее успешное задание по created_at.
    if any(
        job.status in _ACTIVE and job.payload.get("zones_sha256") == zones.sha256
        for job in existing
    ):
        log.info(
            "cad_walls_recompute_skipped_same_zones",
            job_id=str(parent.id),
            page_index=page_index,
            view=view,
        )
        return None
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=params,
        sequence=len(existing),
        zones=zones,
    )


async def _schedule(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    settings: Settings,
    rebuild_by_remarks: bool,
) -> Job:
    if parent.job_type is not JobType.CAD_PDF_CONVERT:
        raise not_found("Задание")
    await session.refresh(parent, with_for_update=True)
    if parent.status is not JobStatus.SUCCEEDED or not cad_service.current_result(parent):
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    dxf = view_has_dxf(parent, page_index, view)
    if dxf is None:
        raise not_found("Вид")
    params = load_params(settings)
    hints: list[dict[str, object]] | None = None
    if rebuild_by_remarks:
        ensure_hints_supported(params.generator_version)
        attempt = cad_service.result_of(parent).get("attempt")
        remarks = await cad_remarks.list_remarks(
            session,
            job=parent,
            attempt=attempt if type(attempt) is int else 0,
            page_index=page_index,
            view=view,
        )
        hints = hints_from_remarks(remarks)
        if not hints:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "Нет открытых замечаний вида типов «Нет стены», «Лишняя стена», «Нет двери»",
            )
    existing = await walls_jobs_of_view(session, parent=parent, page_index=page_index, view=view)
    if any(job.status in _ACTIVE for job in existing):
        raise DomainError(ErrorCode.CAD_WALLS_BUSY)
    zones = await cad_walls_zones.prepare(
        session, storage, parent=parent, page_index=page_index, view=view
    )
    if hints and zones.frame is None:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Кадр вида не подтверждён: рамки замечаний нельзя перевести в миллиметры",
        )
    return await _enqueue(
        session,
        parent=parent,
        page_index=page_index,
        view=view,
        dxf=dxf,
        params=params,
        sequence=len(existing),
        zones=zones,
        hints=hints,
    )


async def schedule_recompute(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
    settings: Settings,
) -> Job:
    """Пересчёт конструкций вида новым заданием.

    Зоны квартир и МОП страницы уходят входом задания (контур плиты); нет кадра вида — без зон.

    Нельзя, пока задание этого вида в очереди или выполняется (409 `CAD_WALLS_BUSY`). Строка
    родителя берётся под блокировкой: два одновременных нажатия не ставят задание дважды.
    """
    return await _schedule(
        session,
        storage,
        parent=parent,
        page_index=page_index,
        view=view,
        settings=settings,
        rebuild_by_remarks=False,
    )


async def schedule_rebuild_by_remarks(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    walls_job: Job,
    settings: Settings,
) -> Job:
    """Перестроение конструкций вида по открытым замечаниям проверяющего (cad_walls v1.26).

    Вид и попытка берутся из задания `cad_walls`: родитель — `parent_job_id`, замечания — его
    `parent_attempt`, страница и вид. Замечания не меняются и не закрываются. Те же блокировки и
    отказы, что у пересчёта; нет подходящих замечаний или версия скрипта старше v1.26 - отказ.
    """
    payload = walls_job.payload
    page_index, view = payload.get("page_index"), payload.get("view")
    try:
        parent_id = uuid.UUID(str(payload.get("parent_job_id")))
    except ValueError as error:
        raise not_found("Задание") from error
    parent = await session.get(Job, parent_id)
    if parent is None or type(page_index) is not int or type(view) is not int:
        raise not_found("Задание")
    return await _schedule(
        session,
        storage,
        parent=parent,
        page_index=page_index,
        view=view,
        settings=settings,
        rebuild_by_remarks=True,
    )
