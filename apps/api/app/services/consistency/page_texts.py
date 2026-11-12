"""Текст страниц PDF ревизии (В1): файл, запись, выгрузка в хранилище, потоковое чтение.

Формат `consistency.page_text.v1` - JSON Lines внутри gzip (по строке на запись, поэтому
и пишется, и читается потоково, без разбора всего документа в память):

    {"format": "consistency.page_text.v1", "parser": "<PARSER_VERSION>"}     первая строка
    {"page_index": 0, "label": "1" | null, "text": "..."}                    по строке на страницу
    {"end": true, "pages": N}                                                  последняя строка

Строка `end` - признак целостности: файл без неё (подпроцесс убит на середине) не принимается.
Символ NUL из текста вычищен при записи. Бинарный объект живёт только в хранилище (ADR-0002),
в базе - ключ, счётчики и SHA-256 (таблица `revision_page_texts`).

Читатель ограничен по распакованному размеру: файл из хранилища не считается доверенным
настолько, чтобы раскрывать его без предела (защита от zip-бомбы).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import uuid
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Final

from app.storage.base import ObjectStorage

PAGE_TEXT_FORMAT: Final = "consistency.page_text.v1"
REASON_STORE_FAILED: Final = "PageTextStoreFailed"

_CONTENT_TYPE: Final = "application/gzip"
_UPLOAD_CHUNK: Final = 1024 * 1024
_READ_CHUNK: Final = 64 * 1024


class PageTextError(Exception):
    """Файл текста страниц повреждён, неполон или превышает предел распакованного размера."""


@dataclass(frozen=True, slots=True)
class PageText:
    page_index: int
    label: str | None
    text: str


@dataclass(frozen=True, slots=True)
class PageTextScan:
    """Итог проверки готового файла: число страниц и страниц без текста."""

    pages: int
    empty_pages: int


@dataclass(frozen=True, slots=True)
class StoredPageText:
    """Выгруженный в хранилище файл: то, что пишется в `revision_page_texts`."""

    storage_key: str
    format: str
    parser_version: str
    pages: int
    empty_pages: int
    size_bytes: int
    sha256: str


def page_text_key(project_id: uuid.UUID, revision_id: uuid.UUID) -> str:
    """Ключ объекта; один на ревизию, повторный разбор перезаписывает его."""
    return f"consistency/page-text/{project_id}/{revision_id}/v1.jsonl.gz"


def _no_nul(value: str) -> str:
    return value.replace("\x00", "")


def _dump(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- запись


class PageTextWriter:
    """Потоковая запись файла текста страниц; без выхода через `with` итоговой строки нет."""

    def __init__(self, path: Path, parser_version: str) -> None:
        self._path = path
        self._parser_version = parser_version
        self._raw: BinaryIO | None = None
        self._file: gzip.GzipFile | None = None
        self._pages = 0

    def __enter__(self) -> PageTextWriter:
        self._raw = self._path.open("wb")
        self._file = gzip.GzipFile(filename="", mode="wb", fileobj=self._raw, mtime=0)
        self._file.write(_dump({"format": PAGE_TEXT_FORMAT, "parser": self._parser_version}))
        return self

    def add(self, page_index: int, label: str | None, text: str) -> None:
        if self._file is None:
            raise RuntimeError("файл текста страниц не открыт")
        record = {
            "page_index": page_index,
            "label": None if label is None else _no_nul(label),
            "text": _no_nul(text),
        }
        self._file.write(_dump(record))
        self._pages += 1

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        file = self._file
        if file is None:
            return
        self._file = None
        try:
            if exc_type is None:
                file.write(_dump({"end": True, "pages": self._pages}))
        finally:
            # GzipFile не закрывает чужой fileobj: закрываем оба.
            file.close()
            if self._raw is not None:
                self._raw.close()
                self._raw = None


# --------------------------------------------------------------------------- разбор строк


def _decode_line(raw: bytes) -> dict[str, Any]:
    try:
        record = json.loads(raw)
    except ValueError:
        raise PageTextError("строка текста страниц не JSON") from None
    if not isinstance(record, dict):
        raise PageTextError("строка текста страниц не объект")
    return record


def _check_header(raw: bytes) -> None:
    header = _decode_line(raw)
    if header.get("format") != PAGE_TEXT_FORMAT:
        raise PageTextError("неизвестный формат текста страниц")


def _page_from(record: dict[str, Any]) -> PageText:
    index, label, text = record.get("page_index"), record.get("label"), record.get("text")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not isinstance(text, str)
        or not (label is None or isinstance(label, str))
    ):
        raise PageTextError("запись страницы текста повреждена")
    return PageText(page_index=index, label=label, text=text)


class _LineState:
    """Разбор потока строк: заголовок, страницы, итоговая строка."""

    def __init__(self) -> None:
        self.header_seen = False
        self.footer: dict[str, Any] | None = None
        self.pages = 0
        self.empty_pages = 0

    def feed(self, raw: bytes) -> PageText | None:
        if not raw.strip():
            return None
        if self.footer is not None:
            raise PageTextError("данные после итоговой строки")
        if not self.header_seen:
            _check_header(raw)
            self.header_seen = True
            return None
        record = _decode_line(raw)
        if record.get("end") is True:
            self.footer = record
            return None
        page = _page_from(record)
        self.pages += 1
        if not page.text.strip():
            self.empty_pages += 1
        return page

    def finish(self) -> PageTextScan:
        if not self.header_seen or self.footer is None:
            raise PageTextError("файл текста страниц неполон")
        if self.footer.get("pages") != self.pages:
            raise PageTextError("число страниц не совпадает с итоговой строкой")
        return PageTextScan(pages=self.pages, empty_pages=self.empty_pages)


def scan_page_text_file(path: Path, *, max_bytes: int) -> PageTextScan:
    """Проверяет готовый файл одним проходом; память - одна строка. Синхронная."""
    state = _LineState()
    total = 0
    try:
        with gzip.open(path, "rb") as stream:
            while True:
                # Строка без перевода строки не должна выйти за остаток предела.
                line = stream.readline(max_bytes - total + 1)
                if not line:
                    break
                total += len(line)
                if total > max_bytes:
                    raise PageTextError("распакованный текст страниц больше предела")
                state.feed(line)
    except (OSError, EOFError, zlib.error) as error:
        raise PageTextError("файл текста страниц не gzip") from error
    return state.finish()


# --------------------------------------------------------------------------- хранилище


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_UPLOAD_CHUNK), b""):
            yield chunk


async def store_page_text_file(
    storage: ObjectStorage,
    *,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    path: Path,
    parser_version: str,
    max_bytes: int,
) -> StoredPageText:
    """Проверяет файл и потоково кладёт его в хранилище под ключом ревизии.

    Ошибки - `PageTextError` (файл негоден) или исключения хранилища; вызывающий решает,
    что с ними делать.
    """
    scan = await asyncio.to_thread(scan_page_text_file, path, max_bytes=max_bytes)
    key = page_text_key(project_id, revision_id)
    stored = await storage.put_stream(
        key,
        _file_chunks(path),
        content_type=_CONTENT_TYPE,
        metadata={"project-id": str(project_id), "parser": parser_version},
    )
    return StoredPageText(
        storage_key=stored.key,
        format=PAGE_TEXT_FORMAT,
        parser_version=parser_version,
        pages=scan.pages,
        empty_pages=scan.empty_pages,
        size_bytes=stored.size,
        sha256=stored.sha256,
    )


async def iter_page_texts(
    storage: ObjectStorage, storage_key: str, *, max_bytes: int
) -> AsyncIterator[PageText]:
    """Страницы из объекта хранилища; распаковка потоковая, предел - `max_bytes` распакованных.

    Бросает `PageTextError` (формат, неполный файл, предел) и `ObjectNotFoundError` хранилища.
    """
    decoder = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
    state = _LineState()
    pending = b""
    total = 0

    def lines(data: bytes) -> list[bytes]:
        nonlocal pending
        parts = (pending + data).split(b"\n")
        pending = parts.pop()
        return parts

    async for chunk in storage.iter_stream(storage_key, chunk_size=_READ_CHUNK):
        data = chunk
        while data:
            try:
                # Порция распаковки ограничена остатком предела (+1 - чтобы заметить превышение).
                part = decoder.decompress(data, max_bytes - total + 1)
            except zlib.error as error:
                raise PageTextError("объект текста страниц не gzip") from error
            total += len(part)
            if total > max_bytes:
                raise PageTextError("распакованный текст страниц больше предела")
            data = decoder.unconsumed_tail
            for line in lines(part):
                page = state.feed(line)
                if page is not None:
                    yield page
    if not decoder.eof:
        raise PageTextError("объект текста страниц оборван")
    if pending.strip():
        page = state.feed(pending)
        if page is not None:
            yield page
    state.finish()
