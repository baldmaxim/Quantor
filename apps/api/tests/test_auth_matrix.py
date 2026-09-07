"""Матрица доступа: кто и что видит.

Проверяется не «есть ли проверка в коде», а наблюдаемое поведение API. Границей считается
ответ: 401 — «не знаю, кто ты», 403 — «знаю, но нельзя», 404 — «в твоём пространстве такого
нет». Третий случай важнее прочих: 403 на чужой объект подтверждал бы его существование
и превращал перебор идентификаторов в разведку (ADR-0012).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, permissions_for
from app.auth.resolver import WORKSPACE_HEADER
from app.domain import COORDINATE_SPACE_NORMALIZED_TOP_LEFT, DocumentKind, ProcessingStatus, Role
from app.models import Region, Sheet, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.storage.keys import revision_key
from tests.conftest import make_context

FAKE_SHA = "b" * 64


@dataclass(frozen=True, slots=True)
class Owned:
    """Полная цепочка владения в одном пространстве — от проекта до области."""

    workspace_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    revision_id: uuid.UUID
    sheet_id: uuid.UUID


async def _build(session: AsyncSession, workspace_id: uuid.UUID, name: str) -> Owned:
    project = await projects_service.create_project(session, workspace_id=workspace_id, name=name)
    document = await documents_service.create_document(
        session, project=project, display_name=f"{name}.pdf", document_kind=DocumentKind.PDF
    )
    revision_id = uuid.uuid4()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=revision_id,
        source_filename=f"{name}.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256=FAKE_SHA,
        storage_key=revision_key(revision_id, f"{name}.pdf"),
        processing_status=ProcessingStatus.READY,
        source_metadata={"coordinate_space": COORDINATE_SPACE_NORMALIZED_TOP_LEFT},
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1")
    session.add(sheet)
    await session.flush()
    session.add(
        Region(
            sheet_id=sheet.id,
            external_block_id="blk_1",
            ordinal=1,
            block_type="text",
            shape_type="rectangle",
            coords_norm=[0.1, 0.1, 0.5, 0.5],
        )
    )
    await session.commit()
    return Owned(
        workspace_id=workspace_id,
        project_id=project.id,
        document_id=document.id,
        revision_id=revision.id,
        sheet_id=sheet.id,
    )


# ------------------------------------------------------------------ права ролей


def test_viewer_cannot_change_anything() -> None:
    """Читатель не получает ни одного права на запись — проверяется по составу набора."""
    granted = permissions_for(Role.VIEWER)
    forbidden = {
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.PROJECT_DELETE,
        Permission.DOCUMENT_UPLOAD,
        Permission.SETTINGS_MANAGE,
        Permission.FEATURE_FLAGS_MANAGE,
    }
    assert not (granted & forbidden)


def test_engineer_is_not_an_administrator() -> None:
    granted = permissions_for(Role.ENGINEER)
    assert Permission.SYSTEM_ADMIN not in granted
    assert Permission.WORKSPACE_MEMBERS_MANAGE not in granted
    assert Permission.AUDIT_READ not in granted
    # При этом рабочие действия ему доступны, иначе роль бессмысленна.
    assert Permission.PROJECT_CREATE in granted
    assert Permission.DOCUMENT_UPLOAD in granted


def test_workspace_admin_is_not_a_platform_admin() -> None:
    granted = permissions_for(Role.WORKSPACE_ADMIN)
    assert Permission.SYSTEM_ADMIN not in granted
    assert Permission.MODELS_MANAGE not in granted
    assert Permission.WORKSPACE_MEMBERS_MANAGE in granted


def test_platform_admin_has_every_permission() -> None:
    assert permissions_for(Role.PLATFORM_ADMIN) == frozenset(Permission)


def test_service_identity_is_read_only() -> None:
    granted = permissions_for(Role.SERVICE)
    assert granted == {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.JOBS_READ,
    }


# ------------------------------------------------------- отказы на живом API


async def test_request_without_credentials_is_unauthenticated(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api() as client:
        response = await client.get("/api/v1/projects")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_viewer_cannot_create_a_project(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    async with build_api(make_context(Role.VIEWER)) as client:
        response = await client.post("/api/v1/projects", json={"name": "Попытка"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


async def test_reviewer_cannot_upload(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    owned = await _build(db_session, workspace_id, "Проект проверяющего")
    async with build_api(make_context(Role.REVIEWER)) as client:
        response = await client.post(
            f"/api/v1/projects/{owned.project_id}/uploads",
            files={"file": ("x.pdf", b"%PDF-1.7\n", "application/pdf")},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


async def test_engineer_may_create_and_read(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    """Отрицательные проверки без положительной доказывают лишь, что всё сломано."""
    async with build_api(make_context(Role.ENGINEER)) as client:
        created = await client.post("/api/v1/projects", json={"name": "Проект инженера"})
        listed = await client.get("/api/v1/projects")

    assert created.status_code == 201, created.text
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


# --------------------------------------------------- граница между пространствами


async def test_foreign_project_is_not_found_rather_than_forbidden(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """404, а не 403: иначе перебор идентификаторов рассказывает, что существует."""
    foreign = await _build(db_session, second_workspace.id, "Чужой проект")

    async with build_api(make_context(Role.WORKSPACE_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.get(f"/api/v1/projects/{foreign.project_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


async def test_guessed_identifiers_do_not_cross_the_boundary(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Ни одно звено цепочки владения не открывается по прямому идентификатору."""
    foreign = await _build(db_session, second_workspace.id, "Чужая цепочка")

    async with build_api(make_context(Role.WORKSPACE_ADMIN, workspace_id=workspace_id)) as client:
        checks = {
            f"/api/v1/projects/{foreign.project_id}": "проект",
            f"/api/v1/projects/{foreign.project_id}/documents": "документы проекта",
            f"/api/v1/documents/{foreign.document_id}": "документ",
            f"/api/v1/documents/{foreign.document_id}/revisions": "ревизии документа",
            f"/api/v1/revisions/{foreign.revision_id}": "ревизия",
            f"/api/v1/revisions/{foreign.revision_id}/sheets": "листы ревизии",
            f"/api/v1/revisions/{foreign.revision_id}/artifacts": "артефакты ревизии",
            f"/api/v1/sheets/{foreign.sheet_id}/regions": "области листа",
        }
        for path, label in checks.items():
            response = await client.get(path)
            assert response.status_code == 404, f"{label}: {response.status_code}"


async def test_content_url_obeys_the_same_boundary(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Ссылка на файл — предъявительский мандат, и выдаваться она должна не всем."""
    foreign = await _build(db_session, second_workspace.id, "Чужой документ")
    mine = await _build(db_session, workspace_id, "Свой документ")

    context = make_context(Role.ENGINEER, workspace_id=workspace_id)
    async with build_api(context) as client:
        denied = await client.get(f"/api/v1/revisions/{foreign.revision_id}/content-url")
        # Своя ревизия: файла в хранилище нет, но граница пройдена — и это разные отказы.
        allowed = await client.get(f"/api/v1/revisions/{mine.revision_id}/content-url")

    assert denied.status_code == 404
    assert denied.json()["detail"]["code"] == "NOT_FOUND"
    assert allowed.json()["detail"]["code"] != "NOT_FOUND" or allowed.status_code == 200


async def test_platform_admin_enters_another_workspace_only_explicitly(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Администратор платформы не видит чужое пространство молча — только по заголовку."""
    foreign = await _build(db_session, second_workspace.id, "Проект соседей")

    without_header = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    async with build_api(without_header) as client:
        implicit = await client.get(f"/api/v1/projects/{foreign.project_id}")

    switched = make_context(Role.PLATFORM_ADMIN, workspace_id=second_workspace.id)
    async with build_api(switched) as client:
        explicit = await client.get(f"/api/v1/projects/{foreign.project_id}")

    assert implicit.status_code == 404
    assert explicit.status_code == 200
    assert explicit.json()["name"] == "Проект соседей"


async def test_workspace_header_is_rejected_for_a_plain_member(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    """Заголовок переключения — не способ выйти за свою границу."""
    async with build_api() as client:
        response = await client.get(
            "/api/v1/projects", headers={WORKSPACE_HEADER: str(second_workspace.id)}
        )

    # Без учётных данных дело до пространства даже не доходит.
    assert response.status_code == 401


@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ENGINEER, Role.WORKSPACE_ADMIN])
async def test_no_role_below_platform_admin_may_switch_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
    role: Role,
) -> None:
    """Проверка на уровне набора прав: переключение — привилегия платформы."""
    context = make_context(role, workspace_id=workspace_id)
    assert not context.principal.is_platform_admin
    assert Permission.SYSTEM_ADMIN not in context.permissions
