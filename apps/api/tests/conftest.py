"""Общие фикстуры.

Тесты делятся на две группы. Тесты оболочки и чистой логики работают всегда. Тесты базы
данных требуют запущенного PostgreSQL и пропускаются, если его нет, — чтобы прогон на машине
без поднятой инфраструктуры не превращался в стену красных ошибок. В CI база поднимается,
и эти тесты выполняются по-настоящему.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.auth.context import AuthContext, CredentialKind, Principal
from app.auth.dev import DEV_USER_ID
from app.auth.permissions import permissions_for
from app.auth.resolver import get_auth_context
from app.core.config import Settings, get_settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.db.base import Base
from app.db.session import get_session
from app.domain import Role, UserKind
from app.main import create_app
from app.models import UserIdentity, Workspace
from app.services.job_runner import get_job_scheduler
from app.storage import get_object_storage
from app.storage.base import ObjectNotFoundError, ObjectStat, StoredObject

# Одна проверка доступности на прогон: незачем ждать таймаут подключения в каждом тесте.
_database_state: dict[str, bool] = {}


def _test_database_url() -> tuple[str, str, str]:
    """Возвращает (URL тестовой базы, URL служебной базы, имя тестовой базы)."""
    settings = get_settings()
    name = f"{settings.postgres_db}_test"
    password = settings.postgres_password.get_secret_value()
    prefix = (
        f"postgresql+asyncpg://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
    )
    return f"{prefix}/{name}", f"{prefix}/postgres", name


async def _ensure_database() -> bool:
    """Создаёт тестовую базу, если сервер доступен. Возвращает False, если сервера нет."""
    target_url, maintenance_url, name = _test_database_url()
    engine = create_async_engine(maintenance_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("select 1 from pg_database where datname = :name"), {"name": name}
            )
            if not exists:
                await connection.execute(text(f'create database "{name}"'))
    except Exception:
        return False
    finally:
        await engine.dispose()

    engine = create_async_engine(target_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    except Exception:
        return False
    finally:
        await engine.dispose()
    return True


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    if "available" not in _database_state:
        _database_state["available"] = await _ensure_database()
    if not _database_state["available"]:
        pytest.skip("PostgreSQL недоступен — поднимите инфраструктуру: pnpm infra:up")

    target_url, _, _ = _test_database_url()
    engine = create_async_engine(target_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия теста. После теста таблицы очищаются, чтобы тесты не влияли друг на друга."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        await _seed_identity(session)
        try:
            yield session
        finally:
            await session.rollback()

    tables = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    async with db_engine.begin() as connection:
        await connection.execute(text(f"truncate table {tables} restart identity cascade"))


async def _seed_identity(session: AsyncSession) -> None:
    """Пространство по умолчанию и dev-личность.

    Сеется в каждом тесте, а не один раз: `truncate` после теста уносит и это тоже.
    Без строки пространства не вставится ни один проект — с миграции 0003 на
    `projects.workspace_id` стоит внешний ключ, а тестовая база собирается из метаданных,
    минуя миграции, и посева оттуда не получает.
    """
    session.add(
        Workspace(id=DEV_WORKSPACE_ID, slug="default", name="Рабочее пространство по умолчанию")
    )
    session.add(
        UserIdentity(
            id=DEV_USER_ID,
            issuer="dev",
            subject="dev",
            email="dev@localhost",
            display_name="Разработчик",
            platform_role=Role.PLATFORM_ADMIN,
        )
    )
    await session.commit()


@pytest.fixture
async def workspace_id(db_session: AsyncSession) -> uuid.UUID:
    """Пространство по умолчанию. Строка уже создана посевом сессии."""
    return DEV_WORKSPACE_ID


@pytest.fixture
async def second_workspace(db_session: AsyncSession) -> Workspace:
    """Чужое пространство. Нужно проверкам границы: без второго арендатора её не видно."""
    workspace = Workspace(slug="second", name="Соседнее пространство")
    db_session.add(workspace)
    await db_session.commit()
    return workspace


@pytest.fixture
async def other_user(db_session: AsyncSession) -> UserIdentity:
    """Обычный пользователь без прав платформы."""
    user = UserIdentity(issuer="idp.test", subject="user-2", email="user2@example.com")
    db_session.add(user)
    await db_session.commit()
    return user


class FakeObjectStorage:
    """Хранилище в памяти.

    Реализует тот же протокол, что и S3: тесты API не должны требовать поднятого MinIO,
    а контракт при этом проверяется настоящий.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.deleted: list[str] = []

    @property
    def bucket(self) -> str:
        return "test-bucket"

    async def check_available(self) -> None:
        return None

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        import hashlib

        digest = hashlib.sha256()
        buffer = bytearray()
        async for chunk in chunks:
            digest.update(chunk)
            buffer.extend(chunk)
        return await self._store(
            key, bytes(buffer), digest.hexdigest(), content_type, original_filename, metadata
        )

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        import hashlib

        return await self._store(
            key,
            data,
            hashlib.sha256(data).hexdigest(),
            content_type,
            original_filename,
            metadata,
        )

    async def _store(
        self,
        key: str,
        data: bytes,
        sha256: str,
        content_type: str,
        original_filename: str | None,
        metadata: Mapping[str, str] | None,
    ) -> StoredObject:
        self.objects[key] = data
        self.metadata[key] = {
            "content-type": content_type,
            **({"original-filename": original_filename} if original_filename else {}),
            **dict(metadata or {}),
        }
        return StoredObject(key=key, size=len(data), sha256=sha256)

    async def iter_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        data = self.objects[key]
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]

    async def stat(self, key: str) -> ObjectStat:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return ObjectStat(
            key=key,
            size=len(self.objects[key]),
            content_type=self.metadata[key].get("content-type"),
            last_modified=datetime.now(UTC),
            metadata=self.metadata[key],
        )

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.metadata.pop(key, None)
        self.deleted.append(key)

    async def presigned_get_url(
        self, key: str, *, expires_in: int, download_filename: str | None = None
    ) -> str:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return f"https://storage.test/{self.bucket}/{key}?expires={expires_in}"


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Клиент без базы — для проверок оболочки."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


def make_context(
    role: Role = Role.PLATFORM_ADMIN,
    *,
    workspace_id: uuid.UUID | None = DEV_WORKSPACE_ID,
    user_id: uuid.UUID = DEV_USER_ID,
    platform_admin: bool | None = None,
) -> AuthContext:
    """Контекст доступа для проверок.

    Собирается тем же способом, что и в бою: права выводятся из роли, а не перечисляются
    руками. Иначе тест проверял бы выдуманный набор, а не действующий.

    `workspace_id=None` — администратор платформы без членства: контекста арендатора нет.
    """
    is_platform = role is Role.PLATFORM_ADMIN if platform_admin is None else platform_admin
    principal = Principal(
        user_id=user_id,
        issuer="idp.test",
        subject=str(user_id),
        email="user@example.com",
        display_name="Проверяющий",
        kind=UserKind.HUMAN,
        platform_role=Role.PLATFORM_ADMIN if is_platform else None,
    )
    return AuthContext(
        principal=principal,
        workspace_id=workspace_id,
        role=role,
        permissions=permissions_for(role),
        credential=CredentialKind.SESSION,
        is_dev_mode=False,
    )


def oidc_settings() -> Settings:
    """Настройки с включённым провайдером: только так виден отказ без учётных данных.

    В dev-режиме контекст выдаётся всем, и проверка «без сеанса — 401» показывала бы 200.
    """
    return Settings(  # type: ignore[call-arg]
        auth_mode="oidc",
        oidc_issuer="https://idp.test",
        oidc_client_id="quantor",
    )


def clean_settings(**overrides: object) -> Settings:
    """Настройки без влияния окружения разработчика.

    `Settings()` читает `.env`, и проверка контура управления начинает зависеть от того,
    что у конкретного человека лежит в файле. Один такой случай уже был: заданный
    `TENDERHUB_API_TOKEN` ломал проверку «интеграцию нельзя включить без ключа», причём
    только на машине, где ключ настроен, — то есть у того, кто с интеграцией и работает.

    Здесь обнуляется всё, чем управляет контур: ключ интеграции, переопределения флагов
    и настроек. Проверка порядка старшинства обязана видеть ровно то, что положила сама.
    """
    values: dict[str, object] = {
        "tenderhub_api_token": SecretStr(""),
        "feature_flags": "",
        "settings_overrides": "",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[call-arg]


def _build_api(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    *,
    context: AuthContext | None,
    settings: Settings | None = None,
) -> tuple[Any, AsyncClient]:
    app = create_app(settings) if settings is not None else create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    def override_storage() -> Any:
        return fake_storage

    # Фоновый импорт в тестах не запускается: задания выполняются явно, чтобы проверять
    # результат, а не гоняться за асинхронной задачей.
    scheduled: list[uuid.UUID] = []

    def override_scheduler() -> Any:
        return scheduled.append

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = override_storage
    app.dependency_overrides[get_job_scheduler] = override_scheduler
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    if context is not None:
        # Подменяется ровно одна зависимость: всё остальное — `require`, `WorkspaceDep`,
        # запрет по умолчанию — построено на ней и подхватывает подмену само.
        app.dependency_overrides[get_auth_context] = lambda: context

    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def api(
    db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> AsyncIterator[AsyncClient]:
    """Клиент API с настоящей базой и хранилищем в памяти.

    Контекст — администратор платформы в пространстве по умолчанию: проверки этого клиента
    занимаются предметной логикой, а не правами, и не должны переписываться из-за них.
    """
    app, client = _build_api(db_session, fake_storage, context=make_context())
    try:
        async with client as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def build_api(
    db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> Iterator[Callable[..., AsyncClient]]:
    """Фабрика клиентов для проверок доступа.

    Без контекста клиент проходит настоящий путь опознания при включённом провайдере —
    так и проверяется отказ без учётных данных.
    """
    apps: list[Any] = []

    def _make(context: AuthContext | None = None, *, with_provider: bool = False) -> AsyncClient:
        settings = oidc_settings() if (with_provider or context is None) else None
        app, client = _build_api(db_session, fake_storage, context=context, settings=settings)
        apps.append(app)
        return client

    try:
        yield _make
    finally:
        for app in apps:
            app.dependency_overrides.clear()
