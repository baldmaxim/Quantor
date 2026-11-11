"""Урезание контент-потока для текста страницы: фильтр и сквозной путь на синтетических PDF."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.services.consistency import pdf_text
from app.services.consistency.pdf_text import page_text, text_only_content

BLOCK_WITH_TRICKS = b"BT /F1 12 Tf 10 700 Td (A ET \\) \\( B (nested ET) C) Tj ET"


def test_keeps_bt_block_with_et_and_parens_inside_strings() -> None:
    data = b"0 0 m 5 5 l S\n" + BLOCK_WITH_TRICKS + b"\n1 1 m 2 2 l S"
    assert text_only_content(data) == BLOCK_WITH_TRICKS


def test_keeps_hex_string_with_block() -> None:
    block = b"BT /F1 12 Tf <0041 0042> Tj [<0043> -10 (D)] TJ ET"
    assert text_only_content(b"1 w 0 0 m 9 9 l S\n" + block) == block


def test_keeps_tf_before_bt_and_state_operators() -> None:
    data = b"q 1 0 0 1 5 5 cm /F1 9 Tf 2 Tc /GS0 gs BT (x) Tj ET Q"
    out = text_only_content(data)
    for piece in (b"1 0 0 1 5 5 cm", b"/F1 9 Tf", b"2 Tc", b"/GS0 gs", b"BT (x) Tj ET"):
        assert piece in out
    assert out.index(b"/F1 9 Tf") < out.index(b"BT")


def test_drops_path_and_paint_operators() -> None:
    data = b"10 20 m 30 40 l 50 60 70 80 re f S h\n0.5 g 1 0 0 rg BT (t) Tj ET"
    out = text_only_content(data)
    assert out == b"BT (t) Tj ET"
    for op in (b" m", b" l", b" re", b" S", b" f"):
        assert op not in out


def test_keeps_order_of_blocks_and_operators() -> None:
    data = b"/F1 8 Tf BT (one) Tj ET 1 2 m 3 4 l S /F2 9 Tf BT (two) Tj ET /Fm0 Do"
    out = text_only_content(data)
    positions = [out.index(x) for x in (b"/F1 8 Tf", b"(one)", b"/F2 9 Tf", b"(two)", b"/Fm0 Do")]
    assert positions == sorted(positions)


def test_et_inside_name_does_not_end_block() -> None:
    block = b"BT /FooET 12 Tf (x) Tj ET"
    assert text_only_content(block) == block


def test_empty_save_restore_pairs_are_collapsed() -> None:
    out = text_only_content(b"q 0 0 m 1 1 l S Q q 5 5 m 6 6 l S Q BT (x) Tj ET")
    assert out == b"BT (x) Tj ET"


def test_empty_input() -> None:
    assert text_only_content(b"") == b""


def _build_pdf(lines: int) -> bytes:
    """Страница: много линий и текст двумя блоками, второй со шрифтом, выбранным до BT."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
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
    path = b"".join(b"%d %d m %d %d l S\n" % (i, i, i + 5, i + 9) for i in range(lines))
    content = (
        b"q\n"
        + path
        + b"BT /F1 12 Tf 50 700 Td (Plan 1 etazh \\(sekciya 3\\) ET) Tj ET\n"
        + b"/F1 14 Tf\n"
        + path
        + b"BT 50 650 Td (Second line) Tj ET\nQ\n"
    )
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_page_text_trimmed_path_equals_full_text(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = PdfReader(io.BytesIO(_build_pdf(3000)))
    page = reader.pages[0]
    full = page.extract_text()
    assert "Plan 1 etazh" in full
    assert "Second line" in full

    calls: list[int] = []
    original = pdf_text.text_only_content

    def spy(data: bytes) -> bytes:
        calls.append(len(data))
        return original(data)

    monkeypatch.setattr(pdf_text, "HEAVY_CONTENT_BYTES", 1024)
    monkeypatch.setattr(pdf_text, "text_only_content", spy)
    assert page_text(page, reader) == full
    assert len(calls) == 1
    assert calls[0] > 1024
    # исходная страница не тронута
    assert page.extract_text() == full


def test_page_text_light_page_uses_full_path(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = PdfReader(io.BytesIO(_build_pdf(5)))
    page = reader.pages[0]

    def boom(data: bytes) -> bytes:
        raise AssertionError("легкая страница не урезается")

    monkeypatch.setattr(pdf_text, "text_only_content", boom)
    assert page_text(page, reader) == page.extract_text()


def test_page_text_falls_back_when_trim_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = PdfReader(io.BytesIO(_build_pdf(3000)))
    page = reader.pages[0]

    def boom(data: bytes) -> bytes:
        raise RuntimeError("сбой фильтра")

    monkeypatch.setattr(pdf_text, "HEAVY_CONTENT_BYTES", 1024)
    monkeypatch.setattr(pdf_text, "text_only_content", boom)
    assert page_text(page, reader) == page.extract_text()
