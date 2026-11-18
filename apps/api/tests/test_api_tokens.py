"""Персональные API-токены `qtk_…` (ADR-0051): выпуск, вход по токену, область, отзыв, срок.

Проверяется настоящий путь: вход по паролю в сеансе, выпуск токена, запросы с заголовком
`Authorization: Bearer` через резолвер. Контекст не подменяется ни в одном из этих тестов.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, permissions_for
from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import AuditAction, Role
from app.models import ApiToken, AuditEvent, UserIdentity, Workspace
from app.services import projects as projects_service
from app.services.api_tokens import permissions_for_scopes
from tests.conftest import clean_settings
from tests.test_local_auth import EMAIL, PASSWORD, _approved_user, _login
from tests.test_tender_exchange import _project_with_release, _url, build_package

TOKENS = "/api/v1/me/api-tokens"


def _settings(*, flag: bool = True) -> Settings:
    return clean_settings(
        auth_mode="local",
        environment="test",
        feature_flags="tender.exchange=true" if flag else "",
    )


@asynccontextmanager
async def _session_client(
    build_api: Callable[..., AsyncClient], *, flag: bool = True
) -> AsyncIterator[AsyncClient]:
    """Клиент с сеансом: вход по паролю, cookie и CSRF-токен хранит сам клиент."""
    async with build_api(settings=_settings(flag=flag)) as client:
        assert await _login(client) == 200
        yield client


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("quantor_csrf")
    assert token
    return {"X-CSRF-Token": token}


async def _issue(
    client: AsyncClient, name: str = "TENDER на ноутбуке", **extra: object
) -> dict[str, object]:
    created = await client.post(TOKENS, json={"name": name, **extra}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    body: dict[str, object] = created.json()
    return body


def _bearer(build_api: Callable[..., AsyncClient], token: object) -> AsyncClient:
    client = build_api(settings=_settings())
    client.headers["Authorization"] = f"Bearer {token}"
    return client


async def test_token_is_shown_once_and_stored_as_hash(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        created = await _issue(client, expires_in_days=30)
        token = str(created["token"])
        assert token.startswith("qtk_") and len(token) == 44
        assert created["prefix"] == token[:12]
        assert created["scopes"] == ["tender"]
        assert created["active"] is True and created["expires_at"] is not None

        listed = (await client.get(TOKENS)).json()
        assert [row["id"] for row in listed] == [created["id"]]
        assert "token" not in listed[0]

    row = (await db_session.execute(select(ApiToken))).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {row.token_hash, row.prefix, row.name}
    audit = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.API_ACCESS_CREATED.value)
        )
    ).scalar_one()
    assert token not in str(audit.after_summary)
    assert audit.after_summary is not None and audit.after_summary["prefix"] == token[:12]


async def test_bearer_token_signs_in_under_local_auth_mode(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]

    async with _bearer(build_api, token) as bearer:
        assert (await bearer.get("/api/v1/projects")).status_code == 200

    async with _bearer(build_api, "qtk_" + "x" * 40) as unknown:
        refused = await unknown.get("/api/v1/projects")
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "CREDENTIAL_INVALID"


async def test_token_rights_are_narrowed_to_the_tender_scope(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Инженер создаёт проекты, а токен инженера - нет: права роли ∩ область токена."""
    await _approved_user(db_session, role=Role.ENGINEER)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]
        assert (
            await client.post("/api/v1/projects", json={"name": "Сеанс"}, headers=_csrf(client))
        ).status_code == 201

    async with _bearer(build_api, token) as bearer:
        denied = await bearer.post("/api/v1/projects", json={"name": "Токен"})
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"
        # Читать проекты область токена разрешает.
        assert (await bearer.get("/api/v1/projects")).status_code == 200


async def test_token_cannot_issue_or_revoke_tokens(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        created = await _issue(client)
    async with _bearer(build_api, created["token"]) as bearer:
        for method, url in (
            ("GET", TOKENS),
            ("POST", TOKENS),
            ("DELETE", f"{TOKENS}/{created['id']}"),
        ):
            response = await bearer.request(method, url, json={"name": "новый"})
            assert response.status_code == 403, (method, response.text)
            assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
    row = (await db_session.execute(select(ApiToken))).scalar_one()
    assert row.revoked_at is None


async def test_revoked_token_stops_working_immediately(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        created = await _issue(client)
        async with _bearer(build_api, created["token"]) as bearer:
            assert (await bearer.get("/api/v1/projects")).status_code == 200

            assert (
                await client.delete(f"{TOKENS}/{created['id']}", headers=_csrf(client))
            ).status_code == 204
            refused = await bearer.get("/api/v1/projects")
            assert refused.status_code == 401
            assert refused.json()["detail"]["code"] == "CREDENTIAL_INVALID"

        listed = (await client.get(TOKENS)).json()
        assert listed[0]["active"] is False and listed[0]["revoked_at"] is not None
        # Повторный отзыв ничего не ломает и не плодит записей журнала.
        again = await client.delete(f"{TOKENS}/{created['id']}", headers=_csrf(client))
        assert again.status_code == 204
    revoked_events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.API_ACCESS_REVOKED.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(revoked_events) == 1


async def test_expired_token_is_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        created = await _issue(client, expires_in_days=1)
    async with _bearer(build_api, created["token"]) as bearer:
        assert (await bearer.get("/api/v1/projects")).status_code == 200
        await db_session.execute(
            update(ApiToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db_session.commit()
        refused = await bearer.get("/api/v1/projects")
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "CREDENTIAL_INVALID"


async def test_token_is_bound_to_its_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]
    async with _bearer(build_api, token) as bearer:
        same = await bearer.get(
            "/api/v1/projects", headers={"X-Workspace-Id": str(DEV_WORKSPACE_ID)}
        )
        assert same.status_code == 200
        other = await bearer.get(
            "/api/v1/projects", headers={"X-Workspace-Id": str(second_workspace.id)}
        )
        assert other.status_code == 403
        assert other.json()["detail"]["code"] == "WORKSPACE_FORBIDDEN"


async def test_last_used_is_touched_at_most_once_a_minute(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]
    async with _bearer(build_api, token) as bearer:
        assert (await bearer.get("/api/v1/projects")).status_code == 200
        first = (await db_session.execute(select(ApiToken.last_used_at))).scalar_one()
        assert first is not None
        assert (await bearer.get("/api/v1/projects")).status_code == 200
        assert (await db_session.execute(select(ApiToken.last_used_at))).scalar_one() == first
        await db_session.execute(
            update(ApiToken).values(last_used_at=datetime.now(UTC) - timedelta(minutes=2))
        )
        await db_session.commit()
        assert (await bearer.get("/api/v1/projects")).status_code == 200
    renewed = (await db_session.execute(select(ApiToken.last_used_at))).scalar_one()
    assert renewed is not None and renewed > datetime.now(UTC) - timedelta(minutes=1)


async def test_disabled_owner_loses_the_token(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    user = await _approved_user(db_session)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]
    await db_session.execute(
        update(UserIdentity).where(UserIdentity.id == user.id).values(is_active=False)
    )
    await db_session.commit()
    async with _bearer(build_api, token) as bearer:
        assert (await bearer.get("/api/v1/projects")).status_code == 401


async def test_foreign_token_cannot_be_revoked_and_name_is_validated(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        assert (
            await client.delete(f"{TOKENS}/{uuid.uuid4()}", headers=_csrf(client))
        ).status_code == 404
        for bad in ({"name": ""}, {"name": "x" * 101}, {"name": "ok", "expires_in_days": 0}):
            response = await client.post(TOKENS, json=bad, headers=_csrf(client))
            assert response.status_code == 422, bad
        assert (
            await client.post(
                TOKENS, json={"name": "ok", "expires_in_days": 366}, headers=_csrf(client)
            )
        ).status_code == 422


async def test_token_endpoints_are_closed_by_the_exchange_flag(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api, flag=False) as client:
        for response in (
            await client.get(TOKENS),
            await client.post(TOKENS, json={"name": "x"}, headers=_csrf(client)),
        ):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_email_constant_is_the_login_one() -> None:
    """Страховка от дрейфа общих констант тестов локального входа."""
    assert EMAIL and PASSWORD


async def test_engineer_token_uploads_a_calc_but_cannot_release_a_base(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Путь навыка TENDER: токен инженера загружает и читает расчёты, но не выпускает базу."""
    await _approved_user(db_session, role=Role.ENGINEER)
    project, release = await _project_with_release(db_session)
    async with _session_client(build_api) as client:
        token = (await _issue(client))["token"]

    data = build_package(project, release)
    async with _bearer(build_api, token) as bearer:
        uploaded = await bearer.post(
            _url(project.id, "calcs/upload"),
            files={"file": ("calc.zip", data, "application/zip")},
        )
        assert uploaded.status_code == 201, uploaded.text
        assert (await bearer.get(_url(project.id, "calcs"))).status_code == 200
        assert (await bearer.get(_url(project.id, "base/releases"))).status_code == 200
        released = await bearer.post(_url(project.id, "base/releases"), json={})
        assert released.status_code == 403
        withdrawn = await bearer.post(
            _url(project.id, f"calc-versions/{uploaded.json()['id']}/withdraw")
        )
        assert withdrawn.status_code == 403
    author = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.TENDER_CALC_UPLOADED.value)
        )
    ).scalar_one()
    assert author.credential == "api_token"


async def test_scopes_union_within_the_owner_role() -> None:
    """Области складываются, но не выходят за роль владельца и не дают создавать проекты."""
    read = permissions_for_scopes(Role.ENGINEER, ["read"])
    assert {Permission.DOCUMENT_READ, Permission.JOBS_READ, Permission.TENDER_CALC_READ} <= read
    assert Permission.DOCUMENT_UPLOAD not in read and Permission.TENDER_CALC_UPLOAD not in read
    upload = permissions_for_scopes(Role.ENGINEER, ["upload"])
    assert Permission.DOCUMENT_UPLOAD in upload and Permission.TENDER_CALC_UPLOAD not in upload
    read_tender = permissions_for_scopes(Role.ENGINEER, ["read", "tender"])
    assert Permission.TENDER_CALC_UPLOAD in read_tender
    assert permissions_for_scopes(Role.ENGINEER, ["admin"]) == frozenset()
    everything = permissions_for_scopes(Role.ENGINEER, ["read", "tender", "upload"])
    assert everything <= permissions_for(Role.ENGINEER)
    assert Permission.PROJECT_CREATE not in everything
    assert Permission.TENDER_BASE_RELEASE not in everything


async def test_token_scopes_are_stored_in_order_and_unknown_is_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with _session_client(build_api) as client:
        created = await _issue(client, scopes=["upload", "read", "read"])
        assert created["scopes"] == ["read", "upload"]
        bad = await client.post(
            TOKENS, json={"name": "x", "scopes": ["admin"]}, headers=_csrf(client)
        )
        assert bad.status_code == 422


async def test_read_token_reads_but_cannot_upload_and_sees_the_agent_openapi(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Токен агента «только чтение»: проекты и описание API - да, загрузка - нет."""
    await _approved_user(db_session, role=Role.ENGINEER)
    project = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Агент"
    )
    async with _session_client(build_api) as client:
        token = (await _issue(client, scopes=["read"]))["token"]

    async with _bearer(build_api, token) as bearer:
        assert (await bearer.get("/api/v1/projects")).status_code == 200
        spec = await bearer.get("/api/v1/meta/openapi.json")
        assert spec.status_code == 200
        coordination = "/api/v1/projects/{project_id}/tender/base/coordination.{fmt}"
        assert coordination in spec.json()["paths"]
        upload = await bearer.post(
            f"/api/v1/projects/{project.id}/uploads",
            files={"file": ("a.ifc", b"ISO-10303-21;", "application/octet-stream")},
        )
        assert upload.status_code == 403
        missing = await bearer.get(_url(project.id, "base/coordination.ifc"))
        assert missing.status_code == 404

    async with build_api(settings=_settings()) as anonymous:
        assert (await anonymous.get("/api/v1/meta/openapi.json")).status_code == 401
