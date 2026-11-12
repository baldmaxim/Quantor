"""Кеш разобранного walls.json: границы, ключ с sha256, повторный запрос без чтения хранилища."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import WallsDocument
from app.services import cad_views
from app.services.cad_walls_cache import CachedWalls, WallsCache, walls_cache
from app.storage.base import ObjectStorage
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_constructions_api import _ready_sheet, _url, walls_settings, walls_tools

__all__ = ["walls_tools"]


def _item(size: int = 10) -> CachedWalls:
    document = WallsDocument.model_construct()
    return CachedWalls(document, {}, size)


def test_cache_evicts_least_recently_used_by_count() -> None:
    cache = WallsCache(max_entries=2, max_total_file_bytes=1000)
    cache.put(("a", "1"), _item())
    cache.put(("b", "1"), _item())
    assert cache.get(("a", "1")) is not None
    cache.put(("c", "1"), _item())
    assert cache.get(("b", "1")) is None
    assert cache.get(("a", "1")) is not None and cache.get(("c", "1")) is not None
    assert len(cache) == 2


def test_cache_evicts_by_total_file_size_and_skips_oversized() -> None:
    cache = WallsCache(max_entries=10, max_total_file_bytes=100)
    cache.put(("a", "1"), _item(60))
    cache.put(("b", "1"), _item(60))
    assert cache.get(("a", "1")) is None and cache.get(("b", "1")) is not None
    cache.put(("big", "1"), _item(101))
    assert cache.get(("big", "1")) is None
    assert cache.get(("b", "1")) is not None


def test_same_key_with_other_sha_is_a_different_entry() -> None:
    cache = WallsCache()
    cache.put(("a", "1"), _item())
    assert cache.get(("a", "2")) is None


async def test_repeated_constructions_request_does_not_read_storage(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    walls_cache.clear()
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls_id = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        reads: list[str] = []
        original = cad_views.read_json

        async def counting(storage: ObjectStorage, key: str) -> Any:
            if key.endswith("/walls.json"):
                reads.append(key)
            return await original(storage, key)

        monkeypatch.setattr(cad_views, "read_json", counting)
        url = _url(project_id, job_id, "constructions")
        first = await api.get(url)
        assert first.status_code == 200, first.text
        assert len(reads) == 1
        second = await api.get(url)
        assert second.status_code == 200 and second.json() == first.json()
        assert len(reads) == 1, "повторный запрос обслужен из кеша, без чтения хранилища"
    walls_cache.clear()
