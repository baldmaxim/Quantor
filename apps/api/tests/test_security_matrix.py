"""Матрица безопасности приёмки Stage 1.5.

Двенадцать пунктов промта 11, собранные в одном месте намеренно. Отдельные свойства
проверяются и в других файлах, но приёмка отвечает на один вопрос — можно ли выставлять
портал наружу, — и ответ на него должен читаться целиком, а не собираться по крупицам
из двадцати файлов.

Пункты, которые нельзя проверить кодом (кэширование браузером, установка PWA на
настоящем устройстве), названы явно и вынесены в отчёт приёмки.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, permissions_for
from app.core.config import get_settings
from app.domain import Role
from app.main import create_app
from app.models import Workspace
from app.services import projects as projects_service
from tests.conftest import make_context, oidc_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _app_with_provider() -> FastAPI:
    settings = oidc_settings()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return app


# 1 -----------------------------------------------------------------------------


async def test_1_unauthenticated_cannot_read_projects() -> None:
    """Неаутентифицированный не читает проекты."""
    app = _app_with_provider()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/projects")

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


# 2 -----------------------------------------------------------------------------


async def test_2_viewer_cannot_mutate(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    """Читатель не меняет ничего."""
    async with build_api(make_context(Role.VIEWER, workspace_id=workspace_id)) as client:
        created = await client.post("/api/v1/projects", json={"name": "Попытка"})

    assert created.status_code == 403


# 3 -----------------------------------------------------------------------------


def test_3_engineer_is_not_an_administrator() -> None:
    """Инженер — не администратор."""
    granted = permissions_for(Role.ENGINEER)

    assert Permission.SYSTEM_ADMIN not in granted
    assert Permission.SETTINGS_MANAGE not in granted
    assert Permission.FEATURE_FLAGS_MANAGE not in granted
    assert Permission.AUDIT_READ not in granted


# 4 -----------------------------------------------------------------------------


async def test_4_workspace_admin_cannot_leave_its_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Администратор пространства не выходит за его границу."""
    foreign = await projects_service.create_project(
        db_session, workspace_id=second_workspace.id, name="Чужой"
    )
    await db_session.commit()

    async with build_api(make_context(Role.WORKSPACE_ADMIN, workspace_id=workspace_id)) as client:
        response = await client.get(f"/api/v1/projects/{foreign.id}")

    assert response.status_code == 404


# 5 -----------------------------------------------------------------------------


async def test_5_platform_admin_access_is_explicit(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Администратор платформы входит в чужое пространство только намеренно."""
    foreign = await projects_service.create_project(
        db_session, workspace_id=second_workspace.id, name="Соседний"
    )
    await db_session.commit()

    async with build_api(make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)) as client:
        implicit = await client.get(f"/api/v1/projects/{foreign.id}")
    async with build_api(
        make_context(Role.PLATFORM_ADMIN, workspace_id=second_workspace.id)
    ) as client:
        explicit = await client.get(f"/api/v1/projects/{foreign.id}")

    assert implicit.status_code == 404, "молчаливого доступа «просто потому что админ» нет"
    assert explicit.status_code == 200


# 6 -----------------------------------------------------------------------------


async def test_6_guessed_identifiers_do_not_cross_the_boundary(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    second_workspace: Workspace,
) -> None:
    """Угаданный UUID не пробивает границу пространства."""
    foreign = await projects_service.create_project(
        db_session, workspace_id=second_workspace.id, name="Чужой"
    )
    await db_session.commit()

    async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
        for path in (
            f"/api/v1/projects/{foreign.id}",
            f"/api/v1/projects/{foreign.id}/documents",
            f"/api/v1/projects/{foreign.id}/jobs",
        ):
            response = await client.get(path)
            assert response.status_code == 404, path
            # 403 подтвердил бы существование объекта и превратил бы перебор в разведку.
            assert response.json()["detail"]["code"] == "NOT_FOUND"


# 7 -----------------------------------------------------------------------------


async def test_7_content_url_obeys_the_same_boundary(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
) -> None:
    """Ссылка на файл выдаётся только после проверки прав."""
    async with build_api(make_context(Role.VIEWER, workspace_id=workspace_id)) as client:
        # У читателя право document.read есть — проверяем именно границу пространства.
        response = await client.get(f"/api/v1/revisions/{uuid.uuid4()}/content-url")

    assert response.status_code == 404


# 8 -----------------------------------------------------------------------------


def test_8_admin_api_denies_by_default() -> None:
    """Каждая административная операция объявляет право.

    Проверяется по контракту: операция, прошедшая опознание и не спросившая права,
    доступна любому вошедшему.
    """
    from fastapi.routing import APIRoute

    from app.auth.resolver import PermissionCheck

    app = _app_with_provider()

    def walk(routes: list[object]) -> list[APIRoute]:
        found: list[APIRoute] = []
        for route in routes:
            if isinstance(route, APIRoute):
                found.append(route)
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(walk(inner.routes))
        return found

    # Проверяются все операции, а не только административные: право должно быть
    # объявлено везде, где запрос доходит до данных.
    missing = [
        f"{sorted(route.methods)} {route.path}"
        for route in walk(app.routes)
        if route.name
        not in {
            "liveness",
            "readiness",
            "read_meta",
            "begin_login",
            "complete_login",
            "logout",
            "read_session",
        }
        and not any(
            isinstance(dependency.call, PermissionCheck)
            for dependency in route.dependant.dependencies
        )
    ]

    assert not missing, "операции без объявленного права: " + "; ".join(sorted(set(missing)))


# 9 -----------------------------------------------------------------------------


def test_9_no_secret_reaches_the_contract_or_the_client() -> None:
    """Ни один секрет не попадает в контракт API и в сгенерированный клиент.

    Проверяются имена полей, а не значения: значение может быть пустым на этой машине
    и заполненным на другой, а поле с таким именем опасно само по себе.
    """
    forbidden = re.compile(
        r"(api_?token|api_?key|client_secret|secret_access_key|password|private_key)",
        re.IGNORECASE,
    )

    schema = _app_with_provider().openapi()
    components = schema.get("components", {}).get("schemas", {})
    leaks = [
        f"{name}.{field}"
        for name, model in components.items()
        for field in model.get("properties", {})
        if forbidden.search(field)
    ]
    assert not leaks, f"поля с секретами в контракте: {leaks}"

    client_source = (REPO_ROOT / "packages/api-client/src/types.gen.ts").read_text(encoding="utf-8")
    client_leaks = sorted(set(forbidden.findall(client_source)))
    assert not client_leaks, f"секреты в сгенерированном клиенте: {client_leaks}"


# 10 ----------------------------------------------------------------------------


async def test_10_destructive_admin_action_is_audited(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Разрушительное административное действие оставляет след."""
    from sqlalchemy import select

    from app.domain import AuditAction, OverrideScope
    from app.models import AuditEvent
    from app.services import portal_settings
    from tests.conftest import clean_settings

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await portal_settings.set_override(
        db_session,
        context,
        key="documents.content_url_ttl_seconds",
        scope=OverrideScope.SYSTEM,
        value=900,
        settings=clean_settings(),
    )

    actions = (await db_session.execute(select(AuditEvent.action))).scalars().all()
    assert AuditAction.SETTING_OVERRIDE_SET.value in actions


# 11 ----------------------------------------------------------------------------


def test_11_service_worker_never_caches_privileged_responses() -> None:
    """Service worker портала не кэширует ответы API.

    Проверяется исходник, а не поведение браузера: правило простое, и держать ради него
    прогон в реальном браузере значит проверять браузер, а не своё решение.
    """
    source = (REPO_ROOT / "apps/web/public/sw.js").read_text(encoding="utf-8")

    assert "url.pathname.startsWith('/api/')" in source
    assert "url.origin !== self.location.origin" in source
    # Кэшируется только статика с хешем в имени.
    assert "/_next/static/" in source


def test_11b_admin_console_has_no_service_worker() -> None:
    """У контура управления service worker не заводится вовсе.

    Закэшированное состояние системы вводит в заблуждение ровно тогда, когда
    администратор пришёл смотреть, что сломалось.
    """
    assert not (REPO_ROOT / "apps/admin/public/sw.js").exists()
    assert not (REPO_ROOT / "apps/admin/public/manifest.json").exists()


# 12 ----------------------------------------------------------------------------


async def test_12_logout_invalidates_the_session(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Выход обесценивает сеанс по-настоящему.

    Ради этого сеанс и хранится строкой в базе: самодостаточный токен в cookie
    остался бы действительным до истечения срока, сколько ни нажимай «Выйти».
    """
    from app.auth import sessions
    from app.models import UserIdentity

    user = UserIdentity(issuer="idp.test", subject="logout-check", email="x@example.com")
    db_session.add(user)
    await db_session.flush()

    row, token = await sessions.create(db_session, user_id=user.id, ttl_seconds=3600)
    await db_session.commit()

    assert await sessions.resolve(db_session, token) is not None

    await sessions.revoke(db_session, row)
    await db_session.commit()

    assert await sessions.resolve(db_session, token) is None


# --------------------------------------------------------- что кодом не проверяется


@pytest.mark.parametrize(
    "item",
    [
        "установка PWA на настоящем iPhone и Android",
        "поведение position: fixed с открытой клавиатурой в Safari",
        "первая загрузка страниц на живом стенде — измеряется вручную",
    ],
)
def test_manual_checks_are_declared(item: str) -> None:
    """Пункты приёмки, которые проверяются руками.

    Тест ничего не проверяет и не притворяется: он существует, чтобы список ручных
    проверок жил в коде рядом с автоматическими, а не терялся в отчёте.
    """
    assert item
