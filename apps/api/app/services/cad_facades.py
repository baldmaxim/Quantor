"""Задание «Фасады» (`cad_facades`): виды фасадов АР по векторам и тексту PDF, решения человека.

Генератор `cad_facades/run_facades.py` движка (PyMuPDF, Shapely) запускает только cad-worker
подпроцессом; сюда он не импортируется. Версия генератора и sha256 параметров - пин `cad_facades`
из pins.json. Результат - кандидаты `cad_facade_views`; в расчёт попадает только принятое человеком,
а окна вида в проёмы плана на этом шаге не переносятся (ADR-0048, следующий шаг).

Повторный запуск для той же ревизии заменяет строки прежних заданий, а решения переносятся на
новые строки с теми же (страница, заголовок, оси вида).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_facades import FacadesFile, FacadeViewRead
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadFacadeView, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_pins
from app.services import jobs as jobs_service

FACADES_JSON: Final = "facades.json"
RUNNER_NAME: Final = "run_facades.py"
RESULT_READY: Final = "facades_ready"
# Привязка вида по отметкам, при которой вид можно принять.
ACCEPTABLE_SCALES: Final = ("fitted", "weak")


@dataclass(frozen=True, slots=True)
class FacadesParams:
    """Параметры генератора: путь к файлу, sha256 канонического JSON и версия генератора."""

    path: Path
    sha256: str
    generator_version: str


def runner_path(settings: Settings) -> Path | None:
    """Скрипт фасадов: `CAD_FACADES_RUNNER` или `<CAD_GENERATORS_ROOT>/cad_facades/`, иначе нет."""
    return cad_pins.generator_runner(
        settings,
        explicit=settings.cad_facades_runner,
        package="cad_facades",
        script=RUNNER_NAME,
    )


def load_params(settings: Settings) -> FacadesParams:
    """Версия и sha256 параметров - из `pins.json` (`generators.cad_facades`); нет пина - отказ.

    Файл параметров читает только исполнитель; если он настроен, его байты сверяются с пином.
    """
    try:
        pin = cad_pins.load_generator_pin(settings, "cad_facades")
    except DomainError as error:
        raise DomainError(
            ErrorCode.CAD_ENGINE_UNAVAILABLE, f"Генератор фасадов не настроен: {error.detail}"
        ) from error
    path, configured = cad_pins.params_file(settings, settings.cad_facades_params, pin)
    if configured:
        cad_pins.verify_params_file(path, pin, "cad_facades")
    return FacadesParams(
        path=path, sha256=pin.params_canonical_sha256, generator_version=pin.generator_version
    )


def idempotency_key(
    revision_id: uuid.UUID,
    *,
    params_sha256: str,
    generator_version: str,
    page_indexes: list[int] | None,
) -> str:
    """Та же ревизия, параметры, версия генератора и набор страниц - то же задание."""
    pages = "all" if page_indexes is None else ",".join(str(i) for i in sorted(page_indexes))
    digest = hashlib.sha256(
        "|".join((str(revision_id), params_sha256, generator_version, pages)).encode()
    ).hexdigest()
    return f"cadfacades:{digest[:48]}"


def normalized_pages(page_indexes: list[int] | None) -> list[int] | None:
    """Страницы без повторов по возрастанию; пусто (`None`) - все страницы PDF."""
    if page_indexes is None:
        return None
    if len(set(page_indexes)) != len(page_indexes):
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "page_indexes: индексы без повторов")
    return sorted(page_indexes)


async def schedule(
    session: AsyncSession,
    *,
    project: Project,
    revision: DocumentRevision,
    page_indexes: list[int] | None,
    settings: Settings,
) -> Job:
    """Задание `cad_facades` по исходному PDF ревизии; тот же ключ - то же задание."""
    if not cad_service.is_pdf(revision):
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Источник ревизии не PDF")
    pages = normalized_pages(page_indexes)
    params = load_params(settings)
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_FACADES,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=idempotency_key(
            revision.id,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            page_indexes=pages,
        ),
        payload={
            "revision_id": str(revision.id),
            "page_indexes": pages,
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
        },
    )


async def latest_jobs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, revision_id: uuid.UUID
) -> tuple[Job | None, Job | None]:
    """Последнее задание ревизии и последнее выполненное; задания - только своего пространства."""
    base = select(Job).where(
        Job.job_type == JobType.CAD_FACADES,
        Job.workspace_id == workspace_id,
        Job.project_id == project_id,
        Job.payload["revision_id"].astext == str(revision_id),
    )
    latest = await session.scalar(
        base.order_by(Job.created_at.desc(), Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if latest is None:
        return None, None
    if latest.status is JobStatus.SUCCEEDED:
        return latest, latest
    done = await session.scalar(
        base.where(Job.status == JobStatus.SUCCEEDED)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return latest, done


# ------------------------------------------------------------------ публикация и чтение видов

_DecisionKey = tuple[int, str, str | None, str | None, str]


def _decision_key(
    page_index: int, title: str, axis_from: str | None, axis_to: str | None, fingerprint: str
) -> _DecisionKey:
    return (page_index, title, axis_from, axis_to, fingerprint)


def _rounded(values: Any) -> list[float] | None:
    """Доли страницы до 1e-6: отпечаток не зависит от шума записи."""
    if not isinstance(values, list):
        return None
    return [round(v, 6) if isinstance(v, int | float) else 0.0 for v in values]


def _fingerprint(
    scale_status: str,
    mm_per_pt: float | None,
    window_count: int,
    windows: list[dict[str, Any]],
    marks: list[dict[str, Any]],
    axes: list[dict[str, Any]],
) -> str:
    """Отпечаток чисел вида: решение переносится, только если они не изменились.

    Привязка, масштаб (до 0,001), число окон, sha256 канонического JSON окон
    `(z_bottom_mm, z_top_mm, u0_mm, u1_mm, width_mm, bbox)`, отметок `(value_mm, used)` и осей
    вида `(label, label_full, x)`: окна `bbox` и оси - входы сопоставления с планом (ADR-0048).
    """
    scale = None if mm_per_pt is None else round(mm_per_pt, 3)
    payload = {
        "scale_status": scale_status,
        "mm_per_pt": scale,
        "window_count": window_count,
        "windows": [
            [
                *(w.get(k) for k in ("z_bottom_mm", "z_top_mm", "u0_mm", "u1_mm", "width_mm")),
                _rounded(w.get("bbox")),
            ]
            for w in windows
        ],
        "axes": [[a.get("label"), a.get("label_full"), _rounded([a.get("x")])] for a in axes],
        "marks": [[m.get("value_mm"), m.get("used")] for m in marks],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


async def publish_views(
    session: AsyncSession,
    *,
    job: Job,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    document: FacadesFile,
) -> int:
    """Строки видов задания; строки прежних заданий ревизии заменяются, решения переносятся.

    Задание по части страниц (`payload.page_indexes`) заменяет только строки этих страниц; строки
    других страниц и их решения остаются. Задание по всем страницам заменяет все строки ревизии.
    Прежние строки читаются с блокировкой, чтобы параллельное решение не потерялось.

    Решение переносится на новую строку с тем же ключом: (страница, заголовок, оси вида, отпечаток
    чисел вида); статус, автор и время копируются. Изменились числа (привязка, масштаб, окна,
    использованные отметки) - не переносится. Ключ должен быть однозначным среди прежних строк
    (решённых или нет) и среди новых, иначе решение не переносится; `accepted` не переносится на
    вид без привязки по отметкам. Решения к исчезнувшим строкам теряются.
    Вызывается в транзакции записи успеха задания. Возвращает число новых строк.
    """
    pages = job.payload.get("page_indexes")
    scope = [CadFacadeView.page_index.in_([int(item) for item in pages])] if pages else []
    previous = list(
        (
            await session.scalars(
                select(CadFacadeView)
                .where(
                    CadFacadeView.project_id == project_id,
                    CadFacadeView.revision_id == revision_id,
                    CadFacadeView.job_id != job.id,
                    *scope,
                )
                .order_by(CadFacadeView.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    old_counts = Counter(
        _decision_key(
            old.page_index,
            old.title,
            old.axis_from,
            old.axis_to,
            _fingerprint(
                old.scale_status,
                old.mm_per_pt,
                old.window_count,
                old.windows,
                old.marks,
                old.axes,
            ),
        )
        for old in previous
    )
    carried: dict[_DecisionKey, tuple[str, uuid.UUID, datetime]] = {}
    for old in previous:
        if old.status != "candidate" and old.decided_by is not None and old.decided_at is not None:
            key = _decision_key(
                old.page_index,
                old.title,
                old.axis_from,
                old.axis_to,
                _fingerprint(
                    old.scale_status,
                    old.mm_per_pt,
                    old.window_count,
                    old.windows,
                    old.marks,
                    old.axes,
                ),
            )
            carried[key] = (old.status, old.decided_by, old.decided_at)
        await session.delete(old)
    await session.flush()

    new_dumps = [
        (
            [item.model_dump(mode="json") for item in view.windows],
            [item.model_dump(mode="json") for item in view.marks],
            [item.model_dump(mode="json") for item in view.axes],
        )
        for view in document.views
    ]
    new_keys = [
        _decision_key(
            view.page_index,
            view.title,
            view.axis_from,
            view.axis_to,
            _fingerprint(
                view.scale.status,
                view.scale.mm_per_pt,
                len(view.windows),
                new_dumps[number][0],
                new_dumps[number][1],
                new_dumps[number][2],
            ),
        )
        for number, view in enumerate(document.views)
    ]
    new_counts = Counter(new_keys)
    for seq, view in enumerate(document.views):
        key = new_keys[seq]
        decision = None if old_counts[key] > 1 or new_counts[key] > 1 else carried.get(key)
        if (
            decision is not None
            and decision[0] == "accepted"
            and view.scale.status not in ACCEPTABLE_SCALES
        ):
            decision = None
        session.add(
            CadFacadeView(
                workspace_id=workspace_id,
                project_id=project_id,
                job_id=job.id,
                revision_id=revision_id,
                seq=seq,
                page_index=view.page_index,
                view_key=view.id,
                title=view.title,
                axis_from=view.axis_from,
                axis_to=view.axis_to,
                corps=view.corps,
                section=view.section,
                body=view.body,
                scale_status=view.scale.status,
                mm_per_pt=view.scale.mm_per_pt,
                residual_mm=view.scale.residual_mm,
                bbox=list(view.bbox),
                axes=[item.model_dump(mode="json") for item in view.axes],
                marks=new_dumps[seq][1],
                floors=[item.model_dump(mode="json") for item in view.floors],
                windows=new_dumps[seq][0],
                window_count=len(view.windows),
                status="candidate" if decision is None else decision[0],
                decided_by=None if decision is None else decision[1],
                decided_at=None if decision is None else decision[2],
            )
        )
    await session.flush()
    return len(document.views)


async def list_views(
    session: AsyncSession, *, project_id: uuid.UUID, revision_id: uuid.UUID
) -> list[CadFacadeView]:
    rows = await session.scalars(
        select(CadFacadeView)
        .where(CadFacadeView.project_id == project_id, CadFacadeView.revision_id == revision_id)
        .order_by(CadFacadeView.page_index, CadFacadeView.seq, CadFacadeView.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


def view_read(row: CadFacadeView) -> FacadeViewRead:
    """Строка -> ответ API; статус и вложенные данные проверяются моделью."""
    return FacadeViewRead.model_validate(row, from_attributes=True)


def _decidable(row: CadFacadeView) -> str | None:
    """Почему вид нельзя принять; `None` - можно."""
    if row.scale_status not in ACCEPTABLE_SCALES:
        return (
            "у вида нет привязки по отметкам "
            f"(статус привязки: {row.scale_status}); принять можно только fitted или weak"
        )
    return None


async def decide(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    view_ids: list[uuid.UUID],
    decision: str,
    user_id: uuid.UUID,
) -> list[CadFacadeView]:
    """Решение человека по видам: `accept`, `reject` или `reset` (обратно в кандидаты).

    Чужой проект или пространство - 404. Принять вид без привязки по отметкам (`fitted` или `weak`)
    нельзя: 422 с причиной, ничего не меняется.
    """
    unique = set(view_ids)
    rows = list(
        (
            await session.scalars(
                select(CadFacadeView)
                .where(
                    CadFacadeView.id.in_(unique),
                    CadFacadeView.project_id == project_id,
                    CadFacadeView.workspace_id == workspace_id,
                )
                .order_by(CadFacadeView.page_index, CadFacadeView.seq, CadFacadeView.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) != len(unique):
        raise not_found("Вид фасада")
    if decision == "accept":
        failed = [
            f"стр. {row.page_index + 1}, «{row.title}»: {why}"
            for row in rows
            if (why := _decidable(row))
        ]
        if failed:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, "Принять нельзя - " + "; ".join(failed[:5])
            )
    now = datetime.now(UTC)
    for row in rows:
        if decision == "reset":
            row.status, row.decided_by, row.decided_at = "candidate", None, None
        else:
            row.status = "accepted" if decision == "accept" else "rejected"
            row.decided_by, row.decided_at = user_id, now
    await session.flush()
    return rows
