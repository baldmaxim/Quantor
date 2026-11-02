"""Сборка модели одного листа: чистая функция над разобранным листом, без ввода-вывода."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from building_model.canonical import (
    BuildingModel,
    OpeningOut,
    OpeningStatus,
    OriginOut,
    ReaderOut,
    ReviewItem,
    ReviewOut,
    Severity,
    SourceRef,
    SwingOut,
    TenderOut,
    WallOut,
)
from building_model.constants import NORMALIZER_VERSION, SUPPORTED_PLANGEOM_VERSION
from building_model.coords import choose_origin
from building_model.elements import HostResult, MergedWall, natural_key
from building_model.floors import (
    build_columns,
    build_levels,
    build_rooms,
    build_slabs,
    build_stacks,
)
from building_model.geometry import Pt, rnd, rnd_pt
from building_model.keys import (
    KeyRequest,
    allocate_keys,
    point_geometry,
    wall_geometry,
)
from building_model.modelstats import build_stats
from building_model.openings import assign_hosts, prepare_openings
from building_model.params import Params
from building_model.reader import Document, Excluded, SheetIn, read_sheet
from building_model.walls import WallsResult, build_walls

_SEVERITY_RANK: dict[str, int] = {"blocker": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class TenderArgs:
    number: str | None = None
    version: int | None = None
    manifest_sha256: str | None = None


def _walls_out(
    result: WallsResult, level: str, page: int, params: Params
) -> tuple[list[WallOut], list[str]]:
    step = params.key_round_mm
    keys = allocate_keys(
        [
            KeyRequest(
                "w",
                "wall",
                level,
                wall_geometry(w.a, w.b, step),
                repr((rnd_pt(w.a, 1), rnd_pt(w.b, 1), rnd(w.thickness), w.wall_ids)),
            )
            for w in result.walls
        ]
    )
    out = [
        WallOut(
            key=key,
            level=level,
            a=rnd_pt(w.a, 1),
            b=rnd_pt(w.b, 1),
            thickness_mm=rnd(w.thickness),
            role=w.role or "unknown",
            role_status="derived",
            type_ref=None,
            status="observed" if w.pieces == 1 and w.axis_source == "segments" else "derived",
            thickness_status="observed" if w.axis_source == "segments" else "derived",
            axis_source=w.axis_source,
            pieces=w.pieces,
            bridged_openings=list(w.bridged_openings),
            source=[SourceRef(page=page, plangeom_ids=list(w.wall_ids))],
        )
        for key, w in zip(keys, result.walls, strict=True)
    ]
    return out, keys


def _opening_height(kind: str, params: Params) -> tuple[float | None, float | None]:
    """(высота, подоконник): дверь — параметр двери, окно и пустой проём — параметры окна."""
    if kind == "door":
        return (params.door_height_mm, None)
    return (params.window_head_mm - params.window_sill_mm, params.window_sill_mm)


def _openings_out(
    hosts: Sequence[HostResult],
    wall_keys: Sequence[str],
    walls: Sequence[MergedWall],
    level: str,
    page: int,
    params: Params,
) -> tuple[list[OpeningOut], list[ReviewItem], dict[str, JsonValue]]:
    step = params.key_round_mm
    keys = allocate_keys(
        [
            KeyRequest(
                "o",
                h.draft.kind,
                level,
                point_geometry(h.midpoint, h.draft.width, step),
                repr(h.draft.ids),
            )
            for h in hosts
        ]
    )
    out: list[OpeningOut] = []
    review: list[ReviewItem] = []
    counts: dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    compared = matched = plangeom_null = 0
    for key, h in zip(keys, hosts, strict=True):
        draft = h.draft
        bump(f"{draft.kind}_total")
        height, sill = _opening_height(draft.kind, params)
        hosted = h.status == "hosted" and h.wall_index is not None
        host_key = wall_keys[h.wall_index] if hosted and h.wall_index is not None else None
        bump(f"{draft.kind}_{h.status}")
        if hosted and h.wall_index is not None and draft.kind == "door":
            wall_ids = set(walls[h.wall_index].wall_ids)
            declared = [leaf.plangeom_host for leaf in draft.leaves if leaf.plangeom_host]
            if declared:
                compared += 1
                if wall_ids.intersection(declared):
                    matched += 1
            else:
                plangeom_null += 1
        swing = (
            [SwingOut(hinge_at=s.hinge_at, opens_to=s.opens_to) for s in h.swings]
            if h.swings
            else None
        )
        out.append(
            OpeningOut(
                key=key,
                kind=draft.kind,
                level=level,
                host=host_key,
                offset_mm=None if h.offset_mm is None else rnd(h.offset_mm),
                width_mm=rnd(draft.width),
                height_mm=height,
                sill_mm=sill,
                swing=swing,
                at=rnd_pt(h.midpoint, 1),
                span=(rnd_pt(h.span[0], 1), rnd_pt(h.span[1], 1)),
                status=OpeningStatus(
                    width_mm="observed",
                    height_mm="assumed",
                    sill_mm="assumed" if sill is not None else None,
                    offset_mm="derived" if hosted else None,
                    swing="derived" if swing else None,
                ),
                source=[SourceRef(page=page, plangeom_ids=list(draft.ids))],
            )
        )
        base_detail: dict[str, float | int | str | None] = {"kind": draft.kind}
        if h.status != "hosted":
            code = "opening_no_host" if h.status == "no_host" else "opening_ambiguous_host"
            base_detail["candidates"] = h.candidates
            review.append(_item(code, "warning", key, draft.ids, h.midpoint, base_detail))
        if draft.kind == "door" and draft.gap_mm is not None:
            diff = abs(draft.gap_mm - draft.width)
            if diff > params.door_gap_warn_mm:
                detail: dict[str, float | int | str | None] = {
                    "opening_mm": rnd(draft.width),
                    "gap_mm": rnd(draft.gap_mm),
                    "diff_mm": rnd(diff),
                }
                review.append(
                    _item("door_leaf_vs_gap", "warning", key, draft.ids, h.midpoint, detail)
                )
        if draft.pair_missing:
            review.append(
                _item("door_pair_missing", "warning", key, draft.ids, h.midpoint, {"leaves": 2})
            )
    out.sort(key=lambda o: o.key)
    stats: dict[str, JsonValue] = dict(sorted(counts.items()))
    stats["door_host_compared_with_plangeom"] = compared
    stats["door_host_matches_plangeom"] = matched
    stats["door_host_plangeom_null"] = plangeom_null
    return out, review, stats


def _item(
    code: str,
    severity: Severity,
    element: str | None,
    source_ids: Sequence[str],
    at: Pt | None,
    detail: dict[str, float | int | str | None],
) -> ReviewItem:
    return ReviewItem(
        code=code,
        severity=severity,
        element=element,
        source_ids=sorted(source_ids, key=natural_key),
        at=None if at is None else rnd_pt(at, 1),
        detail=detail,
    )


def _wall_review(result: WallsResult, wall_keys: Sequence[str], params: Params) -> list[ReviewItem]:
    review: list[ReviewItem] = []
    for r in result.rejected:
        review.append(
            ReviewItem(
                code=r.code,
                severity="info",
                element=None,
                source_ids=[r.piece.wall_id],
                at=None,
                detail={
                    "thickness_mm": rnd(r.piece.thickness),
                    "length_mm": rnd(r.piece.length),
                    "outline": int(r.piece.outline),
                },
                a=rnd_pt(r.piece.a, 1),
                b=rnd_pt(r.piece.b, 1),
            )
        )
    codes = {
        "not_rectangle": "wall_no_axis",
        "compact": "wall_no_axis_compact",
        "duplicate": "wall_axis_duplicate",
    }
    for n in result.outline_outcomes:
        if n.outcome not in codes:
            continue
        review.append(
            ReviewItem(
                code=codes[n.outcome],
                severity="info",
                element=None,
                source_ids=[n.wall_id],
                at=None,
                detail={"area_m2": rnd(n.area_m2, 2), "length_mm": rnd(n.length_mm)},
                a=None if n.a is None else rnd_pt(n.a, 1),
                b=None if n.b is None else rnd_pt(n.b, 1),
            )
        )
    for d in result.dangling:
        wall = result.walls[d.wall_index]
        review.append(
            _item(
                "wall_dangling_end",
                "info" if d.near_opening else "warning",
                wall_keys[d.wall_index],
                wall.wall_ids,
                d.point,
                {"end": d.end, "near_opening": int(d.near_opening)},
            )
        )
    return review


def _scale_review(sheet: SheetIn, has_axes: bool) -> list[ReviewItem]:
    review: list[ReviewItem] = []
    if not sheet.scale.confident or sheet.scale.disagrees_with_printed:
        review.append(
            _item(
                "scale_not_confirmed",
                "blocker",
                None,
                [],
                None,
                {
                    "confident": int(sheet.scale.confident),
                    "disagrees_with_printed": int(sheet.scale.disagrees_with_printed),
                    "method": sheet.scale.method,
                },
            )
        )
    # В M1 подтверждать масштаб некому: автоматического утверждения нет.
    review.append(
        _item("scale_needs_human", "blocker", None, [], None, {"mm_per_pt": sheet.scale.mm_per_pt})
    )
    if not has_axes:
        review.append(_item("no_axes_origin", "blocker", None, [], None, {}))
    return review


def build_sheet_model(
    sheet: SheetIn,
    neighbors_mm: Sequence[float],
    building: int | None,
    tender: TenderArgs,
    params: Params,
) -> BuildingModel:
    mm_per_pt = sheet.scale.mm_per_pt
    corner: Pt = (0.0, sheet.source.height_pt * mm_per_pt if mm_per_pt else 0.0)
    frame = choose_origin(sheet.axes or [], params, corner)
    drafts = prepare_openings(sheet, frame, params)
    walls_result = build_walls(sheet, frame, drafts, params)
    hosts = assign_hosts(drafts, walls_result.walls, params)
    levels = build_levels(sheet, neighbors_mm, params)
    level = levels.carrier
    page = sheet.page

    walls_out, wall_keys = _walls_out(walls_result, level, page, params)
    openings, opening_review, opening_stats = _openings_out(
        hosts, wall_keys, walls_result.walls, level, page, params
    )
    slabs, slab_review = build_slabs(sheet, frame, level, params)
    rooms, room_review, rooms_compared = build_rooms(sheet, frame, level, params)
    stacks = build_stacks(sheet, frame, level, params)
    columns = build_columns(walls_result.columns, level, page, params)

    items = [
        *_scale_review(sheet, frame.has_axes_origin),
        *levels.review,
        *_wall_review(walls_result, wall_keys, params),
        *opening_review,
        *slab_review,
        *room_review,
    ]
    items.sort(
        key=lambda i: (
            _SEVERITY_RANK[i.severity],
            i.code,
            i.element or "",
            i.at or (0.0, 0.0),
            i.a or (0.0, 0.0),
            i.source_ids,
        )
    )
    counts = {s: sum(1 for i in items if i.severity == s) for s in _SEVERITY_RANK}

    stats = build_stats(
        sheet,
        building,
        params,
        walls_result,
        walls_out,
        wall_keys,
        opening_stats,
        len(rooms),
        rooms_compared,
        counts,
        items,
        len(slabs),
        len(stacks),
        len(columns),
    )
    return BuildingModel(
        tender=TenderOut(
            number=tender.number, version=tender.version, manifest_sha256=tender.manifest_sha256
        ),
        reader=ReaderOut(
            name="plangeom", version=SUPPORTED_PLANGEOM_VERSION, normalizer=NORMALIZER_VERSION
        ),
        origin=OriginOut(
            axes=None if frame.axes is None else list(frame.axes),
            sheet_mm=rnd_pt(frame.origin_sheet, 1),
            source="axes" if frame.has_axes_origin else "sheet_corner",
        ),
        levels=levels.levels,
        walls=walls_out,
        openings=openings,
        slabs=slabs,
        rooms=rooms,
        stacks=stacks,
        review=ReviewOut(
            blockers=counts["blocker"], warnings=counts["warning"], info=counts["info"], items=items
        ),
        columns=columns,
        params=json.loads(params.model_dump_json()),
        stats=stats,
    )


def build_model(
    doc: Document, page: int, tender: TenderArgs, params: Params | None = None
) -> BuildingModel:
    """Модель одного листа комплекта; исключённый лист (не план, плохой verdict) — ValueError."""
    used = params or Params()
    sheet = read_sheet(doc, page)
    if isinstance(sheet, Excluded):
        raise ValueError(f"страница {page} исключена из модели: {sheet.reason}")
    return build_sheet_model(
        sheet, doc.known_elevations_mm(page), doc.building_of(page), tender, used
    )


def dumps_model(model: BuildingModel) -> str:
    """Детерминированная сериализация: порядок полей фиксирован, времени запуска нет."""
    data = model.model_dump(mode="json", by_alias=True)
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"
