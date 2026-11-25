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

from app.api.v1.deps import SessionDep, TenderHubDep, WorkspaceDep, require
from app.auth.permissions import Permission
from app.domain import ProjectSource
from app.errors import DomainError, ErrorCode
from app.schemas import ProjectRead, TenderBriefRead, TenderImport
from app.services import projects as projects_service
from app.services import tender_imports as tender_imports_service
from app.services.projects import project_name

router = APIRouter(prefix="/integrations/tenderhub", tags=["integrations"])


@router.get(
    "/tenders",
    response_model=list[TenderBriefRead],
    summary="Тендеры, доступные ключу",
    dependencies=[require(Permission.INTEGRATION_READ)],
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
        workspace_id=workspace.tenant,
        source=ProjectSource.TENDERHUB,
        external_ids=[tender.id for tender in tenders],
    )

    # Другая версия того же номера ведёт в уже существующий проект (ADR-0035): строка с
    # собственным проектом — подключённая — в такой подсказке не нуждается.
    by_number = await projects_service.map_external_refs(
        session,
        workspace_id=workspace.tenant,
        source=ProjectSource.TENDERHUB,
        external_refs=[
            tender.tender_number
            for tender in tenders
            if tender.tender_number and tender.id not in linked
        ],
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
            same_number_project_id=(
                None
                if tender.id in linked or not tender.tender_number
                else by_number.get(tender.tender_number)
            ),
        )
        for tender in tenders
    ]


@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект по тендеру",
    dependencies=[require(Permission.PROJECT_CREATE)],
)
async def import_tender(
    payload: TenderImport,
    session: SessionDep,
    workspace: WorkspaceDep,
    client: TenderHubDep,
) -> ProjectRead:
    existing = await projects_service.find_by_external_id(
        session,
        workspace_id=workspace.tenant,
        source=ProjectSource.TENDERHUB,
        external_id=payload.tender_id,
    )
    if existing is not None:
        raise DomainError(ErrorCode.TENDERHUB_ALREADY_LINKED)

    tender = await client.get_tender(payload.tender_id)

    # Та же блокировка, что у пакетного импорта: проверки ниже и создание идут под ней.
    await tender_imports_service.lock_tender(
        session, workspace_id=workspace.tenant, key=tender.tender_number or payload.tender_id
    )
    if await projects_service.find_by_external_id(
        session,
        workspace_id=workspace.tenant,
        source=ProjectSource.TENDERHUB,
        external_id=payload.tender_id,
    ):
        raise DomainError(ErrorCode.TENDERHUB_ALREADY_LINKED)

    # Один номер тендера — один проект (ADR-0035). Другая версия того же номера добавляется
    # версией в существующий проект; интерфейс ведёт туда по `issue.project_id`.
    if tender.tender_number:
        occupied = await projects_service.find_by_external_ref(
            session,
            workspace_id=workspace.tenant,
            source=ProjectSource.TENDERHUB,
            external_ref=tender.tender_number,
        )
        if occupied is not None:
            raise DomainError(
                ErrorCode.TENDERHUB_NUMBER_TAKEN, issue={"project_id": str(occupied.id)}
            )

    project = await projects_service.create_project(
        session,
        workspace_id=workspace.tenant,
        name=payload.name or project_name(tender),
        source=ProjectSource.TENDERHUB,
        external_id=payload.tender_id,
        external_ref=tender.tender_number,
    )
    await session.commit()
    return ProjectRead.model_validate(project)
