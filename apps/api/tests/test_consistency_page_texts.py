"""Текст страниц ревизии (В1): запись, проверка, выгрузка и потоковое чтение с пределом."""

from __future__ import annotations

import gzip
import uuid
from pathlib import Path

import pytest

from app.services.consistency.page_texts import (
    PAGE_TEXT_FORMAT,
    PageText,
    PageTextError,
    PageTextWriter,
    iter_page_texts,
    page_text_key,
    scan_page_text_file,
    store_page_text_file,
)
from tests.conftest import FakeObjectStorage

MAX = 1024 * 1024


def _write(path: Path, pages: list[tuple[str | None, str]]) -> None:
    with PageTextWriter(path, "parser.test") as writer:
        for index, (label, text) in enumerate(pages):
            writer.add(index, label, text)


async def _collect(storage: FakeObjectStorage, key: str, max_bytes: int = MAX) -> list[PageText]:
    return [page async for page in iter_page_texts(storage, key, max_bytes=max_bytes)]


def test_key_follows_revision() -> None:
    project, revision = uuid.uuid4(), uuid.uuid4()
    assert page_text_key(project, revision) == (
        f"consistency/page-text/{project}/{revision}/v1.jsonl.gz"
    )


def test_scan_counts_pages_and_empty_pages(tmp_path: Path) -> None:
    path = tmp_path / "t.gz"
    _write(path, [("1", "План"), (None, "  \n"), ("3", "")])
    scan = scan_page_text_file(path, max_bytes=MAX)
    assert (scan.pages, scan.empty_pages) == (3, 2)


def test_scan_rejects_unfinished_and_foreign_files(tmp_path: Path) -> None:
    unfinished = tmp_path / "unfinished.gz"
    with pytest.raises(RuntimeError), PageTextWriter(unfinished, "p") as writer:
        writer.add(0, None, "текст")
        raise RuntimeError("подпроцесс убит")
    with pytest.raises(PageTextError):
        scan_page_text_file(unfinished, max_bytes=MAX)

    foreign = tmp_path / "foreign.gz"
    foreign.write_bytes(gzip.compress(b'{"format": "other"}\n'))
    with pytest.raises(PageTextError):
        scan_page_text_file(foreign, max_bytes=MAX)

    not_gzip = tmp_path / "plain.gz"
    not_gzip.write_bytes(b"plain text")
    with pytest.raises(PageTextError):
        scan_page_text_file(not_gzip, max_bytes=MAX)


async def test_store_and_read_roundtrip(tmp_path: Path) -> None:
    storage = FakeObjectStorage()
    project, revision = uuid.uuid4(), uuid.uuid4()
    path = tmp_path / "t.gz"
    pages = [("1", "Первая страница"), (None, ""), ("С-3", "Третья\nс переводом строки")]
    _write(path, pages)
    stored = await store_page_text_file(
        storage,
        project_id=project,
        revision_id=revision,
        path=path,
        parser_version="parser.test",
        max_bytes=MAX,
    )
    assert stored.storage_key == page_text_key(project, revision)
    assert stored.format == PAGE_TEXT_FORMAT
    assert (stored.pages, stored.empty_pages) == (3, 1)
    assert stored.size_bytes == path.stat().st_size == len(storage.objects[stored.storage_key])
    assert len(stored.sha256) == 64

    read = await _collect(storage, stored.storage_key)
    assert read == [PageText(i, label, text) for i, (label, text) in enumerate(pages)]


async def test_read_streams_in_small_chunks(tmp_path: Path) -> None:
    storage = FakeObjectStorage()
    path = tmp_path / "t.gz"
    pages = [(str(n), f"страница {n} " + "я" * 5000) for n in range(40)]
    _write(path, pages)
    storage.objects["k"] = path.read_bytes()
    read = [page async for page in iter_page_texts(storage, "k", max_bytes=10 * MAX)]
    assert [item.text for item in read] == [text for _, text in pages]


async def test_decompressed_size_limit(tmp_path: Path) -> None:
    storage = FakeObjectStorage()
    path = tmp_path / "t.gz"
    _write(path, [(None, "а" * 200_000), (None, "б" * 200_000)])
    storage.objects["k"] = path.read_bytes()
    assert len(storage.objects["k"]) < 5_000  # сжатие велико, предел считается по распакованному
    assert len(await _collect(storage, "k", max_bytes=MAX)) == 2
    with pytest.raises(PageTextError):
        await _collect(storage, "k", max_bytes=100_000)
    with pytest.raises(PageTextError):
        scan_page_text_file(path, max_bytes=100_000)


async def test_truncated_object_is_rejected(tmp_path: Path) -> None:
    storage = FakeObjectStorage()
    path = tmp_path / "t.gz"
    _write(path, [("1", "текст")] * 50)
    storage.objects["k"] = path.read_bytes()[:-30]
    with pytest.raises(PageTextError):
        await _collect(storage, "k")
    storage.objects["bad"] = b"not gzip at all"
    with pytest.raises(PageTextError):
        await _collect(storage, "bad")
