"""Статистика модели листа: счётчики, длины по классам толщины, сводка review. Только числа."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from pydantic import JsonValue

from building_model.canonical import ReviewItem, WallOut
from building_model.geometry import rnd
from building_model.params import Params
from building_model.reader import SheetIn
from building_model.walls import WallsResult


def band_label(thickness: float, bands: Sequence[float]) -> str:
    """Класс толщины для статистики: «<100», «100-150», …, «>=400»."""
    edges = sorted(bands)
    if thickness < edges[0]:
        return f"<{edges[0]:g}"
    for lo, hi in pairwise(edges):
        if thickness < hi:
            return f"{lo:g}-{hi:g}"
    return f">={edges[-1]:g}"


def gap_histogram(result: WallsResult, params: Params) -> dict[str, JsonValue]:
    """Сколько висячих концов в каждом интервале зазора до грани ближайшей другой стены."""
    edges = [params.dangling_tol_mm, *sorted(params.dangling_excess_bands_mm)]
    labels = [f"{lo:g}-{hi:g}" for lo, hi in pairwise(edges)] + [f">{edges[-1]:g}"]
    counts = dict.fromkeys(labels, 0)
    for end in result.dangling:
        gap = end.gap_to_face_mm
        index = len(labels) - 1
        if gap is not None:
            for i, hi in enumerate(edges[1:]):
                if gap <= hi:
                    index = i
                    break
        counts[labels[index]] += 1
    return dict(counts)


def _outline_stats(result: WallsResult) -> dict[str, JsonValue]:
    """Судьба стен без segments: сколько вернулось осью по контуру и сколько осталось вне модели."""
    stats: dict[str, JsonValue] = {}
    for outcome in ("used", "filtered", "duplicate", "compact", "not_rectangle"):
        items = [n for n in result.outline_outcomes if n.outcome == outcome]
        stats[outcome] = {
            "walls": len(items),
            "area_m2": rnd(sum(n.area_m2 for n in items), 2),
            "axis_length_m": rnd(sum(n.length_mm for n in items) / 1000.0, 2),
        }
    return stats


def build_stats(
    sheet: SheetIn,
    building: int | None,
    params: Params,
    result: WallsResult,
    walls_out: Sequence[WallOut],
    wall_keys: Sequence[str],
    opening_stats: dict[str, JsonValue],
    rooms_total: int,
    rooms_compared: int,
    counts: dict[str, int],
    items: Sequence[ReviewItem],
    slabs: int,
    stacks: int,
    columns: int,
) -> dict[str, JsonValue]:
    by_band: dict[str, float] = {}
    for w in walls_out:
        label = band_label(w.thickness_mm, params.survey_thickness_bands_mm)
        length = ((w.b[0] - w.a[0]) ** 2 + (w.b[1] - w.a[1]) ** 2) ** 0.5
        by_band[label] = by_band.get(label, 0.0) + length / 1000.0
    real = [r for r in result.rejected if not r.piece.outline]
    rejected_thin = sum(1 for r in real if r.code == "wall_rejected_thin")
    rejected_short = sum(1 for r in real if r.code == "wall_rejected_short")
    outline = _outline_stats(result)
    near = sum(1 for d in result.dangling if d.near_opening)
    area_m2 = sum(
        ((w.b[0] - w.a[0]) ** 2 + (w.b[1] - w.a[1]) ** 2) ** 0.5 * w.thickness_mm / 1e6
        for w in walls_out
    )
    review_codes: dict[str, int] = {}
    for item in items:
        review_codes[item.code] = review_codes.get(item.code, 0) + 1
    title = sheet.title
    floors: list[JsonValue] = []
    if title is not None:
        floors.extend(sorted(title.floors))
    thickness_bands: dict[str, JsonValue] = {k: rnd(v, 2) for k, v in sorted(by_band.items())}
    return {
        "sheet": {
            "page": sheet.page,
            "section": sheet.section,
            "kind": sheet.kind.kind,
            "verdict": sheet.verdict,
            "building_group": building,
            "floors": floors,
        },
        "scale": {
            "mm_per_pt": sheet.scale.mm_per_pt,
            "method": sheet.scale.method,
            "confident": sheet.scale.confident,
            "disagrees_with_printed": sheet.scale.disagrees_with_printed,
        },
        "walls": {
            "pieces_total": result.pieces_total,
            "pieces_kept": result.pieces_total - rejected_thin - rejected_short,
            "rejected_thin": rejected_thin,
            "rejected_short": rejected_short,
            "without_segments": len(result.outline_outcomes),
            "plangeom_area_m2": rnd(result.input_area_m2, 2),
            "without_segments_area_m2": rnd(sum(n.area_m2 for n in result.outline_outcomes), 2),
            "outline_axis": outline,
            "merged": len(walls_out),
            "bridged_gaps": result.bridged_gaps,
            "bridged_gap_length_m": rnd(result.bridged_gap_mm / 1000.0, 2),
            "kept_pieces_length_m": rnd(result.kept_length_mm / 1000.0, 2),
            "dangling_ends": len(result.dangling),
            "dangling_ends_near_opening": near,
            "dangling_gap_to_face_mm": gap_histogram(result, params),
            "ends_total": 2 * len(wall_keys),
            "length_m_by_thickness_band": thickness_bands,
            "length_m_total": rnd(sum(by_band.values()), 2),
            "area_m2": rnd(area_m2, 2),
        },
        "openings": opening_stats,
        "columns": columns,
        "rooms": {"total": rooms_total, "compared_with_schedule": rooms_compared},
        "slabs": slabs,
        "stacks": stacks,
        "review_by_code": dict(sorted(review_codes.items())),
        "review": dict(counts),
    }
