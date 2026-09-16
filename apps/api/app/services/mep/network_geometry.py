"""Длины и повороты участка сети по снимку калибровки — без базы, модели и изображения.

Плановая часть считается существующим ядром `services/geometry/transform.py` (правило `length.v1`:
нормализованные → точки PDF → мм), высотная — по отметкам. Ничего не угадывается: не хватает
калибровки, отметки или листа — участок получает код блокера, а не число.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from app.contracts.mep.boq import BlockerCode
from app.contracts.mep.common import Level, SheetRef
from app.contracts.mep.network import NetworkSegment, Vertex
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    polyline_length_pdf_points,
)

# Относительный допуск коллинеарности: шум binary64, а не инженерный порог угла.
COLLINEAR_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class SegmentLength:
    millimetres: Decimal | None
    blocker: BlockerCode | None


def _decimal(value: float) -> Decimal:
    """Граница «float → Decimal» (ADR-0017): `repr` — кратчайшая запись того же double."""
    return Decimal(repr(value))


def height_mm(vertex: Vertex, levels: dict[str, Level]) -> float | None:
    if vertex.z_mm is not None:
        return vertex.z_mm
    level = levels.get(vertex.level_id) if vertex.level_id is not None else None
    return level.elevation_mm if level is not None else None


def _page(sheet: SheetRef) -> tuple[PageGeometryValue, Decimal] | None:
    snapshot = sheet.calibration
    if snapshot is None:
        return None
    page = PageGeometryValue.from_decimal(snapshot.display_width_pt, snapshot.display_height_pt)
    return page, snapshot.mm_per_pt


def segment_length(
    segment: NetworkSegment, sheets: dict[str, SheetRef], levels: dict[str, Level]
) -> SegmentLength:
    path = segment.path
    heights = [height_mm(vertex, levels) for vertex in path]
    planar = [vertex.x is not None for vertex in path]
    same_sheet = len({vertex.sheet_id for vertex in path}) == 1
    level_run = len({h for h in heights if h is not None}) <= 1 and (
        all(h is None for h in heights) or all(h is not None for h in heights)
    )
    if all(planar) and same_sheet and level_run:
        # Горизонтальный участок на одном листе — ровно правило `length.v1`.
        sheet = sheets.get(path[0].sheet_id or "")
        resolved = _page(sheet) if sheet is not None else None
        if resolved is None:
            return SegmentLength(None, BlockerCode.NO_SCALE)
        page, factor = resolved
        points = [NormalizedPoint(v.x or 0.0, v.y or 0.0) for v in path]
        return SegmentLength(_decimal(polyline_length_pdf_points(points, page)) * factor, None)

    total = Decimal(0)
    for (a, ha), (b, hb) in pairwise(zip(path, heights, strict=True)):
        piece = _pair_length(a, b, ha, hb, sheets)
        if piece.blocker is not None:
            return piece
        total += piece.millimetres or Decimal(0)
    return SegmentLength(total, None)


def _pair_length(
    a: Vertex, b: Vertex, ha: float | None, hb: float | None, sheets: dict[str, SheetRef]
) -> SegmentLength:
    planar_mm = Decimal(0)
    if (a.x is None) != (b.x is None):
        return SegmentLength(None, BlockerCode.LENGTH_UNDETERMINED)
    if a.x is not None and b.x is not None:
        if a.sheet_id != b.sheet_id:
            return SegmentLength(None, BlockerCode.CROSS_SHEET_PLANAR)
        sheet = sheets.get(a.sheet_id or "")
        resolved = _page(sheet) if sheet is not None else None
        if resolved is None:
            return SegmentLength(None, BlockerCode.NO_SCALE)
        page, factor = resolved
        points = [NormalizedPoint(a.x, a.y or 0.0), NormalizedPoint(b.x, b.y or 0.0)]
        planar_mm = _decimal(polyline_length_pdf_points(points, page)) * factor
    if (ha is None) != (hb is None):
        return SegmentLength(None, BlockerCode.ELEVATION_INCOMPLETE)
    if ha is None or hb is None or ha == hb:
        if a.x is None:
            return SegmentLength(None, BlockerCode.LENGTH_UNDETERMINED)
        return SegmentLength(planar_mm, None)
    rise = abs(hb - ha)
    if planar_mm == 0:
        return SegmentLength(_decimal(rise), None)
    return SegmentLength(_decimal(math.hypot(float(planar_mm), rise)), None)


def turn_count(
    segment: NetworkSegment, sheets: dict[str, SheetRef], levels: dict[str, Level]
) -> int:
    """Число промежуточных вершин, где направление трассы меняется (в мм, с отметками).

    Вызывается только для участка, длина которого посчитана: калибровка его листа известна.
    """
    vectors: list[tuple[float, float, float]] = []
    for a, b in pairwise(segment.path):
        dx = dy = 0.0
        if a.x is not None and b.x is not None and a.sheet_id is not None:
            snapshot = sheets[a.sheet_id].calibration
            if snapshot is not None:
                factor = float(snapshot.mm_per_pt)
                dx = (b.x - a.x) * float(snapshot.display_width_pt) * factor
                dy = ((b.y or 0.0) - (a.y or 0.0)) * float(snapshot.display_height_pt) * factor
        ha, hb = height_mm(a, levels), height_mm(b, levels)
        dz = hb - ha if ha is not None and hb is not None else 0.0
        if dx or dy or dz:
            vectors.append((dx, dy, dz))
    return sum(1 for u, v in pairwise(vectors) if not _same_direction(u, v))


def _same_direction(u: tuple[float, float, float], v: tuple[float, float, float]) -> bool:
    cross = (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )
    scale = math.hypot(*u) * math.hypot(*v)
    dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2]
    return math.hypot(*cross) <= COLLINEAR_TOLERANCE * scale and dot > 0
