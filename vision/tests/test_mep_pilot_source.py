"""Synthetic coordinate checks; no client pages or human-confirmation assertions."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from quantor_vision.mep.pilot_source import text_origins
from tests.test_mep_discovery import pdf_bytes


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_text_origin_rotation_and_read_only(tmp_path: Path, rotation: int) -> None:
    reader = PdfReader(BytesIO(pdf_bytes(text=True)))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    page.rotate(rotation)
    path = tmp_path / "synthetic.pdf"
    with path.open("wb") as stream:
        writer.write(stream)
    before = path.read_bytes()
    result = text_origins(path, [1])
    assert path.read_bytes() == before
    spans = result[0]["spans"]
    assert isinstance(spans, list)
    span = next(s for s in spans if s["text"].strip() == "Synthetic hello")
    x, y = 20 / 595.276, 1 - 40 / 841.89
    expected = {0: (x, y), 90: (1 - y, x), 180: (1 - x, 1 - y), 270: (y, 1 - x)}
    assert span["origin"] == pytest.approx(expected[rotation])
    assert span["geometry_semantics"] == "text_origin_not_glyph_bbox"
