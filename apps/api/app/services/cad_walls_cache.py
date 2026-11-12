"""Процессный кеш разобранного walls.json (`WallsDocument` + файл как прочитан).

Ключ — ключ объекта хранилища и sha256 файла из итога задания. Ключ объекта содержит id задания и
номер попытки (`revisions/<rev>/cad/<job>/attempt-<n>/...`), повтор — всегда новая попытка, а
sha256 привязывает запись к содержимому: чужое или перезаписанное содержимое под тем же ключом в
кеш не попадёт. Права доступа проверяются до обращения к кешу. Разбор JSON и валидация большого
файла идут в потоке (не на event loop), кеш избавляет от них на повторных запросах листа.

Записи читаются только на чтение: потребители (`compute_sheet`, сборка 3D-вида) модели и словарь не
меняют. Ограничен числом записей и суммарным размером исходных файлов (разобранный объект в памяти
в несколько раз больше файла); вытеснение — давнее по использованию.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final

from app.contracts.cad_constructions import WallsDocument

# Контейнер API — 512 МБ, из них до 200 МБ у кеша превью; разобранный документ в памяти
# в разы больше файла, поэтому лимит по исходным байтам скромный.
MAX_ENTRIES: Final = 16
MAX_TOTAL_FILE_BYTES: Final = 16 * 1024 * 1024

WallsCacheKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class CachedWalls:
    document: WallsDocument
    raw: Any
    file_size: int


class WallsCache:
    def __init__(
        self, *, max_entries: int = MAX_ENTRIES, max_total_file_bytes: int = MAX_TOTAL_FILE_BYTES
    ) -> None:
        self._max_entries = max_entries
        self._max_total = max_total_file_bytes
        self._items: OrderedDict[WallsCacheKey, CachedWalls] = OrderedDict()
        self._total = 0

    def get(self, key: WallsCacheKey) -> CachedWalls | None:
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
        return item

    def put(self, key: WallsCacheKey, item: CachedWalls) -> None:
        if item.file_size > self._max_total:
            return
        previous = self._items.pop(key, None)
        if previous is not None:
            self._total -= previous.file_size
        self._items[key] = item
        self._total += item.file_size
        while self._items and (
            len(self._items) > self._max_entries or self._total > self._max_total
        ):
            _, evicted = self._items.popitem(last=False)
            self._total -= evicted.file_size

    def clear(self) -> None:
        self._items.clear()
        self._total = 0

    def __len__(self) -> int:
        return len(self._items)


walls_cache: Final = WallsCache()
