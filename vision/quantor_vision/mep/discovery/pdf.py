"""Text and PDF operators only. No rasterization, OCR, images decoded, or models."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from pypdf import PageObject, PdfReader
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    RectangleObject,
    StreamObject,
)

from .common import Page, stable
from .content import without_path_coordinates
from .rules import STAMP_LABEL_PATTERN, TITLE_PATTERN, classify, path_sources

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def _prepare_forms(resources: DictionaryObject, seen: set[int], depth: int = 0) -> None:
    if depth > 20:
        return
    objects = resources.get("/XObject", DictionaryObject()).get_object()
    for key in list(objects):
        form = objects[key].get_object()
        if form.get("/Subtype") != "/Form" or id(form) in seen:
            continue
        seen.add(id(form))
        prepared = DecodedStreamObject()
        prepared.update(
            {k: v for k, v in form.items() if k not in ("/Length", "/Filter", "/DecodeParms")}
        )
        prepared.set_data(without_path_coordinates(form.get_data()))
        seen.add(id(prepared))
        objects[key] = prepared
        if "/Resources" in prepared:
            _prepare_forms(
                cast(DictionaryObject, prepared["/Resources"].get_object()), seen, depth + 1
            )


def multiply(a: Matrix, b: Matrix) -> Matrix:
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def matrix(values: object) -> Matrix:
    if not isinstance(values, (list, tuple)) or len(values) != 6:
        raise ValueError("invalid_matrix")
    a, b, c, d, e, f = [float(v) for v in values]
    return a, b, c, d, e, f


@dataclass
class ImageStats:
    largest: float = 0
    images: int = 0
    vector_paints: int = 0
    issues: set[str] = field(default_factory=set)
    operations: int = 0


def _fraction(transform: Matrix, box: RectangleObject) -> float:
    # Clip the transformed unit square polygon against CropBox (no bbox-area inflation).
    points = [
        (
            transform[0] * x + transform[2] * y + transform[4],
            transform[1] * x + transform[3] * y + transform[5],
        )
        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))
    ]
    for axis, bound, sign in (
        (0, float(box.left), 1),
        (0, float(box.right), -1),
        (1, float(box.bottom), 1),
        (1, float(box.top), -1),
    ):
        clipped = []
        for previous, current in zip(points[-1:] + points[:-1], points, strict=True):
            inside_p = (previous[axis] - bound) * sign >= 0
            inside_c = (current[axis] - bound) * sign >= 0
            if inside_p != inside_c:
                t = (bound - previous[axis]) / (current[axis] - previous[axis])
                clipped.append(
                    (
                        previous[0] + t * (current[0] - previous[0]),
                        previous[1] + t * (current[1] - previous[1]),
                    )
                )
            if inside_c:
                clipped.append(current)
        points = clipped
    area = (
        abs(
            sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1], strict=True)
            )
        )
        / 2
    )
    return min(1.0, area / max(float(box.width) * float(box.height), 1))


def _walk(
    content: ContentStream,
    resources: DictionaryObject,
    transform: Matrix,
    page: PageObject,
    stats: ImageStats,
    depth: int = 0,
) -> None:
    if depth > 20:
        stats.issues.add("form_depth_limit")
        return
    stack: list[Matrix] = []
    for operands, operator in content.operations:
        stats.operations += 1
        if stats.operations > 2_000_000:
            raise ValueError("pdf_operation_limit")
        if operator == b"q":
            stack.append(transform)
        elif operator == b"Q":
            if stack:
                transform = stack.pop()
        elif operator == b"cm":
            transform = multiply(matrix(operands), transform)
        elif operator in (b"W", b"W*"):
            stats.issues.add("image_fraction_upper_bound_custom_clipping")
        elif operator in (b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
            stats.vector_paints += 1
        elif operator == b"INLINE IMAGE":
            stats.images += 1
            stats.largest = max(stats.largest, _fraction(transform, page.cropbox))
        elif operator == b"Do":
            objects = resources.get("/XObject", DictionaryObject()).get_object()
            obj = objects.get(operands[0])
            if obj is None:
                continue
            obj = obj.get_object()
            if obj.get("/Subtype") == "/Image":
                stats.images += 1
                stats.largest = max(stats.largest, _fraction(transform, page.cropbox))
            elif obj.get("/Subtype") == "/Form":
                child = multiply(matrix(obj.get("/Matrix", list(IDENTITY))), transform)
                child_resources = obj.get("/Resources", resources).get_object()
                _walk(
                    ContentStream(cast(StreamObject, obj), page.pdf),
                    cast(DictionaryObject, child_resources),
                    child,
                    page,
                    stats,
                    depth + 1,
                )


def paper_format(box: RectangleObject, unit: float) -> str:
    width, height = sorted(
        (float(box.width) * unit * 25.4 / 72, float(box.height) * unit * 25.4 / 72)
    )
    for name, w, h in (
        ("A0", 841, 1189),
        ("A1", 594, 841),
        ("A2", 420, 594),
        ("A3", 297, 420),
        ("A4", 210, 297),
    ):
        if abs(width - w) <= 3 and abs(height - h) <= 3:
            return name
    return "nonstandard"


def inspect_pdf(
    path: Path,
    file_id: str,
    paths: list[str],
    *,
    start_page: int = 1,
    on_page: Callable[[Page], None] | None = None,
) -> tuple[list[Page], list[str]]:
    # pypdf warnings can contain client text; status codes below replace console logging.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    pages: list[Page] = []
    issues: list[str] = []
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            return [], ["encrypted_pdf"]
        for number, page in enumerate(reader.pages, 1):
            if number < start_page:
                continue
            local_issues: list[str] = []
            stamp_spans: list[str] = []
            unit = float(page.get("/UserUnit", 1))
            if not math.isfinite(unit) or unit <= 0:
                raise ValueError("invalid_user_unit")

            def visitor(
                text: str,
                cm: list[float],
                tm: list[float],
                font: DictionaryObject | None,
                size: float,
                page: PageObject = page,
                unit: float = unit,
                stamp_spans: list[str] = stamp_spans,
            ) -> None:
                position = multiply(matrix(tm), matrix(cm))
                x, y = position[4], position[5]
                # GOST-sized bottom-right region is a candidate, not proof of a stamp.
                if (
                    page.rotation == 0
                    and x >= float(page.cropbox.right) - 190 * 72 / 25.4 / unit
                    and float(page.cropbox.bottom)
                    <= y
                    <= float(page.cropbox.bottom) + 60 * 72 / 25.4 / unit
                ):
                    stamp_spans.append(text)

            content = None
            try:
                if "/Resources" in page:
                    _prepare_forms(cast(DictionaryObject, page["/Resources"].get_object()), set())
                raw_content = page.get("/Contents")
                if raw_content is not None:
                    # Reuse parsed operators for text and image inventory. Only the in-memory
                    # reader object is changed; the source PDF is never written.
                    content = ContentStream(raw_content.get_object(), page.pdf, "bytes")
                    content.set_data(without_path_coordinates(content.get_data()))
                    page[NameObject("/Contents")] = content
                text = page.extract_text(visitor_text=visitor)
            except Exception as error:
                text = ""
                local_issues.append("text_extraction_failed:" + type(error).__name__)
            stamp_candidate = "\n".join(stamp_spans).strip()
            stamp = (
                stamp_candidate
                if text.strip() and re.search(STAMP_LABEL_PATTERN, stamp_candidate, re.IGNORECASE)
                else None
            )
            if text.strip() and stamp is None:
                local_issues.append("stamp_not_located")
            titles = "\n".join(
                line for line in text.splitlines() if re.search(TITLE_PATTERN, line, re.IGNORECASE)
            )
            sources = [("stamp", stamp or ""), ("title", titles), *path_sources(paths)]
            stats = ImageStats()
            try:
                if content is not None:
                    resources = cast(DictionaryObject, page["/Resources"].get_object())
                    _walk(content, resources, IDENTITY, page, stats)
            except Exception as error:
                stats.issues.add("image_inspection_failed:" + type(error).__name__)
            kind = "vector"
            if stats.images:
                kind = "mixed"
                if stats.largest >= 0.8 and not text.strip() and not stats.vector_paints:
                    kind = "raster_scan"
            local_issues.extend(sorted(stats.issues))
            if not text.strip() and not stats.images and not stats.vector_paints:
                local_issues.append("blank_or_unclassified_page")
            pages.append(
                Page(
                    f"{file_id}:{number}",
                    file_id,
                    number,
                    [round(float(v) * unit * 25.4 / 72, 4) for v in page.mediabox],
                    [round(float(v) * unit * 25.4 / 72, 4) for v in page.cropbox],
                    page.rotation,
                    paper_format(page.mediabox, unit),
                    len(text.strip()),
                    round(stats.largest, 6),
                    kind,
                    stamp,
                    classify(sources),
                    stable(text),
                    issues=local_issues,
                    titles=titles,
                )
            )
            if on_page is not None:
                on_page(pages[-1])
    except Exception as error:
        issues.append("pdf_inspection_failed:" + type(error).__name__)
    return pages, issues
