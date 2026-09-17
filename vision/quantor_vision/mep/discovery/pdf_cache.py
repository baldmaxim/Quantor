"""Local text/operator cache for bounded PDF workers; never stores a raster."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import cast

from .common import Page, digest, stable, write_json
from .pdf import inspect_pdf
from .rules import classify, path_sources


def cache_root(path: Path) -> Path | None:
    for parent in reversed(path.parents):
        if parent.name == "raw" and (parent.parent / "inventory/source_snapshot.json").is_file():
            return parent.parent / ".pdf-cache"
    return None


def _restore(record: dict[str, object], sources: list[str]) -> Page:
    # Evidence is reclassified using the current occurrence paths, never cache-worker paths.
    c = cast(dict[str, dict[str, object]], record["classification"])
    evidence = [
        cast(dict[str, str], e)
        for finding in c.values()
        for e in cast(list[object], finding["evidence"])
    ]
    text_sources = list(
        dict.fromkeys(
            (e["source"], e["line"]) for e in evidence if e["source"] in ("stamp", "title")
        )
    )
    text_sources.sort(key=lambda item: (item[0] != "stamp", item[1]))
    if "titles" in record:
        text_sources = [
            ("stamp", str(record.get("stamp_text") or "")),
            ("title", str(record["titles"])),
        ]
    return Page(
        str(record["page_id"]),
        str(record["file_id"]),
        cast(int, record["page_number"]),
        cast(list[float], record["media_box_mm"]),
        cast(list[float], record["crop_box_mm"]),
        cast(int, record["rotation"]),
        str(record["paper_format"]),
        cast(int, record["text_characters"]),
        cast(float, record["largest_image_fraction"]),
        str(record["content_kind"]),
        cast(str | None, record["stamp_text"]),
        classify([*text_sources, *path_sources(sources)]),
        str(record["text_sha256"]),
        issues=cast(list[str], record["issues"]),
        titles=str(record.get("titles", "")),
    )


@contextmanager
def _lease(path: Path) -> Iterator[None]:
    with path.open("a+b") as stream:
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cached_pdf(path: Path, file_id: str, sources: list[str]) -> tuple[list[Page], list[str]]:
    root = cache_root(path)
    if root is None:
        return inspect_pdf(path, file_id, sources)
    root.mkdir(exist_ok=True)
    signature = stable(
        [
            file_id,
            digest(Path(__file__).with_name("pdf.py")),
            digest(Path(__file__).with_name("rules.py")),
            digest(Path(__file__).with_name("content.py")),
        ]
    )
    if (root / (signature + ".json")).is_file():
        return _cached_pdf(path, file_id, sources, root)
    with _lease(root / (file_id + ".lock")):
        return _cached_pdf(path, file_id, sources, root)


def _cached_pdf(
    path: Path, file_id: str, sources: list[str], root: Path
) -> tuple[list[Page], list[str]]:
    signature = stable(
        [
            file_id,
            digest(Path(__file__).with_name("pdf.py")),
            digest(Path(__file__).with_name("rules.py")),
            digest(Path(__file__).with_name("content.py")),
        ]
    )
    target = root / (signature + ".json")
    if target.is_file():
        data: dict[str, object] = json.loads(target.read_text(encoding="utf-8"))
        if data.get("signature") == signature:
            pages = [_restore(row, sources) for row in cast(list[dict[str, object]], data["pages"])]
            return pages, cast(list[str], data["issues"])
    partial = root / (signature + ".partial.jsonl")
    previous: list[Page] = []
    if partial.is_file():
        for line in partial.read_text(encoding="utf-8").splitlines():
            try:
                row: dict[str, object] = json.loads(line)
                page = _restore(row, [])
                if page.file_id != file_id or page.page_number != len(previous) + 1:
                    break
                previous.append(page)
            except (ValueError, KeyError, TypeError):
                break
    # Rewrite a possibly interrupted last line, then flush each finished page.
    with partial.open("w", encoding="utf-8") as progress:
        for page in previous:
            progress.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
        progress.flush()

        def save_page(page: Page) -> None:
            progress.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
            progress.flush()

        remaining, issues = inspect_pdf(
            path, file_id, [], start_page=len(previous) + 1, on_page=save_page
        )
    pages = previous + remaining
    temporary = root / f"{signature}.{os.getpid()}.tmp"
    write_json(
        temporary, {"signature": signature, "pages": [asdict(p) for p in pages], "issues": issues}
    )
    temporary.replace(target)
    partial.unlink(missing_ok=True)
    return [_restore(asdict(p), sources) for p in pages], issues
