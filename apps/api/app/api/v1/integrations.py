"""Внешние системы: TenderHUB.

Портал берёт из TenderHUB только то, что делает тендер проектом, — номер, название и
заказчика. Позиции ВОР и строки смет не читаются: на Stage 1 портал не считает объёмы
и не ведёт смету, а показать чужой расчёт как свой результат — худший вид неправды
в таком продукте.

Ключ доступа живёт в окружении сервера и наружу не выходит ни в каком виде. Браузер
ходит в портал, портал — в TenderHUB.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.v1.deps import SessionDep, TenderHubDep, WorkspaceDep
from app.domain import ProjectSource
from app.errors import DomainError, ErrorCode
from app.integrations.tenderhub import TenderBrief
from app.schemas import ProjectRead, TenderBriefRead, TenderImport
from app.services import projects as projects_service

router = APIRouter(prefix="/integrations/tenderhub", tags=["integrations"])


@router.get(
    "/tenders",
    response_model=list[TenderBriefRead],
    summary="Тендеры, доступные ключу",
)
async def list_tenders(
    session: SessionDep,
    workspace: WorkspaceDep,
    client: TenderHubDep,
    search: str | None = None,
) -> list[TenderBriefRead]:
    tenders = await client.list_tenders(search=search)

    # Какие тендеры уже стали проектами — одним запросом, а не по строке на каждый.
    linked = await projects_service.map_external_ids(
        session,
        workspace_id=workspace.workspace_id,
        source=ProjectSource.TENDERHUB,
        external_ids=[tender.id for tender in tenders],
    )

    return [
        TenderBriefRead(
            id=tender.id,
            tender_number=tender.tender_number,
            title=tender.title,
            client_name=tender.client_name,
            version=tender.version,
            construction_scope=tender.construction_scope,
            submission_deadline=tender.submission_deadline,
            updated_at=tender.updated_at,
            imported_project_id=linked.get(tender.id),
        )
        for tender in tenders
    ]


@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект по тендеру",
)
async def import_tender(
    payload: TenderImport,
    session: SessionDep,
    workspace: WorkspaceDep,
    client: TenderHubDep,
) -> ProjectRead:
    existing = await projects_service.find_by_external_id(
        session,
        workspace_id=workspace.workspace_id,
        source=ProjectSource.TENDERHUB,
        external_id=payload.tender_id,
    )
    if existing is not None:
        raise DomainError(ErrorCode.TENDERHUB_ALREADY_LINKED)

    tender = await client.get_tender(payload.tender_id)

    project = await projects_service.create_project(
        session,
        workspace_id=workspace.workspace_id,
        name=payload.name or project_name(tender),
        source=ProjectSource.TENDERHUB,
        external_id=payload.tender_id,
        external_ref=tender.tender_number,
    )
    await session.commit()
    return ProjectRead.model_validate(project)


def project_name(tender: TenderBrief) -> str:
    """Имя проекта по тендеру.

    Номер впереди: инженеры ищут тендер по номеру, а названия у соседних тендеров
    часто отличаются одним словом в конце. Если названия нет — остаётся номер.
    """
    parts = [part for part in (tender.tender_number, tender.title.strip()) if part]
    name = " · ".join(parts) or f"Тендер {tender.id}"
    return name[:200]
