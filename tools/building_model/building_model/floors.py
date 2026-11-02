"""Уровни, плиты с отверстиями, помещения, колонны и контуры лестниц и лифтов."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from building_model.canonical import (
    ColumnOut,
    HoleKind,
    LevelOut,
    LevelStatus,
    ReviewItem,
    RoomOut,
    RoomStatus,
    SlabHole,
    SlabOut,
    SlabStatus,
    SourceRef,
    StackKind,
    StackOut,
    Status,
)
from building_model.coords import Frame
from building_model.elements import Column, natural_key
from building_model.geometry import Pt, canonical_polygon, centroid, point_in_polygon, rnd, rnd_pt
from building_model.keys import KeyRequest, allocate_keys, polygon_geometry
from building_model.params import Params
from building_model.reader import RoomIn, SheetIn, sheet_levels_m


@dataclass(frozen=True)
class LevelsResult:
    levels: list[LevelOut]
    carrier: str
    review: list[ReviewItem]


def _poly(points: Sequence[Pt], frame: Frame) -> list[Pt]:
    return [rnd_pt(p, 1) for p in canonical_polygon([frame.to_model(p) for p in points])]


def _ref(page: int, ids: Sequence[str]) -> list[SourceRef]:
    return [SourceRef(page=page, plangeom_ids=sorted(ids, key=natural_key))]


def _level_key(floor: int | None, elevation_mm: float | None) -> str:
    if floor is not None:
        return f"L{floor}"
    if elevation_mm is not None:
        return f"E{round(elevation_mm)}"
    return "L?"


def build_levels(sheet: SheetIn, neighbors_mm: Sequence[float], params: Params) -> LevelsResult:
    """Отметка — из штампа/плана (observed); высота — по соседней отметке комплекта (derived)."""
    review: list[ReviewItem] = []
    floors = sorted(set(sheet.title.floors)) if sheet.title is not None else []
    observed = [round(m * 1000.0, 1) for m in sheet_levels_m(sheet.title, sheet.floor_level)]
    slots: list[tuple[int | None, float | None, Status | None]] = []
    if not floors:
        elevation = observed[0] if observed else None
        slots.append((None, elevation, "observed" if elevation is not None else None))
    elif len(observed) == len(floors):
        slots.extend((f, e, "observed") for f, e in zip(floors, observed, strict=True))
    else:
        base = observed[0] if observed else None
        for fl in floors:
            if base is None:
                slots.append((fl, None, None))
            elif fl == floors[0]:
                slots.append((fl, base, "observed"))
            else:
                # Отметки остальных этажей типового листа штамп не даёт: параметр, а не наблюдение.
                shifted = base + (fl - floors[0]) * params.level_height_mm
                slots.append((fl, shifted, "assumed"))
    known = sorted({*neighbors_mm, *(e for _, e, _ in slots if e is not None)})
    keys = [_level_key(f, e) for f, e, _ in slots]
    carrier = keys[0]
    levels: list[LevelOut] = []
    for (floor, elevation, e_status), key in zip(slots, keys, strict=True):
        height = params.level_height_mm
        h_status: Status = "assumed"
        if elevation is not None:
            higher = [k for k in known if k > elevation + 1.0]
            if higher:
                diff = higher[0] - elevation
                if params.level_height_min_mm <= diff <= params.level_height_max_mm:
                    height, h_status = diff, "derived"
                else:
                    review.append(
                        ReviewItem(
                            code="level_height_implausible",
                            severity="warning",
                            element=key,
                            source_ids=[],
                            at=None,
                            detail={"next_level_diff_mm": rnd(diff)},
                        )
                    )
        else:
            review.append(
                ReviewItem(
                    code="level_unknown",
                    severity="blocker",
                    element=key,
                    source_ids=[],
                    at=None,
                    detail={},
                )
            )
        levels.append(
            LevelOut(
                key=key,
                floor=floor,
                elevation_mm=None if elevation is None else rnd(elevation),
                height_mm=rnd(height),
                status=LevelStatus(elevation_mm=e_status, height_mm=h_status),
                instance_of=None if key == carrier else carrier,
            )
        )
    return LevelsResult(levels=levels, carrier=carrier, review=review)


def build_columns(
    columns: Sequence[Column], level: str, page: int, params: Params
) -> list[ColumnOut]:
    requests = [
        KeyRequest(
            "c", "column", level, polygon_geometry(c.polygon, params.key_round_mm), c.wall_id
        )
        for c in columns
    ]
    keys = allocate_keys(requests)
    return [
        ColumnOut(
            key=key,
            level=level,
            polygon=[rnd_pt(p, 1) for p in col.polygon],
            status="observed",
            source=_ref(page, [col.wall_id]),
        )
        for key, col in zip(keys, columns, strict=True)
    ]


def build_slabs(
    sheet: SheetIn, frame: Frame, level: str, params: Params
) -> tuple[list[SlabOut], list[ReviewItem]]:
    """Плита с отверстиями: лестничные проёмы и шахты; отверстие вне плиты — предупреждение."""
    review: list[ReviewItem] = []
    outlines = [_poly(o, frame) for o in (sheet.slab_outlines_mm or []) if len(o) >= 3]
    outlines.sort()
    if not outlines:
        review.append(
            ReviewItem(
                code="no_slab_outline",
                severity="warning",
                element=None,
                source_ids=[],
                at=None,
                detail={},
            )
        )
    holes: list[list[SlabHole]] = [[] for _ in outlines]
    candidates: list[tuple[HoleKind, list[Pt], str]] = []
    for stair in sorted(sheet.stairs, key=lambda s: natural_key(s.id)):
        if stair.slab_opening_mm is not None and len(stair.slab_opening_mm) >= 3:
            candidates.append(("stair", _poly(stair.slab_opening_mm, frame), stair.id))
    for room in sorted(sheet.rooms, key=lambda r: natural_key(r.id)):
        if room.type == "shaft" and len(room.polygon_mm) >= 3:
            candidates.append(("shaft", _poly(room.polygon_mm, frame), room.id))
    for kind, polygon, source_id in candidates:
        center = centroid(polygon)
        owner = next((i for i, o in enumerate(outlines) if point_in_polygon(center, o)), None)
        if owner is None:
            review.append(
                ReviewItem(
                    code="slab_hole_outside",
                    severity="warning",
                    element=None,
                    source_ids=[source_id],
                    at=rnd_pt(center, 1),
                    detail={"kind": kind},
                )
            )
            continue
        holes[owner].append(
            SlabHole(
                kind=kind,
                polygon=polygon,
                status="derived",
                source=_ref(sheet.page, [source_id]),
            )
        )
    requests = [
        KeyRequest("s", "slab", level, polygon_geometry(o, params.key_round_mm), repr(o))
        for o in outlines
    ]
    keys = allocate_keys(requests)
    slabs = [
        SlabOut(
            key=key,
            level=level,
            polygon=outline,
            thickness_mm=params.slab_thickness_mm,
            holes=sorted(h, key=lambda x: (x.kind, x.polygon)),
            status=SlabStatus(outline="observed", thickness_mm="assumed"),
            source=_ref(sheet.page, []),
        )
        for key, outline, h in zip(keys, outlines, holes, strict=True)
    ]
    return slabs, review


def _room_type_status(room: RoomIn) -> Status:
    if room.type_source == "name":
        return "observed"
    if room.type_source == "geometry":
        return "derived"
    return "assumed"


def build_rooms(
    sheet: SheetIn, frame: Frame, level: str, params: Params
) -> tuple[list[RoomOut], list[ReviewItem], int]:
    """Помещения, кроме фасадных полостей, со сверкой площади с экспликацией.

    Третье значение результата — сколько помещений сверено.
    """
    review: list[ReviewItem] = []
    rooms = [
        r
        for r in sorted(sheet.rooms, key=lambda r: natural_key(r.id))
        if r.type != "facade cavity" and len(r.polygon_mm) >= 3
    ]
    polygons = [_poly(r.polygon_mm, frame) for r in rooms]
    keys = allocate_keys(
        [
            KeyRequest("r", "room", level, polygon_geometry(poly, params.key_round_mm), room.id)
            for room, poly in zip(rooms, polygons, strict=True)
        ]
    )
    out: list[RoomOut] = []
    compared = 0
    for room, poly, key in zip(rooms, polygons, keys, strict=True):
        out.append(
            RoomOut(
                key=key,
                level=level,
                tag=room.tag,
                type=room.type,
                area_m2=rnd(room.area_m2, 2),
                schedule_area_m2=room.schedule_area_m2,
                polygon=poly,
                status=RoomStatus(area_m2="observed", type=_room_type_status(room)),
                source=_ref(sheet.page, [room.id]),
            )
        )
        sched = room.schedule_area_m2
        if sched is not None and sched > 0:
            compared += 1
            diff_pct = abs(room.area_m2 - sched) / sched * 100.0
            if diff_pct > params.room_area_tol_pct:
                review.append(
                    ReviewItem(
                        code="room_area_vs_schedule",
                        severity="warning",
                        element=key,
                        source_ids=[room.id],
                        at=rnd_pt(centroid(poly), 1),
                        detail={
                            "area_m2": rnd(room.area_m2, 2),
                            "schedule_area_m2": rnd(sched, 2),
                            "diff_pct": rnd(diff_pct, 1),
                        },
                    )
                )
    return out, review, compared


def build_stacks(sheet: SheetIn, frame: Frame, level: str, params: Params) -> list[StackOut]:
    """Лестницы и лифты — контуром, без семейств."""
    items: list[tuple[StackKind, str, list[Pt], list[Pt] | None, Status]] = []
    for stair in sorted(sheet.stairs, key=lambda s: natural_key(s.id)):
        if len(stair.polygon_mm) >= 3:
            opening = (
                _poly(stair.slab_opening_mm, frame)
                if stair.slab_opening_mm is not None and len(stair.slab_opening_mm) >= 3
                else None
            )
            items.append(("stair", stair.id, _poly(stair.polygon_mm, frame), opening, "derived"))
    for room in sorted(sheet.rooms, key=lambda r: natural_key(r.id)):
        if room.type in ("lift", "possible lift") and len(room.polygon_mm) >= 3:
            kind: StackKind = "lift" if room.type == "lift" else "possible_lift"
            status: Status = "derived" if room.type == "lift" else "assumed"
            items.append((kind, room.id, _poly(room.polygon_mm, frame), None, status))
    keys = allocate_keys(
        [
            KeyRequest("k", kind, level, polygon_geometry(poly, params.key_round_mm), source_id)
            for kind, source_id, poly, _, _ in items
        ]
    )
    result: list[StackOut] = []
    for key, (kind, source_id, poly, opening, status) in zip(keys, items, strict=True):
        result.append(
            StackOut(
                key=key,
                level=level,
                kind=kind,
                polygon=poly,
                slab_opening=opening,
                status=status,
                source=_ref(sheet.page, [source_id]),
            )
        )
    return result
