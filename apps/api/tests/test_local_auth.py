"""Локальный вход с одобрением администратора (ADR-0031).

Проверяется настоящий путь: регистрация и вход через HTTP, cookie сеанса, разбор контекста
резолвером, подтверждение небезопасного запроса. Контекст подменяется только у клиента
администратора — его права здесь не предмет проверки.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import ApprovalStatus, AuditAction, Role
from app.models import AuditEvent, LocalCredential, UserIdentity, WorkspaceMembership
from app.services import identity as identity_service
from app.services import local_auth
from app.services import users as users_service
from tests.conftest import clean_settings, make_context

PASSWORD = "длинный-пароль-1"
EMAIL = "Engineer@Example.ru"


def _local() -> Settings:
    return clean_settings(auth_mode="local", environment="test")


async def _approved_user(
    session: AsyncSession,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
    role: Role = Role.ENGINEER,
) -> UserIdentity:
    await local_auth.register(session, email=email, display_name="Инженер", password=password)
    user = await identity_service.get_user_by_subject(
        session, issuer=local_auth.LOCAL_ISSUER, subject=local_auth.normalize_email(email)
    )
    assert user is not None
    await users_service.approve(session, user=user, workspace_id=DEV_WORKSPACE_ID, role=role)
    await session.commit()
    return user


async def _login(client: AsyncClient, *, email: str = EMAIL, password: str = PASSWORD) -> int:
    response = await client.post(
        "/api/v1/auth/password-login", json={"email": email, "password": password}
    )
    return response.status_code


def _admin(build_api: Callable[..., AsyncClient]) -> AsyncClient:
    return build_api(
        make_context(Role.PLATFORM_ADMIN, workspace_id=DEV_WORKSPACE_ID, platform_admin=True),
        settings=_local(),
    )


async def _actions(session: AsyncSession) -> list[str]:
    return list((await session.execute(select(AuditEvent.action))).scalars().all())


# ------------------------------------------------------------------ регистрация и допуск


async def test_registration_is_a_request_not_access(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(settings=_local()) as client:
        registered = await client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "display_name": "Инженер", "password": PASSWORD},
        )
        assert registered.status_code == 202
        assert registered.json() == {"status": "pending"}

        refused = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": PASSWORD}
        )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "ACCOUNT_PENDING"

    user = await identity_service.get_user_by_subject(
        db_session, issuer="local", subject="engineer@example.ru"
    )
    assert user is not None
    assert user.approval_status is ApprovalStatus.PENDING
    credential = await db_session.get(LocalCredential, user.id)
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert PASSWORD not in credential.password_hash
    assert AuditAction.USER_REGISTERED.value in await _actions(db_session)


async def test_second_registration_answers_the_same_and_changes_nothing(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    body = {"email": EMAIL, "display_name": "Инженер", "password": PASSWORD}
    async with build_api(settings=_local()) as client:
        first = await client.post("/api/v1/auth/register", json=body)
        second = await client.post(
            "/api/v1/auth/register",
            json={**body, "email": EMAIL.upper(), "password": "другой-пароль-2"},
        )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    rows = (
        (await db_session.execute(select(UserIdentity).where(UserIdentity.issuer == "local")))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_weak_password_is_refused(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(settings=_local()) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "display_name": "Инженер", "password": "short"},
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CREDENTIAL_TOO_WEAK"


# ------------------------------------------------------------------------------- вход


async def test_approved_user_gets_a_working_session_guarded_by_csrf(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        assert await _login(client, email="  engineer@example.RU ") == 200

        session_state = (await client.get("/api/v1/auth/session")).json()
        assert session_state["authenticated"] is True
        assert session_state["auth_mode"] == "local"
        assert session_state["role"] == "engineer"
        assert session_state["workspace_id"] == str(DEV_WORKSPACE_ID)
        assert session_state["must_change_password"] is False

        # Чтение идёт через настоящий резолвер: cookie → сеанс → личность → пространство.
        assert (await client.get("/api/v1/projects")).status_code == 200

        # Небезопасный запрос без подтверждения отвергается.
        denied = await client.post("/api/v1/projects", json={"name": "Объект"})
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "CSRF_FAILED"

        token = client.cookies.get("quantor_csrf")
        assert token
        created = await client.post(
            "/api/v1/projects", json={"name": "Объект"}, headers={"X-CSRF-Token": token}
        )
        assert created.status_code == 201

    user = await identity_service.get_user_by_subject(
        db_session, issuer="local", subject="engineer@example.ru"
    )
    assert user is not None
    assert user.last_login_at is not None
    assert AuditAction.LOGIN_SUCCEEDED.value in await _actions(db_session)


async def test_unknown_email_and_wrong_password_are_the_same_refusal(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        unknown = await client.post(
            "/api/v1/auth/password-login", json={"email": "nobody@example.ru", "password": PASSWORD}
        )
        wrong = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": "неверный-пароль"}
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]
    assert AuditAction.LOGIN_FAILED.value in await _actions(db_session)


async def test_repeated_failures_lock_the_account(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        for _ in range(local_auth.MAX_FAILED_ATTEMPTS):
            assert await _login(client, password="неверный-пароль") == 401
        # Блокировка держит и верный пароль: иначе перебор просто продолжался бы.
        locked = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": PASSWORD}
        )

    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
    credential = await db_session.get(LocalCredential, user.id)
    assert credential is not None
    await db_session.refresh(credential)
    assert credential.locked_until is not None
    assert credential.locked_until > datetime.now(UTC)


async def test_pending_state_is_not_revealed_without_the_password(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(settings=_local()) as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "display_name": "Инженер", "password": PASSWORD},
        )
        response = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": "неверный-пароль"}
        )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "CREDENTIAL_INVALID"


async def test_bearer_token_is_refused_in_local_mode(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(settings=_local()) as client:
        response = await client.get(
            "/api/v1/projects", headers={"Authorization": "Bearer something"}
        )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "CREDENTIAL_INVALID"


async def test_password_routes_are_closed_outside_local_mode(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api() as client:
        response = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": PASSWORD}
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTH_NOT_CONFIGURED"


async def test_login_link_leads_to_the_portal_form(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(settings=_local()) as client:
        inside = await client.get("/api/v1/auth/login", params={"next": "/projects"})
        outside = await client.get("/api/v1/auth/login", params={"next": "//evil.example"})

    assert inside.status_code == 307
    assert inside.headers["location"] == "http://localhost:3000/signed-out?next=/projects"
    assert outside.headers["location"] == "http://localhost:3000/signed-out?next=/"


# ------------------------------------------------------------------ действия администратора


async def test_admin_approves_request_into_a_workspace(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await local_auth.register(db_session, email=EMAIL, display_name="Инженер", password=PASSWORD)
    await db_session.commit()

    async with _admin(build_api) as admin:
        pending = await admin.get("/api/v1/admin/users", params={"status": "pending"})
        assert pending.status_code == 200
        assert pending.json()["total"] == 1
        user_id = pending.json()["items"][0]["id"]

        approved = await admin.post(
            f"/api/v1/admin/users/{user_id}/approve",
            json={"workspace_id": str(DEV_WORKSPACE_ID), "role": "reviewer"},
        )
        assert approved.status_code == 200
        body = approved.json()
        assert body["approval_status"] == "approved"
        assert body["is_local"] is True
        assert [item["role"] for item in body["memberships"]] == ["reviewer"]

        again = await admin.post(
            f"/api/v1/admin/users/{user_id}/approve",
            json={"workspace_id": str(DEV_WORKSPACE_ID), "role": "reviewer"},
        )
        assert again.status_code == 409

        platform_role = await admin.put(
            f"/api/v1/admin/users/{user_id}/membership",
            json={"workspace_id": str(DEV_WORKSPACE_ID), "role": "platform_admin"},
        )
        assert platform_role.status_code == 422

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
    assert AuditAction.USER_APPROVED.value in await _actions(db_session)


async def test_rejected_request_cannot_sign_in(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await local_auth.register(
        db_session, email=EMAIL, display_name="Инженер", password=PASSWORD
    )
    assert user is not None
    await db_session.commit()

    async with _admin(build_api) as admin:
        rejected = await admin.post(f"/api/v1/admin/users/{user.id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["approval_status"] == "rejected"

    async with build_api(settings=_local()) as client:
        response = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": PASSWORD}
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_REJECTED"


async def test_disabling_revokes_live_sessions(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        assert (await client.get("/api/v1/projects")).status_code == 200

        async with _admin(build_api) as admin:
            disabled = await admin.post(f"/api/v1/admin/users/{user.id}/disable")
            assert disabled.status_code == 200
            assert disabled.json()["is_active"] is False

        after = await client.get("/api/v1/projects")
        assert after.status_code == 401
        assert after.json()["detail"]["code"] == "SESSION_EXPIRED"

        refused = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": PASSWORD}
        )
        assert refused.json()["detail"]["code"] == "ACCOUNT_DISABLED"


async def test_admin_cannot_disable_themselves(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await _approved_user(db_session, role=Role.WORKSPACE_ADMIN)
    context = make_context(
        Role.PLATFORM_ADMIN, workspace_id=DEV_WORKSPACE_ID, user_id=user.id, platform_admin=True
    )
    async with build_api(context, settings=_local()) as admin:
        response = await admin.post(f"/api/v1/admin/users/{user.id}/disable")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "USER_SELF_ACTION"


async def test_temporary_password_must_be_changed(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await _approved_user(db_session)
    temporary = "временный-пароль-7"
    changed = "постоянный-пароль-9"

    async with build_api(settings=_local()) as old_browser:
        assert await _login(old_browser) == 200

        async with _admin(build_api) as admin:
            reset = await admin.post(
                f"/api/v1/admin/users/{user.id}/password", json={"password": temporary}
            )
            assert reset.status_code == 200
            assert reset.json()["must_change_password"] is True

        # Выданный пароль заменяет прежний: сеанс, открытый до сброса, погашен.
        assert (await old_browser.get("/api/v1/projects")).status_code == 401

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 401
        login = await client.post(
            "/api/v1/auth/password-login", json={"email": EMAIL, "password": temporary}
        )
        assert login.status_code == 200
        assert login.json() == {"must_change_password": True}
        assert (await client.get("/api/v1/auth/session")).json()["must_change_password"] is True

        body = {"current_password": temporary, "new_password": changed}
        without_csrf = await client.post("/api/v1/auth/change-password", json=body)
        assert without_csrf.status_code == 403

        token = client.cookies.get("quantor_csrf")
        assert token
        wrong_current = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "не-тот-пароль", "new_password": changed},
            headers={"X-CSRF-Token": token},
        )
        assert wrong_current.status_code == 401

        done = await client.post(
            "/api/v1/auth/change-password", json=body, headers={"X-CSRF-Token": token}
        )
        assert done.status_code == 200
        # Сеанс, из которого пароль сменили, продолжает работать.
        state = (await client.get("/api/v1/auth/session")).json()
        assert state["authenticated"] is True
        assert state["must_change_password"] is False

    async with build_api(settings=_local()) as client:
        assert await _login(client, password=changed) == 200
    assert AuditAction.USER_CREDENTIAL_RESET.value in await _actions(db_session)
    assert AuditAction.CREDENTIAL_CHANGED.value in await _actions(db_session)


# ---------------------------------------------------------------------- команда обслуживания


async def test_create_platform_admin_is_also_access_recovery(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    admin = await local_auth.create_platform_admin(
        db_session, email="Owner@Example.ru", password=PASSWORD, display_name="Владелец"
    )
    await db_session.commit()

    assert admin.platform_role is Role.PLATFORM_ADMIN
    assert admin.approval_status is ApprovalStatus.APPROVED
    membership = (
        await db_session.execute(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == admin.id)
        )
    ).scalar_one()
    assert membership.workspace_id == DEV_WORKSPACE_ID
    assert membership.role is Role.WORKSPACE_ADMIN

    # Повторный вызов меняет пароль и возвращает права, а не заводит второго.
    admin.platform_role = None
    await db_session.commit()
    again = await local_auth.create_platform_admin(
        db_session, email="owner@example.ru", password="новый-пароль-42", display_name=None
    )
    await db_session.commit()
    assert again.id == admin.id
    assert again.platform_role is Role.PLATFORM_ADMIN

    async with build_api(settings=_local()) as client:
        assert await _login(client, email="owner@example.ru", password=PASSWORD) == 401
        assert await _login(client, email="owner@example.ru", password="новый-пароль-42") == 200
        state = (await client.get("/api/v1/auth/session")).json()
    assert state["user"]["is_platform_admin"] is True


async def test_admin_list_never_carries_the_hash(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _admin(build_api) as admin:
        response = await admin.get("/api/v1/admin/users")
    assert response.status_code == 200
    assert "argon2" not in response.text
    assert all(item["id"] != str(uuid.UUID(int=0)) for item in response.json()["items"])


async def test_platform_admin_with_membership_keeps_platform_rights(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Администратор платформы с членством видит и портал, и админку.

    Прежде резолвер отдавал ему роль членства, а `/auth/session` — платформенную: интерфейс
    показывал админку, а API отвечал на неё отказом `system.admin`.
    """
    await local_auth.create_platform_admin(
        db_session, email="owner@example.ru", password=PASSWORD, display_name="Владелец"
    )
    await db_session.commit()

    async with build_api(settings=_local()) as client:
        assert await _login(client, email="owner@example.ru") == 200
        admin_area = await client.get("/api/v1/admin/users")
        portal = await client.get("/api/v1/projects")

    assert admin_area.status_code == 200
    assert portal.status_code == 200
