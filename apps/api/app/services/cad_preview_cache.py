"""Процессный кеш готовых ответов превью CAD.

Превью завершённой попытки неизменяемо (DXF и preview.json привязаны хешем), а его выдача
дорога: чтение JSON из хранилища, проверка каждого пути, повторная сериализация. Кеш хранит
уже готовые байты ответа по неизменяемому ключу; права доступа проверяются до обращения к нему.
Ограничен и числом записей, и суммарным размером; вытеснение — давнее по использованию.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import OrderedDict
from typing import Final

MAX_ENTRIES: Final = 16
MAX_TOTAL_BYTES: Final = 200 * 1024 * 1024

PreviewKey = tuple[uuid.UUID, int, int, int, str, str]


def make_key(
    job_id: uuid.UUID,
    attempt: int,
    page_index: int,
    view: int,
    dxf_sha256: str,
    preview_sha256: str,
) -> PreviewKey:
    return (job_id, attempt, page_index, view, dxf_sha256, preview_sha256)


def etag_of(key: PreviewKey) -> str:
    """Сильный ETag из неизменяемого ключа: тело по тому же ключу не меняется."""
    digest = hashlib.sha256("|".join(str(part) for part in key).encode()).hexdigest()
    return f'"{digest[:32]}"'


def etag_matches(header: str | None, etag: str) -> bool:
    """`If-None-Match`: список значений, `*`, слабый префикс `W/`."""
    if not header:
        return False
    for raw in header.split(","):
        candidate = raw.strip()
        if candidate == "*" or candidate.removeprefix("W/") == etag:
            return True
    return False


class PreviewCache:
    def __init__(
        self, *, max_entries: int = MAX_ENTRIES, max_total_bytes: int = MAX_TOTAL_BYTES
    ) -> None:
        self._max_entries = max_entries
        self._max_total_bytes = max_total_bytes
        self._items: OrderedDict[PreviewKey, bytes] = OrderedDict()
        self._total = 0

    def get(self, key: PreviewKey) -> bytes | None:
        body = self._items.get(key)
        if body is not None:
            self._items.move_to_end(key)
        return body

    def put(self, key: PreviewKey, body: bytes) -> None:
        if len(body) > self._max_total_bytes:
            return
        previous = self._items.pop(key, None)
        if previous is not None:
            self._total -= len(previous)
        self._items[key] = body
        self._total += len(body)
        while self._items and (
            len(self._items) > self._max_entries or self._total > self._max_total_bytes
        ):
            _, evicted = self._items.popitem(last=False)
            self._total -= len(evicted)

    def clear(self) -> None:
        self._items.clear()
        self._total = 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def total_bytes(self) -> int:
        return self._total


preview_cache: Final = PreviewCache()
