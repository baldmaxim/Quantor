"""Модель здания из загруженных IFC проекта (ADR-0053): постановка задания `model_ifc_import`.

IFC лежат в проекте обычными документами (`DocumentKind.IFC`, ревизии неизменяемы). Задание берёт
последнюю ревизию каждого IFC (или выбранные), запускает генератор `cad_model` из репозитория
движка подпроцессом в cad-worker и сохраняет результат версией модели (кандидат). Тот же набор
ревизий, параметры и версия генератора - то же задание; другая ревизия любого IFC - новое.

Модуль стандартный: генератор запускает только cad-worker; версия генератора и sha256 параметров
берутся из pins.json (`generators.cad_model`).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import DocumentKind, JobType
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_pins
from app.services import jobs as jobs_service

MAX_IFC_FILES: Final = 40
MAX_TOTAL_BYTES: Final = 4 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ModelParams:
    """Параметры генератора: путь к файлу, sha256 канонического JSON и версия генератора."""

    path: Path
    sha256: str
    generator_version: str


def runner_path(settings: Settings) -> Path | None:
    """Скрипт: `CAD_MODEL_RUNNER` или `<CAD_GENERATORS_ROOT>/cad_model/run_model.py`."""
    return cad_pins.generator_runner(
        settings, explicit=settings.cad_model_runner, package="cad_model", script="run_model.py"
    )


def load_params(settings: Settings) -> ModelParams:
    """Версия и sha256 параметров - из `pins.json` (`generators.cad_model`); нет пина - отказ."""
    pin = cad_pins.load_generator_pin(settings, "cad_model")
    path, configured = cad_pins.params_file(settings, settings.cad_model_params, pin)
    if configured:
        cad_pins.verify_params_file(path, pin, "cad_model")
    return ModelParams(
        path=path, sha256=pin.params_canonical_sha256, generator_version=pin.generator_version
    )


def import_idempotency_key(
    source_sha256: list[str], *, params_sha256: str, generator_version: str
) -> str:
    """Тот же набор ревизий IFC, параметры и версия генератора - то же задание."""
    digest = hashlib.sha256(
        "|".join((*sorted(source_sha256), params_sha256, generator_version)).encode()
    ).hexdigest()
    return f"modelifc:{digest[:48]}"


async def project_ifc_revisions(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[tuple[Document, DocumentRevision]]:
    """Последняя ревизия каждого IFC проекта, по имени файла."""
    rows = await session.execute(
        select(Document, DocumentRevision)
        .join(DocumentRevision, DocumentRevision.document_id == Document.id)
        .where(Document.project_id == project_id, Document.document_kind == DocumentKind.IFC)
        .order_by(Document.id, DocumentRevision.created_at.desc())
    )
    latest: dict[uuid.UUID, tuple[Document, DocumentRevision]] = {}
    for document, revision in rows:
        latest.setdefault(document.id, (document, revision))
    return sorted(latest.values(), key=lambda pair: pair[1].source_filename.casefold())


async def _chosen(
    session: AsyncSession, *, project_id: uuid.UUID, revision_ids: list[uuid.UUID]
) -> list[tuple[Document, DocumentRevision]]:
    rows = await session.execute(
        select(Document, DocumentRevision)
        .join(DocumentRevision, DocumentRevision.document_id == Document.id)
        .where(
            Document.project_id == project_id,
            Document.document_kind == DocumentKind.IFC,
            DocumentRevision.id.in_(revision_ids),
        )
    )
    found = {revision.id: (document, revision) for document, revision in rows}
    if set(found) != set(revision_ids):
        raise DomainError(ErrorCode.MODEL_IFC_NOT_FOUND, "Выбранные IFC не найдены в проекте")
    return sorted(found.values(), key=lambda pair: pair[1].source_filename.casefold())


async def schedule_import(
    session: AsyncSession,
    *,
    project: Project,
    user_id: uuid.UUID,
    revision_ids: list[uuid.UUID] | None,
    settings: Settings,
) -> Job:
    """Задание `model_ifc_import` по выбранным ревизиям IFC или по всем IFC проекта."""
    pairs = (
        await _chosen(session, project_id=project.id, revision_ids=revision_ids)
        if revision_ids
        else await project_ifc_revisions(session, project_id=project.id)
    )
    if not pairs:
        raise DomainError(ErrorCode.MODEL_IFC_NOT_FOUND)
    if len(pairs) > MAX_IFC_FILES or sum(r.source_size for _, r in pairs) > MAX_TOTAL_BYTES:
        raise DomainError(ErrorCode.MODEL_IFC_NOT_FOUND, "Слишком много IFC для одного задания")
    params = load_params(settings)
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.MODEL_IFC_IMPORT,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=import_idempotency_key(
            [revision.source_sha256 for _, revision in pairs],
            params_sha256=params.sha256,
            generator_version=params.generator_version,
        ),
        payload={
            "inputs": [
                {
                    "revision_id": str(revision.id),
                    "document_id": str(document.id),
                    "filename": revision.source_filename,
                    "sha256": revision.source_sha256,
                    "size": revision.source_size,
                }
                for document, revision in pairs
            ],
            "requested_by": str(user_id),
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
        },
    )
    return await cad_service.requeue_if_retryable_failure(
        session, job, settings=settings, refresh=False
    )


async def latest_import_job(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Job | None:
    """Новейшее `model_ifc_import` проекта в любом статусе: для показа хода и отказа."""
    found: Job | None = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.MODEL_IFC_IMPORT,
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return found
