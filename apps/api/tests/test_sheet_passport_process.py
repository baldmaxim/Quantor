"""Паспорт листа: разбор PDF в подпроцессе с пределами (ADR-0043); только синтетика."""

from __future__ import annotations

import gzip
import io
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus
from app.services.consistency import passport_cli, passport_process
from app.services.consistency.page_texts import (
    PAGE_TEXT_FORMAT,
    PageText,
    scan_page_text_file,
)
from app.services.consistency.passport_codec import candidate_from_json, candidate_to_json
from app.services.consistency.passport_process import (
    REASON_FAILED,
    REASON_MEMORY,
    REASON_TIMEOUT,
    REASON_UNREADABLE,
    PassportParseError,
    parse_pdf_in_subprocess,
)
from app.services.consistency.sheet_passport import (
    PARSER_VERSION,
    PageInput,
    extract_pdf_pages,
    parse_page,
)
from tests.conftest import FakeObjectStorage, make_context
from tests.test_sheet_passports import _add_pdf, _extract, _project, _settings, _url

GOOD_NAME = "ПД-00000001-12-АР1.pdf"
OTHER_NAME = "ПД-00000001-12-ИОС2.pdf"


def _pdf_bytes(pages: int = 2) -> bytes:
    """Мини-PDF с текстовым слоем (латиница, стандартный шрифт)."""
    writer = PdfWriter()
    for number in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 200 Td (Plan floor {number + 3}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_codec_roundtrip() -> None:
    page = next(iter(extract_pdf_pages(io.BytesIO(_pdf_bytes(1)), GOOD_NAME)))
    candidate = parse_page(page)
    assert candidate.evidence  # шифр из имени файла
    assert candidate_from_json(candidate_to_json(candidate)) == candidate
    with pytest.raises(ValueError):
        candidate_from_json({"page_index": "0"})
    with pytest.raises(ValueError):
        candidate_from_json({"page_index": 0, "sheet_kind": "nope"})


async def test_subprocess_gives_same_candidates_as_direct_call(tmp_path: Path) -> None:
    data = _pdf_bytes(2)
    path = tmp_path / "source.pdf"
    path.write_bytes(data)
    direct = [parse_page(page) for page in extract_pdf_pages(io.BytesIO(data), GOOD_NAME)]
    via_process = await parse_pdf_in_subprocess(
        path, GOOD_NAME, memory_limit_mb=448, timeout_seconds=60
    )
    assert len(via_process.candidates) == 2
    assert via_process.candidates == direct
    assert via_process.text_path.is_file()
    pages = scan_page_text_file(via_process.text_path, max_bytes=1024 * 1024)
    assert pages.pages == 2


@pytest.mark.parametrize("data", [b"not a pdf at all", _pdf_bytes(1)[:120]])
async def test_unreadable_pdf_is_pdf_unreadable(tmp_path: Path, data: bytes) -> None:
    """Не PDF и обрезанный файл - своя причина, а не общий ParseFailed."""
    path = tmp_path / "source.pdf"
    path.write_bytes(data)
    with pytest.raises(PassportParseError) as caught:
        await parse_pdf_in_subprocess(path, "x.pdf", memory_limit_mb=448, timeout_seconds=60)
    assert caught.value.reason == REASON_UNREADABLE


def _read_texts(path: Path) -> list[PageText]:
    scan_page_text_file(path, max_bytes=1024 * 1024)
    with gzip.open(path, "rb") as stream:
        lines = [json.loads(line) for line in stream.read().splitlines()]
    assert lines[0]["format"] == PAGE_TEXT_FORMAT and lines[0]["parser"] == PARSER_VERSION
    return [
        PageText(item["page_index"], item["label"], item["text"])
        for item in lines[1:]
        if "page_index" in item
    ]


def test_cli_writes_page_text_and_strips_nul(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")

    def pages(stream: object, file_name: str) -> Iterator[PageInput]:
        yield PageInput(0, "План\x00 этажа", file_name, "1\x00")
        yield PageInput(1, "", file_name, None)

    monkeypatch.setattr(passport_cli, "extract_pdf_pages", pages)
    out, text = tmp_path / "out.json", tmp_path / "text.gz"
    assert passport_cli.main([str(pdf), "x.pdf", str(out), str(text)]) == 0
    assert _read_texts(text) == [PageText(0, "1", "План этажа"), PageText(1, None, "")]
    assert scan_page_text_file(text, max_bytes=1024 * 1024).empty_pages == 1
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 2


def test_cli_exit_codes(tmp_path: Path) -> None:
    out, text = tmp_path / "out.json", tmp_path / "text.gz"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(_pdf_bytes(1)[:120])
    assert (
        passport_cli.main([str(broken), "x.pdf", str(out), str(text)])
        == passport_cli.EXIT_UNREADABLE
    )
    assert passport_cli.main([str(broken), "x.pdf", str(out)]) == passport_cli.EXIT_USAGE
    missing = tmp_path / "missing.pdf"
    assert (
        passport_cli.main([str(missing), "x.pdf", str(out), str(text)]) == passport_cli.EXIT_FAILED
    )


@pytest.mark.parametrize(
    ("script", "limit", "reason"),
    [
        ("raise SystemExit(3)", 30.0, REASON_MEMORY),
        ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", 30.0, REASON_MEMORY),
        ("raise SystemExit(1)", 30.0, REASON_FAILED),
        ("raise SystemExit(4)", 30.0, REASON_UNREADABLE),
        (
            "import sys; open(sys.argv[-2], 'w').write('{'); open(sys.argv[-1], 'w').write('')",
            30.0,
            REASON_FAILED,
        ),
        (
            "open(__import__('sys').argv[-2], 'w').write('[]')",
            30.0,
            REASON_FAILED,
        ),  # нет файла текста
        ("import time; time.sleep(60)", 1.0, REASON_TIMEOUT),
    ],
)
async def test_failure_classes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: str, limit: float, reason: str
) -> None:
    def command(pdf_path: Path, file_name: str, out_path: Path, text_path: Path) -> list[str]:
        return [sys.executable, "-c", script, str(pdf_path), file_name, str(out_path)]

    monkeypatch.setattr(passport_process, "_command", command)
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    with pytest.raises(PassportParseError) as caught:
        await parse_pdf_in_subprocess(path, "x.pdf", memory_limit_mb=448, timeout_seconds=limit)
    assert caught.value.reason == reason


async def test_memory_limit_is_applied_to_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def command(pdf_path: Path, file_name: str, out_path: Path, text_path: Path) -> list[str]:
        return [sys.executable, "-c", "import sys; x = bytearray(300 * 1024 * 1024)"]

    monkeypatch.setattr(passport_process, "_command", command)
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    with pytest.raises(PassportParseError) as caught:
        await parse_pdf_in_subprocess(path, "x.pdf", memory_limit_mb=128, timeout_seconds=30)
    # Python выходит с кодом 1 при непойманном MemoryError: это отказ разбора, не успех.
    assert caught.value.reason in {REASON_MEMORY, REASON_FAILED}


async def test_job_continues_after_failed_file(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, "A-битый.pdf", data=b"garbage")
        await _add_pdf(db_session, fake_storage, project_id, GOOD_NAME, data=_pdf_bytes(2))
        await _add_pdf(db_session, fake_storage, project_id, OTHER_NAME, data=_pdf_bytes(1))

        job = await _extract(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        assert job.payload["files_total"] == 3
        assert job.payload["files_parsed"] == 2 and job.payload["pages"] == 3
        assert job.payload["files_already_parsed"] == 0
        assert job.payload["errors"] == [{"file_name": "A-битый.pdf", "reason": REASON_UNREADABLE}]
        assert job.payload["page_texts_stored"] == 2
        listing = (await api.get(_url(project_id))).json()
        assert listing["total"] == 3
