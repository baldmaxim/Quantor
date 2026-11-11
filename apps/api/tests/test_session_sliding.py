"""Скользящий срок сеанса: простой гасит сеанс, активность продлевает, 30 суток — предел."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message, Receive, Scope, Send

from app.auth import sessions
from app.auth.session_cookie import STATE_KEY, SessionCookieMiddleware, SessionCookieRefresh
from app.models import AuthSession, UserIdentity
from tests.conftest import clean_settings
from tests.test_local_auth import _approved_user, _local, _login

IDLE = 12 * 3600
MAX_LIFETIME = 30 * 24 * 3600


async def _transient_row(
    db_session: AsyncSession, *, created: datetime, last_seen: datetime | None
) -> AuthSession:
    return AuthSession(
        user_id=(await _make_user(db_session)).id,
        token_hash="x" * 64,
        created_at=created,
        last_seen_at=last_seen,
        expires_at=created + timedelta(seconds=IDLE),
    )


async def _make_user(db_session: AsyncSession) -> UserIdentity:
    user = UserIdentity(issuer="idp.test", subject="sliding", email="s@example.com")
    db_session.add(user)
    await db_session.flush()
    return user


async def _the_session(db_session: AsyncSession) -> AuthSession:
    return (
        await db_session.execute(select(AuthSession).execution_options(populate_existing=True))
    ).scalar_one()


async def _shift(db_session: AsyncSession, **values: datetime) -> None:
    await db_session.execute(update(AuthSession).values(**values))
    await db_session.commit()


def _cookies(response: Response, name: str) -> list[str]:
    return [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


def _max_age(header: str) -> int:
    found = re.search(r"Max-Age=(\d+)", header)
    assert found is not None
    return int(found.group(1))


# ------------------------------------------------------------------ sessions.touch


async def test_touch_inside_interval_changes_nothing(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    row = await _transient_row(db_session, created=now - timedelta(hours=1), last_seen=now)
    before = (row.last_seen_at, row.expires_at)

    touched = await sessions.touch(
        db_session, row, idle_ttl_seconds=IDLE, max_lifetime_seconds=MAX_LIFETIME
    )

    assert touched is False
    assert (row.last_seen_at, row.expires_at) == before


async def test_touch_extends_by_idle_ttl(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    row = await _transient_row(
        db_session, created=now - timedelta(hours=10), last_seen=now - timedelta(minutes=10)
    )

    touched = await sessions.touch(
        db_session, row, idle_ttl_seconds=IDLE, max_lifetime_seconds=MAX_LIFETIME
    )

    assert touched is True
    assert row.last_seen_at is not None and row.last_seen_at >= now
    assert abs((row.expires_at - (datetime.now(UTC) + timedelta(seconds=IDLE))).total_seconds()) < 5


async def test_touch_is_capped_by_max_lifetime(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    created = now - timedelta(seconds=MAX_LIFETIME - 3600)
    row = await _transient_row(db_session, created=created, last_seen=now - timedelta(minutes=10))

    assert await sessions.touch(
        db_session, row, idle_ttl_seconds=IDLE, max_lifetime_seconds=MAX_LIFETIME
    )

    assert row.expires_at == created + timedelta(seconds=MAX_LIFETIME)


async def test_create_is_capped_by_max_lifetime(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    row, _ = await sessions.create(
        db_session, user_id=user.id, ttl_seconds=IDLE, max_lifetime_seconds=600
    )
    assert abs((row.expires_at - (datetime.now(UTC) + timedelta(seconds=600))).total_seconds()) < 5


# ------------------------------------------------------------------ через HTTP


async def test_stale_activity_renews_row_and_cookies(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        now = datetime.now(UTC)
        await _shift(
            db_session,
            last_seen_at=now - timedelta(minutes=10),
            expires_at=now + timedelta(hours=1),
        )

        response = await client.get("/api/v1/projects")

        assert response.status_code == 200
        session_cookie = _cookies(response, "quantor_session")
        csrf_cookie = _cookies(response, "quantor_csrf")
        assert len(session_cookie) == 1 and len(csrf_cookie) == 1
        assert abs(_max_age(session_cookie[0]) - IDLE) <= 5
        assert abs(_max_age(csrf_cookie[0]) - IDLE) <= 5
        assert "HttpOnly" in session_cookie[0] and "HttpOnly" not in csrf_cookie[0]

        row = await _the_session(db_session)
        assert row.last_seen_at is not None and row.last_seen_at > now - timedelta(minutes=1)
        assert abs((row.expires_at - (now + timedelta(seconds=IDLE))).total_seconds()) < 10


async def test_activity_inside_interval_sets_no_cookie(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200

        response = await client.get("/api/v1/projects")

        assert response.status_code == 200
        assert response.headers.get_list("set-cookie") == []


async def test_logout_clears_cookies_and_middleware_keeps_them_cleared(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        now = datetime.now(UTC)
        await _shift(db_session, last_seen_at=now - timedelta(minutes=10))
        token = client.cookies.get("quantor_csrf")

        response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token or ""})

        assert response.status_code == 200
        for name in ("quantor_session", "quantor_csrf"):
            headers = _cookies(response, name)
            assert len(headers) == 1
            assert _max_age(headers[0]) == 0


async def test_idle_expired_session_is_rejected(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session)
    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        now = datetime.now(UTC)
        await _shift(
            db_session,
            last_seen_at=now - timedelta(hours=13),
            expires_at=now - timedelta(minutes=1),
        )

        response = await client.get("/api/v1/projects")

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
        assert response.headers.get_list("set-cookie") == []


# ------------------------------------------------------------------ middleware отдельно


async def _run_middleware(*, own_cookie: bool) -> list[tuple[bytes, bytes]]:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        scope["state"][STATE_KEY] = SessionCookieRefresh(token="tok", max_age=100)
        headers: list[tuple[bytes, bytes]] = []
        if own_cookie:
            headers.append((b"set-cookie", b"quantor_session=; Max-Age=0; Path=/"))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope: Scope = {
        "type": "http",
        "headers": [(b"cookie", b"quantor_csrf=abc")],
    }
    middleware = SessionCookieMiddleware(app, settings=clean_settings(environment="test"))
    await middleware(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return list(start["headers"])


async def test_middleware_does_not_override_own_session_cookie() -> None:
    headers = await _run_middleware(own_cookie=True)
    assert headers == [(b"set-cookie", b"quantor_session=; Max-Age=0; Path=/")]


async def test_middleware_adds_both_cookies_with_csrf_from_request() -> None:
    headers = [value.decode() for key, value in await _run_middleware(own_cookie=False)]
    assert any(h.startswith("quantor_session=tok") and "Max-Age=100" in h for h in headers)
    assert any(h.startswith("quantor_csrf=abc") and "Max-Age=100" in h for h in headers)
