"""Управление связью проекта с тендером.

Связь `source` + `external_id` — каноническая: по ней проект узнаётся во внешней системе.
Проверяется, что обычным редактированием её не изменить, что перепривязка требует прав
и подтверждения, оставляет след и не трогает работу, а недоступность TenderHUB не мешает
смотреть уже импортированное.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import AuditAction, DocumentKind, ProcessingStatus, ProjectSource, Role
from app.errors import DomainError
from app.integrations.tenderhub import TenderHubClient
from app.models import AuditEvent, Document, Project
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import tenderhub_binding
from app.storage.keys import revision_key
from tests.conftest import make_context
from tests.test_api_tenderhub import TENDER, settings_with_key

OTHER_TENDER: dict[str, Any] = {
    **TENDER,
    "id": "22222222-2222-4222-8222-222222222222",
    "tender_number": "ТН-0099",
    "title": "ЖК «Южный», корпус 1",
}


def client_for(*tenders: dict[str, Any]) -> TenderHubClient:
    """Клиент, отвечающий только этими тендерами. В сеть не ходит."""
    known = {tender["id"]: tender for tender in tenders}

    def handler(request: httpx.Request) -> httpx.Response:
        for tender_id, payload in known.items():
            if tender_id in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"items": list(known.values())})

    return TenderHubClient(settings_with_key(), transport=httpx.MockTransport(handler))


async def bound_project(session: AsyncSession, workspace_id: uuid.UUID) -> Project:
    project = await projects_service.create_project(
        session,
        workspace_id=workspace_id,
        name="ТН-0042 · ЖК «Северный», корпус 3",
        source=ProjectSource.TENDERHUB,
        external_id=TENDER["id"],
        external_ref=TENDER["tender_number"],
    )
    await session.commit()
    return project


# ------------------------------------------------- каноническая связь неприкосновенна


def test_ordinary_update_cannot_touch_the_binding() -> None:
    """Схема обычного редактирования не принимает полей связи.

    Проверка на уровне контракта, а не поведения: поле, которого нет в схеме, нельзя
    прислать, и добавить его случайно тоже не выйдет — этот тест упадёт.
    """
    from app.schemas import ProjectUpdate

    assert set(ProjectUpdate.model_fields) == {"name", "status"}


async def test_renaming_a_tender_project_keeps_the_canonical_name(
    api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Переименование пишется в местное имя: каноническое принадлежит внешней системе."""
    project = await bound_project(db_session, workspace_id)

    response = await api.patch(
        f"/api/v1/projects/{project.id}", json={"name": "Северный, третий корпус"}
    )
    assert response.status_code == 200

    await db_session.refresh(project)
    assert project.name == "ТН-0042 · ЖК «Северный», корпус 3"
    assert project.local_alias == "Северный, третий корпус"
    assert project.external_id == TENDER["id"]


async def test_renaming_a_manual_project_still_changes_its_name(
    api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """У заведённого руками проекта имя своё — и переименование обычное."""
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="Обычный проект"
    )
    await db_session.commit()

    response = await api.patch(f"/api/v1/projects/{project.id}", json={"name": "Новое имя"})
    assert response.status_code == 200

    await db_session.refresh(project)
    assert project.name == "Новое имя"
    assert project.local_alias is None


# ------------------------------------------------------------ перепривязка и отвязка


async def test_rebind_requires_the_integration_permission(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    project = await bound_project(db_session, workspace_id)
    context = make_context(Role.ENGINEER, workspace_id=workspace_id)

    with pytest.raises(DomainError) as error:
        await tenderhub_binding.rebind(
            db_session,
            context,
            client_for(TENDER, OTHER_TENDER),
            project=project,
            tender_id=OTHER_TENDER["id"],
        )
    assert error.value.code.value == "PERMISSION_DENIED"


async def test_rebind_is_refused_when_the_tender_is_taken(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Один тендер — один проект. Иначе непонятно, какой из них настоящий."""
    project = await bound_project(db_session, workspace_id)
    await projects_service.create_project(
        db_session,
        workspace_id=workspace_id,
        name="Уже занят",
        source=ProjectSource.TENDERHUB,
        external_id=OTHER_TENDER["id"],
        external_ref=OTHER_TENDER["tender_number"],
    )
    await db_session.commit()

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    with pytest.raises(DomainError) as error:
        await tenderhub_binding.rebind(
            db_session,
            context,
            client_for(TENDER, OTHER_TENDER),
            project=project,
            tender_id=OTHER_TENDER["id"],
        )
    assert error.value.code.value == "TENDERHUB_BINDING_CONFLICT"


async def test_preview_reports_the_conflict_before_anything_changes(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    project = await bound_project(db_session, workspace_id)
    occupied = await projects_service.create_project(
        db_session,
        workspace_id=workspace_id,
        name="Занявший проект",
        source=ProjectSource.TENDERHUB,
        external_id=OTHER_TENDER["id"],
    )
    await db_session.commit()

    plan = await tenderhub_binding.preview(
        db_session,
        client_for(TENDER, OTHER_TENDER),
        workspace_id=workspace_id,
        project=project,
        tender_id=OTHER_TENDER["id"],
    )
    assert plan.conflicting_project_id == occupied.id
    assert plan.conflicting_project_name == "Занявший проект"
    # Ничего не изменилось: предпросмотр только смотрит.
    await db_session.refresh(project)
    assert project.external_id == TENDER["id"]


async def test_rebind_is_audited_from_old_to_new(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    project = await bound_project(db_session, workspace_id)
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)

    await tenderhub_binding.rebind(
        db_session,
        context,
        client_for(TENDER, OTHER_TENDER),
        project=project,
        tender_id=OTHER_TENDER["id"],
    )

    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.TENDERHUB_PROJECT_REBOUND.value
            )
        )
    ).scalar_one()
    assert event.before_summary is not None
    assert event.after_summary is not None
    assert event.before_summary["external_id"] == TENDER["id"]
    assert event.after_summary["external_id"] == OTHER_TENDER["id"]
    assert event.resource_id == str(project.id)


async def test_rebind_keeps_the_work(db_session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Перепривязка меняет ссылку, а не данные: документы остаются на месте."""
    project = await bound_project(db_session, workspace_id)
    document = await documents_service.create_document(
        db_session, project=project, display_name="АР.pdf", document_kind=DocumentKind.PDF
    )
    revision_id = uuid.uuid4()
    await documents_service.create_revision(
        db_session,
        document=document,
        revision_id=revision_id,
        source_filename="АР.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256="c" * 64,
        storage_key=revision_key(revision_id, "АР.pdf"),
        processing_status=ProcessingStatus.READY,
        source_metadata={},
    )
    await db_session.commit()

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await tenderhub_binding.rebind(
        db_session,
        context,
        client_for(TENDER, OTHER_TENDER),
        project=project,
        tender_id=OTHER_TENDER["id"],
    )

    remaining = (
        (await db_session.execute(select(Document).where(Document.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 1
    assert remaining[0].id == document.id


async def test_unlink_keeps_the_project_and_its_work(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    project = await bound_project(db_session, workspace_id)
    project.local_alias = "Северный, третий корпус"
    await db_session.commit()

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    updated = await tenderhub_binding.unlink(db_session, context, project=project)

    assert updated.source is ProjectSource.MANUAL
    assert updated.external_id is None
    # Местное имя становится основным: под названием чужого тендера проекту больше не место.
    assert updated.name == "Северный, третий корпус"
    assert updated.local_alias is None


async def test_unlink_refuses_a_manual_project(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="Заведён руками"
    )
    await db_session.commit()

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    with pytest.raises(DomainError) as error:
        await tenderhub_binding.unlink(db_session, context, project=project)
    assert error.value.code.value == "TENDERHUB_BINDING_IMMUTABLE"


# --------------------------------------------------------------- изоляция отказа


async def test_tenderhub_outage_does_not_hide_imported_projects(
    build_api: Callable[..., AsyncClient], db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Недоступность внешней системы не должна мешать смотреть уже импортированное.

    Проект живёт сам по себе с момента создания: связь с TenderHUB нужна была один раз.
    """
    project = await bound_project(db_session, workspace_id)

    async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
        listed = await client.get("/api/v1/projects")
        opened = await client.get(f"/api/v1/projects/{project.id}")
        documents = await client.get(f"/api/v1/projects/{project.id}/documents")

    # Ни один из этих маршрутов во внешнюю систему не ходит — и это проверяется тем,
    # что ключа в окружении теста нет вовсе, а ответы всё равно успешные.
    assert listed.status_code == 200
    assert opened.status_code == 200
    assert documents.status_code == 200
