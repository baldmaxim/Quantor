"""Export PDF text origins for local review, without asserting human annotation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from pypdf import PdfReader
from pypdf.generic import ContentStream, DictionaryObject, NameObject, RectangleObject

from .discovery.content import without_path_coordinates
from .discovery.pdf import _prepare_forms, matrix, multiply


def text_origins(path: Path, page_numbers: list[int]) -> list[dict[str, object]]:
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    reader = PdfReader(path)
    results = []
    for number in page_numbers:
        page = reader.pages[number - 1]
        spans: list[dict[str, object]] = []
        box = page.cropbox

        def visitor(
            text: str,
            cm: list[float],
            tm: list[float],
            font: DictionaryObject | None,
            size: float,
            box: RectangleObject = box,
            rotation: int = page.rotation % 360,
            spans: list[dict[str, object]] = spans,
            number: int = number,
        ) -> None:
            if not text.strip():
                return
            transform = multiply(matrix(tm), matrix(cm))
            x = (transform[4] - float(box.left)) / float(box.width)
            y = 1 - (transform[5] - float(box.bottom)) / float(box.height)
            if rotation == 90:
                x, y = 1 - y, x
            elif rotation == 180:
                x, y = 1 - x, 1 - y
            elif rotation == 270:
                x, y = y, 1 - x
            elif rotation != 0:
                raise ValueError("unsupported_page_rotation")
            spans.append(
                {
                    "span_id": f"p{number}-t{len(spans) + 1}",
                    "text": text,
                    "origin": [x, y],
                    "inside_page": 0 <= x <= 1 and 0 <= y <= 1,
                    "font_size_pdf_units": size,
                    "geometry_semantics": "text_origin_not_glyph_bbox",
                }
            )

        if "/Resources" in page:
            _prepare_forms(cast(DictionaryObject, page["/Resources"].get_object()), set())
        raw = page.get("/Contents")
        if raw is not None:
            content = ContentStream(raw.get_object(), page.pdf, "bytes")
            content.set_data(without_path_coordinates(content.get_data()))
            page[NameObject("/Contents")] = content
        text = page.extract_text(visitor_text=visitor)
        results.append(
            {
                "page_number": number,
                "spans": spans,
                "text": text,
                "coordinate_system": "normalized_rotated_cropbox_top_left",
                "rotation": page.rotation,
            }
        )
    return results
