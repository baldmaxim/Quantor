"""Постановка задания извлечения геометрии.

Общая точка для обоих сценариев: обычной загрузки PDF и импорта распознанного пакета.
Живёт в пакете геометрии, а не в приёме файлов, потому что вызывающих двое, а правило
одно (ADR-0016).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobType
from app.models import DocumentRevision, Job, Project
from app.services import jobs as jobs_service
from app.services.geometry.extract import idempotency_key
from app.services.geometry.provider import PypdfGeometryProvider


async def schedule_extract(
    session: AsyncSession, *, project: Project, revision: DocumentRevision
) -> Job:
    """Ставит задание извлечения геометрии для ревизии PDF.

    Ключ идемпотентности включает версию парсера: повтор тем же парсером задания не
    создаёт, а смена версии создаёт — геометрия могла измениться, и это должно быть видно,
    а не скрыто идемпотентностью прежнего задания.

    Задание проектное: у него всегда есть владелец, общесистемным оно быть не может.
    """
    provider = PypdfGeometryProvider()
    return await jobs_service.enqueue(
        session,
        job_type=JobType.PDF_GEOMETRY_EXTRACT,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=idempotency_key(revision.id, provider),
        payload={"revision_id": str(revision.id)},
    )
