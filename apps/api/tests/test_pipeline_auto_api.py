"""GET /projects/{id}/pipeline-auto: включён ли автопайплайн для проекта (S0-B)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from tests.conftest import (
    DEV_WORKSPACE_ID,
    FakeObjectStorage,
    _build_api,
    clean_settings,
    make_context,
)


async def _project(session: AsyncSession) -> Project:
    project = Project(workspace_id=DEV_WORKSPACE_ID, name=f"Авто {uuid.uuid4().hex[:6]}")
    session.add(project)
    await session.commit()
    return project


async def _client(
    session: AsyncSession, storage: FakeObjectStorage, raw: str
) -> AsyncIterator[AsyncClient]:
    settings = clean_settings(environment="test", pipeline_auto=raw)
    app, client = _build_api(session, storage, context=make_context(), settings=settings)
    try:
        async with client as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def pilot_api(
    db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> AsyncIterator[tuple[AsyncClient, Project, Project]]:
    pilot = await _project(db_session)
    other = await _project(db_session)
    raw = json.dumps({"project_ids": [str(pilot.id)]})
    async for client in _client(db_session, fake_storage, raw):
        yield client, pilot, other


async def test_enabled_only_for_pilot_project(
    pilot_api: tuple[AsyncClient, Project, Project],
) -> None:
    client, pilot, other = pilot_api

    on = await client.get(f"/api/v1/projects/{pilot.id}/pipeline-auto")
    off = await client.get(f"/api/v1/projects/{other.id}/pipeline-auto")

    assert on.status_code == 200
    assert on.json() == {"enabled": True}
    assert off.json() == {"enabled": False}


async def test_disabled_when_setting_empty(
    db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project = await _project(db_session)
    async for client in _client(db_session, fake_storage, ""):
        response = await client.get(f"/api/v1/projects/{project.id}/pipeline-auto")
        assert response.json() == {"enabled": False}


async def test_unknown_project_is_404(
    pilot_api: tuple[AsyncClient, Project, Project],
) -> None:
    client, _, _ = pilot_api

    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/pipeline-auto")

    assert response.status_code == 404
