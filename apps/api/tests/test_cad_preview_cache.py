"""Превью CAD: кеш готового ответа, ETag, 304 и Cache-Control (завершённое задание неизменяемо).

Трассы строятся настоящим обработчиком cad-worker с заглушкой генератора (как в test_cad_mep),
поэтому движок не нужен.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import cad_preview_cache, cad_views
from app.storage.base import ObjectStorage
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_mep import (
    PARAMS,
    STUB,
    _approve_and_queue,
    _parent,
    _run_route_worker,
    mep_settings,
)


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_mep"
    (root / "params").mkdir(parents=True)
    (root / "cad_mep").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_mep.py").write_text(STUB, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def empty_cache() -> None:
    cad_preview_cache.preview_cache.clear()


def _count_preview_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reads: list[str] = []
    original = cad_views.read_json

    async def counting(storage: ObjectStorage, key: str) -> Any:
        if key.endswith("/preview.json"):
            reads.append(key)
        return await original(storage, key)

    monkeypatch.setattr(cad_views, "read_json", counting)
    return reads


async def test_preview_is_cached_and_served_with_etag(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        reads = _count_preview_reads(monkeypatch)
        url = f"{base}/{route_id}/views/0/1/preview"

        first = await api.get(url)
        assert first.status_code == 200, first.text
        assert first.headers["content-type"] == "application/json"
        assert first.headers["cache-control"] == "private, max-age=300"
        etag = first.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')
        assert len(reads) == 1

        second = await api.get(url)
        assert second.status_code == 200 and second.json() == first.json()
        assert second.headers["etag"] == etag
        assert len(reads) == 1, "повторный запрос обслужен из кеша, без чтения хранилища"

        # Условный запрос: 304 без тела; слабый префикс и список значений тоже подходят.
        for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
            not_modified = await api.get(url, headers={"If-None-Match": header})
            assert not_modified.status_code == 304, header
            assert not_modified.content == b""
            assert not_modified.headers["etag"] == etag
        other = await api.get(url, headers={"If-None-Match": '"stale"'})
        assert other.status_code == 200
        assert len(reads) == 1

        # Кеш не обходит проверку доступа: чужой вид и несуществующее задание — 404.
        assert (await api.get(f"{base}/{uuid.uuid4()}/views/0/1/preview")).status_code == 404
        assert (await api.get(f"{base}/{route_id}/views/0/2/preview")).status_code == 404


async def test_preview_is_rebuilt_identically_after_cache_reset(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        url = f"{base}/{route_id}/views/0/1/preview"
        body = (await api.get(url)).json()
        # Вне кеша ответ собирается заново и совпадает.
        cad_preview_cache.preview_cache.clear()
        assert (await api.get(url)).json() == body
        assert len(cad_preview_cache.preview_cache) == 1


def test_cache_evicts_by_entries_and_size() -> None:
    cache = cad_preview_cache.PreviewCache(max_entries=2, max_total_bytes=10)
    keys = [cad_preview_cache.make_key(uuid.uuid4(), 1, 0, 1, "d", "p") for _ in range(3)]
    cache.put(keys[0], b"aaaa")
    cache.put(keys[1], b"bbbb")
    assert cache.get(keys[0]) == b"aaaa"  # обновляет давность
    cache.put(keys[2], b"cc")
    assert cache.get(keys[1]) is None, "вытеснена давно не использованная"
    assert cache.get(keys[0]) == b"aaaa" and cache.get(keys[2]) == b"cc"
    cache.put(keys[1], b"x" * 11)
    assert cache.get(keys[1]) is None, "запись крупнее предела не кешируется"
    cache.put(keys[1], b"zzzzzz")  # 4 + 2 + 6 > 10 -> вытесняется самая давняя
    assert cache.total_bytes <= 10 and len(cache) <= 2
