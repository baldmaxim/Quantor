"""Каноническая геометрия страницы PDF (ADR-0016)."""

from app.services.geometry.extract import (
    ExtractResult,
    extract_for_revision,
    fingerprint,
    idempotency_key,
    sheet_id_for,
)
from app.services.geometry.provider import (
    PageGeometryProvider,
    PypdfGeometryProvider,
    RawPageGeometry,
)
from app.services.geometry.schedule import schedule_extract
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    PdfDisplayPoint,
    distance_pdf_points,
    normalized_to_pdf_display,
    pdf_display_to_normalized,
    polygon_area_pdf_points2,
    polyline_length_pdf_points,
)

__all__ = [
    "ExtractResult",
    "NormalizedPoint",
    "PageGeometryProvider",
    "PageGeometryValue",
    "PdfDisplayPoint",
    "PypdfGeometryProvider",
    "RawPageGeometry",
    "distance_pdf_points",
    "extract_for_revision",
    "fingerprint",
    "idempotency_key",
    "normalized_to_pdf_display",
    "pdf_display_to_normalized",
    "polygon_area_pdf_points2",
    "polyline_length_pdf_points",
    "schedule_extract",
    "sheet_id_for",
]
