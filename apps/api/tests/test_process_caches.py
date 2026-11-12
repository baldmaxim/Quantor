"""Внутрипроцессные кэши: переопределения флагов (15 с) и разбор сеанса (5 с).

Время подменяется через `time.monotonic`: ждать TTL по-настоящему в тестах незачем.
Базовые проверки TTL и сброса не требуют базы; счёт запросов идёт по настоящему PostgreSQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import DBAPICursor, ExecutionContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import cache as auth_cache
from app.auth.context import Principal
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import OverrideScope, Role, UserKind
from app.services import feature_flags as flags_service
from app.services import users as users_service
from tests.conftest import clean_settings, make_context
from tests.test_local_auth import _approved_user, _local, _login

PILOT = "takeoff.manual"


class FakeClock:
    """Управляемые монотонные часы."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    # Подменяется `time` только в модулях кэшей: глобальная подмена `time.monotonic` остановила
    # бы таймеры цикла событий.
    stub = SimpleNamespace(monotonic=fake)
    monkeypatch.setattr(auth_cache, "time", stub)
    monkeypatch.setattr(flags_service, "time", stub)
    return fake


@pytest.fixture
def statements(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Тексты SQL, выполненные на движке теста."""
    captured: list[str] = []

    def record(
        connection: Connection,
        cursor: DBAPICursor,
        statement: str,
        parameters: object,
        context: ExecutionContext | None,
        executemany: bool,
    ) -> None:
        captured.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)


def _count(statements: list[str], table: str) -> int:
    return sum(1 for text in statements if "SELECT" in text and f"FROM {table}" in text)


def _principal() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        issuer="idp.test",
        subject="cache",
        email="cache@example.com",
        display_name=None,
        kind=UserKind.HUMAN,
        platform_role=None,
    )


# ---------------------------------------------------------------- кэш разбора сеанса


def _put(key: str = "h1", *, expires_in: timedelta = timedelta(hours=1)) -> None:
    auth_cache.put_auth_entry(
        key,
        principal=_principal(),
        session_id=uuid.uuid4(),
        session_expires_at=datetime.now(UTC) + expires_in,
    )


def test_auth_entry_lives_until_ttl(clock: FakeClock) -> None:
    _put()
    assert auth_cache.get_auth_entry("h1") is not None

    clock.now += auth_cache.AUTH_CACHE_TTL_SECONDS - 0.1
    assert auth_cache.get_auth_entry("h1") is not None

    clock.now += 0.2
    assert auth_cache.get_auth_entry("h1") is None


def test_expired_session_is_never_served_from_cache(clock: FakeClock) -> None:
    _put(expires_in=timedelta(seconds=-1))
    assert auth_cache.get_auth_entry("h1") is None


def test_auth_invalidation_by_key_and_all(clock: FakeClock) -> None:
    _put("a")
    _put("b")

    auth_cache.invalidate_auth_cache("a")
    assert auth_cache.get_auth_entry("a") is None
    assert auth_cache.get_auth_entry("b") is not None

    _put("a")
    auth_cache.invalidate_auth_cache()
    assert auth_cache.get_auth_entry("a") is None
    assert auth_cache.get_auth_entry("b") is None


def test_memberships_do_not_extend_entry_lifetime(clock: FakeClock) -> None:
    _put()
    clock.now += auth_cache.AUTH_CACHE_TTL_SECONDS - 1
    auth_cache.set_cached_memberships("h1", ())
    entry = auth_cache.get_auth_entry("h1")
    assert entry is not None
    assert entry.memberships == ()

    clock.now += 1.1
    assert auth_cache.get_auth_entry("h1") is None


# ---------------------------------------------------------------- кэш флагов


async def test_flag_overrides_are_cached_until_ttl(
    db_session: AsyncSession, statements: list[str], clock: FakeClock
) -> None:
    context = flags_service.EvaluationContext(workspace_id=DEV_WORKSPACE_ID)
    settings = clean_settings()

    await flags_service.evaluate_all(db_session, settings, context)
    await flags_service.evaluate_all(db_session, settings, context)
    assert _count(statements, "feature_flag_overrides") == 1

    clock.now += flags_service.FLAG_CACHE_TTL_SECONDS + 0.1
    await flags_service.evaluate_all(db_session, settings, context)
    assert _count(statements, "feature_flag_overrides") == 2


async def test_flag_cache_is_keyed_by_workspace(
    db_session: AsyncSession, statements: list[str], clock: FakeClock
) -> None:
    settings = clean_settings()
    await flags_service.evaluate_all(
        db_session, settings, flags_service.EvaluationContext(workspace_id=DEV_WORKSPACE_ID)
    )
    await flags_service.evaluate_all(db_session, settings, flags_service.EvaluationContext())
    assert _count(statements, "feature_flag_overrides") == 2


async def test_flag_write_resets_cache_at_once(db_session: AsyncSession, clock: FakeClock) -> None:
    settings = clean_settings()
    context = flags_service.EvaluationContext(workspace_id=DEV_WORKSPACE_ID)

    before = await flags_service.evaluate_all(db_session, settings, context)
    assert before[PILOT].value is False

    admin = make_context(Role.PLATFORM_ADMIN, workspace_id=DEV_WORKSPACE_ID)
    await flags_service.set_override(
        db_session,
        admin,
        key=PILOT,
        scope=OverrideScope.SYSTEM,
        enabled=True,
        reason="тест",
        settings=settings,
    )
    assert (await flags_service.evaluate_all(db_session, settings, context))[PILOT].value is True

    await flags_service.delete_override(
        db_session, admin, key=PILOT, scope=OverrideScope.SYSTEM, settings=settings
    )
    assert (await flags_service.evaluate_all(db_session, settings, context))[PILOT].value is False


async def test_database_failure_is_not_cached(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise OperationalError("select", {}, Exception("база недоступна"))

    settings = clean_settings()
    context = flags_service.EvaluationContext(workspace_id=DEV_WORKSPACE_ID)
    with monkeypatch.context() as patched:
        patched.setattr(db_session, "execute", broken)
        fallback = await flags_service.evaluate_all(db_session, settings, context)
    assert fallback[PILOT].value is False

    # Сбой не закрепился: после восстановления базы читается настоящее значение.
    admin = make_context(Role.PLATFORM_ADMIN, workspace_id=DEV_WORKSPACE_ID)
    await flags_service.set_override(
        db_session,
        admin,
        key=PILOT,
        scope=OverrideScope.SYSTEM,
        enabled=True,
        reason=None,
        settings=settings,
    )
    assert (await flags_service.evaluate_all(db_session, settings, context))[PILOT].value is True


# ---------------------------------------------------------------- через HTTP


async def test_consecutive_requests_skip_session_selects(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    statements: list[str],
    clock: FakeClock,
) -> None:
    await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        statements.clear()

        assert (await client.get("/api/v1/projects")).status_code == 200
        first = _count(statements, "auth_sessions")
        assert (await client.get("/api/v1/projects")).status_code == 200
        total = _count(statements, "auth_sessions")

        # Первый запрос разбирает сеанс, второй берёт его из кэша.
        assert first == 1
        assert total == first
        memberships_total = _count(statements, "workspace_memberships")
        assert memberships_total == 1

        # По истечении TTL разбор идёт заново.
        clock.now += auth_cache.AUTH_CACHE_TTL_SECONDS + 0.1
        assert (await client.get("/api/v1/projects")).status_code == 200
        assert _count(statements, "auth_sessions") == first + 1


async def test_logout_invalidates_cached_session(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], clock: FakeClock
) -> None:
    await _approved_user(db_session)

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        assert (await client.get("/api/v1/projects")).status_code == 200

        token = client.cookies.get("quantor_csrf")
        # Cookie сеанса сохраняем: после выхода предъявляем тот же токен.
        session_cookie = client.cookies.get("quantor_session")
        assert token and session_cookie
        out = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
        assert out.status_code == 200

        client.cookies.set("quantor_session", session_cookie)
        after = await client.get("/api/v1/projects")
        assert after.status_code == 401


async def test_role_change_is_seen_without_waiting_for_ttl(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], clock: FakeClock
) -> None:
    user = await _approved_user(db_session, role=Role.VIEWER)

    async with build_api(settings=_local()) as client:
        assert await _login(client) == 200
        csrf = client.cookies.get("quantor_csrf")
        assert csrf
        headers = {"X-CSRF-Token": csrf}

        # Наблюдатель создавать проекты не может; ответ прогревает кэш сеанса и членств.
        denied = await client.post("/api/v1/projects", json={"name": "Объект"}, headers=headers)
        assert denied.status_code == 403

        await users_service.upsert_membership(
            db_session, user_id=user.id, workspace_id=DEV_WORKSPACE_ID, role=Role.ENGINEER
        )
        await db_session.commit()

        created = await client.post("/api/v1/projects", json={"name": "Объект"}, headers=headers)
        assert created.status_code == 201
