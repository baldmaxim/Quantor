"""Общий вид здания для 3D: кеш этажей листов (повторное открытие не читает walls.json заново)."""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_building3d import CadBuilding3dRead
from app.contracts.cad_constructions import CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_building3d as b3d
from app.services.cad_constructions import ProjectSlab
from tests.conftest import FakeObjectStorage
from tests.test_cad_floor3d import NO_LEVELS, raw_document, raw_extras

WALLS_KEY = "walls/k1.json"


class CountingStorage(FakeObjectStorage):
    """Хранилище в памяти, считающее чтения по ключам."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    async def iter_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        self.reads.append(key)
        async for chunk in super().iter_stream(key, chunk_size=chunk_size):
            yield chunk


def _sheet(*, overrides: CadSheetLevelsRead = NO_LEVELS) -> b3d.SheetRef:
    return b3d.SheetRef(
        job_id=uuid.UUID(int=1),
        revision_id=uuid.UUID(int=2),
        document_id=uuid.UUID(int=3),
        page_index=0,
        view=1,
        label="АР · лист 1",
        order=(0.0, 0.0, 0, 1),
        overrides=overrides,
        walls_key=WALLS_KEY,
    )


def _walls_bytes() -> bytes:
    return json.dumps({**raw_extras(), **raw_document()}).encode()


@pytest.fixture(autouse=True)
def empty_cache() -> Iterator[None]:
    b3d.floor_cache.clear()
    yield
    b3d.floor_cache.clear()


def _serve(monkeypatch: pytest.MonkeyPatch, sheets: list[b3d.SheetRef]) -> None:
    async def collect(
        _session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[list[b3d.SheetRef], list[object], ProjectSlab | None]:
        return list(sheets), [], None

    monkeypatch.setattr(b3d, "collect_sheets", collect)


async def _build(storage: CountingStorage) -> CadBuilding3dRead:
    return await b3d.build_building3d(
        cast(AsyncSession, object()),
        storage,
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        include_walls=True,
    )


async def test_second_open_takes_floors_from_cache_without_reading_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = CountingStorage()
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    _serve(monkeypatch, [_sheet()])
    first = await _build(storage)
    assert storage.reads == [WALLS_KEY]
    second = await _build(storage)
    assert storage.reads == [WALLS_KEY]
    assert second.model_dump() == first.model_dump()
    (floor,) = second.floors
    assert floor.walls is not None and len(floor.walls) == 2


async def test_cached_floor_is_the_same_as_built_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = CountingStorage()
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    _serve(monkeypatch, [_sheet()])
    await _build(storage)
    (cached,) = (await _build(storage)).floors
    raw = json.loads(_walls_bytes())
    direct, _warnings = b3d.build_floor(
        _sheet(),
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(raw),
        None,
        include_walls=True,
    )
    assert cached.walls == direct.walls
    assert (cached.outline, cached.base_z_mm) == (direct.outline, direct.base_z_mm)


async def test_changed_sheet_levels_rebuild_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = CountingStorage()
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    _serve(monkeypatch, [_sheet()])
    (before,) = (await _build(storage)).floors
    levels = NO_LEVELS.model_copy(update={"slab_thickness_mm": 260})
    _serve(monkeypatch, [_sheet(overrides=levels)])
    (after,) = (await _build(storage)).floors
    assert storage.reads == [WALLS_KEY, WALLS_KEY]
    assert after.slab_thickness_mm == 260 and before.slab_thickness_mm != 260


async def test_unreadable_walls_file_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = CountingStorage()
    _serve(monkeypatch, [_sheet()])
    missing = await _build(storage)
    assert missing.floors == []
    assert [w.code for w in missing.warnings] == ["walls_unreadable"]
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    (floor,) = (await _build(storage)).floors
    assert floor.walls is not None


async def test_cache_drops_floors_of_older_requests_over_the_points_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = CountingStorage()
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    first, second = _sheet(), dataclasses.replace(_sheet(), page_index=1)
    _serve(monkeypatch, [first])
    await _build(storage)
    # Предел - ровно один этаж: второй запрос вытесняет этаж первого.
    (entry,) = b3d.floor_cache._items.values()
    monkeypatch.setattr(b3d, "FLOOR_CACHE_MAX_POINTS", entry[0].cost)
    _serve(monkeypatch, [second])
    await _build(storage)
    _serve(monkeypatch, [first])
    await _build(storage)
    assert storage.reads == [WALLS_KEY, WALLS_KEY, WALLS_KEY]


async def test_object_bigger_than_cache_keeps_part_of_its_floors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = CountingStorage()
    await storage.put_bytes(WALLS_KEY, _walls_bytes(), content_type="application/json")
    sheets = [dataclasses.replace(_sheet(), page_index=i) for i in range(3)]
    _serve(monkeypatch, sheets[:1])
    await _build(storage)
    (entry,) = b3d.floor_cache._items.values()
    b3d.floor_cache.clear()
    storage.reads.clear()
    # Влезают два этажа из трёх: повторное открытие читает только третий, а не все три по кругу.
    monkeypatch.setattr(b3d, "FLOOR_CACHE_MAX_POINTS", entry[0].cost * 2)
    _serve(monkeypatch, sheets)
    await _build(storage)
    assert len(storage.reads) == 3
    await _build(storage)
    assert len(storage.reads) == 4
