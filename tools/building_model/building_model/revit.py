"""Адаптер `BuildingModel + подтверждение -> RevitPackage` (`quantor.revit_package.v0`).

Чистая функция без ввода-вывода: те же входы дают те же байты. Ничего не пропадает молча: элемент,
который нельзя выгрузить, попадает в `not_exported` с причиной, а по каждому виду
`exported + not_exported = total`. Статус `assumed` не выдаётся за `observed`: в `QTO_Status`
стоит самый слабый из статусов величин элемента.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from pydantic import JsonValue

from building_model.approval import NOISE_BLOCKER, ApprovalOut
from building_model.canonical import (
    BuildingModel,
    ColumnOut,
    OpeningOut,
    RoomOut,
    SlabOut,
    SourceRef,
    StackOut,
    Status,
    WallOut,
)
from building_model.geometry import Pt, dist, interior_point, signed_area
from building_model.revit_format import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    AdapterRef,
    AssumedParams,
    Assumptions,
    ColumnPkg,
    Coverage,
    ElementKind,
    FloorPkg,
    HolePkg,
    LevelPkg,
    LevelStatusOut,
    Manifest,
    NotExported,
    NotExportedReason,
    OpeningPkg,
    OriginRef,
    ReaderRef,
    ReviewSummary,
    RevitPackage,
    RoomPkg,
    StackPkg,
    SwingPkg,
    TenderRef,
    WallPkg,
    WallType,
)

# Эти два блокера снимает только подтверждение человека; остальные блокеры снять нельзя.
SCALE_BLOCKERS = frozenset({"scale_needs_human", "scale_not_confirmed"})
STRUCTURAL_ROLES = frozenset({"outer wall", "bearing wall", "thick wall"})
# Стена короче этого значения считается нулевой (после округления модели до 0,1 мм).
ZERO_LENGTH_MM = 1.0
# Запас на неточность осей: край проёма может выступать за конец стены-хозяина не больше этого.
OFFSET_TOLERANCE_MM = 50.0
WALL_TYPE_STEP_MM = 10
_STRENGTH: dict[str, int] = {"assumed": 0, "derived": 1, "observed": 2, "human": 3}
_PARAM_NAMES = (
    "door_height_mm",
    "window_sill_mm",
    "window_head_mm",
    "slab_thickness_mm",
    "level_height_mm",
)


class RevitRefusalError(ValueError):
    """Пакет собрать нельзя; сообщение перечисляет причины (коды и числа, без данных чертежа)."""


def weakest(statuses: Sequence[Status | None]) -> Status:
    """Самый слабый статус: observed > derived > assumed; human сильнее observed."""
    present: list[Status] = [s for s in statuses if s is not None]
    if not present:
        raise ValueError("у элемента нет ни одного статуса")
    return min(present, key=lambda s: _STRENGTH[s])


def source_text(refs: Sequence[SourceRef]) -> str:
    """`p51:W12,W13` (несколько записей через `|`): страница и id plangeom."""
    return "|".join(f"p{r.page}:{','.join(r.plangeom_ids)}" for r in refs)


def element_params(
    key: str, status: Status, refs: Sequence[SourceRef], extra: dict[str, str] | None = None
) -> dict[str, str]:
    base = {"QTO_Key": key, "QTO_Source": source_text(refs), "QTO_Status": status}
    return {**base, **(extra or {})}


def wall_type_class(thickness_mm: float) -> int:
    return math.floor(thickness_mm / WALL_TYPE_STEP_MM + 0.5) * WALL_TYPE_STEP_MM


def _degenerate(polygon: Sequence[Pt]) -> bool:
    return len(polygon) < 3 or abs(signed_area(polygon)) < 1e-9


def _first(polygon: Sequence[Pt]) -> Pt | None:
    return polygon[0] if polygon else None


def _number(params: dict[str, JsonValue], name: str) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"в модели нет числового параметра {name}")
    return float(value)


def _model_page(model: BuildingModel) -> int:
    sheet = model.stats.get("sheet")
    page = sheet.get("page") if isinstance(sheet, dict) else None
    if isinstance(page, bool) or not isinstance(page, int):
        raise ValueError("в модели нет номера страницы (stats.sheet.page)")
    return page


def refusal_reasons(
    model: BuildingModel, approval: ApprovalOut | None, model_sha256: str
) -> list[str]:
    reasons: list[str] = []
    if approval is not None:
        if approval.model_sha256 != model_sha256:
            reasons.append("sha256 модели не совпал с подтверждением")
        if approval.page != _model_page(model):
            reasons.append("номер страницы модели не совпал с подтверждением")
    # Принять человек может только openings_noise; любой другой код в акте игнорируется.
    accepted = (
        {NOISE_BLOCKER} & set(approval.accepted_blockers) if approval is not None else set[str]()
    )
    blockers: dict[str, int] = {}
    for item in model.review.items:
        if (
            item.severity == "blocker"
            and item.code not in SCALE_BLOCKERS
            and item.code not in accepted
        ):
            blockers[item.code] = blockers.get(item.code, 0) + 1
    if blockers:
        listed = ", ".join(f"{code} x{n}" for code, n in sorted(blockers.items()))
        reasons.append(f"есть блокеры, которые не снимает подтверждение: {listed}")
    unknown = sorted(lv.key for lv in model.levels if lv.elevation_mm is None)
    if unknown:
        reasons.append(f"уровень без отметки: {', '.join(unknown)}")
    return reasons


def _levels(model: BuildingModel) -> list[LevelPkg]:
    result: list[LevelPkg] = []
    for lv in model.levels:
        if lv.elevation_mm is None or lv.status.elevation_mm is None:
            raise ValueError("уровень без отметки должен быть отклонён раньше")
        result.append(
            LevelPkg(
                id=lv.key,
                floor=lv.floor,
                elevation_mm=lv.elevation_mm,
                height_mm=lv.height_mm,
                status=LevelStatusOut(
                    elevation_mm=lv.status.elevation_mm, height_mm=lv.status.height_mm
                ),
                instance_of=lv.instance_of,
            )
        )
    return sorted(result, key=lambda lv: (lv.elevation_mm, lv.id))


def _wall(wall: WallOut, height: float) -> WallPkg:
    thickness_class = wall_type_class(wall.thickness_mm)
    return WallPkg(
        id=wall.key,
        level=wall.level,
        start=wall.a,
        end=wall.b,
        height_mm=height,
        type=f"QTO-W-{thickness_class}",
        thickness_mm=wall.thickness_mm,
        structural=wall.role in STRUCTURAL_ROLES,
        params=element_params(
            wall.key,
            weakest([wall.status, wall.thickness_status]),
            wall.source,
            {"QTO_Role": wall.role},
        ),
    )


def _opening_status(op: OpeningOut) -> Status:
    s = op.status
    return weakest([s.width_mm, s.height_mm, s.sill_mm, s.offset_mm, s.swing])


def _opening_reason(
    op: OpeningOut, walls: dict[str, WallPkg], ambiguous: set[str]
) -> NotExportedReason | None:
    host = walls.get(op.host) if op.host is not None else None
    if host is None or op.offset_mm is None:
        return "ambiguous_host" if op.key in ambiguous else "no_host"
    length = dist(host.start, host.end)
    if op.width_mm > length + OFFSET_TOLERANCE_MM:
        return "wider_than_host"
    half = op.width_mm / 2.0
    if (
        op.offset_mm - half < -OFFSET_TOLERANCE_MM
        or op.offset_mm + half > length + OFFSET_TOLERANCE_MM
    ):
        return "offset_outside_host"
    return None


def _opening(op: OpeningOut, host: str, offset: float) -> OpeningPkg:
    swing = (
        None
        if op.swing is None
        else [SwingPkg(hinge_at=s.hinge_at, opens_to=s.opens_to) for s in op.swing]
    )
    return OpeningPkg(
        id=op.key,
        kind=op.kind,
        host=host,
        offset_mm=offset,
        width_mm=op.width_mm,
        height_mm=op.height_mm,
        sill_mm=op.sill_mm,
        swing=swing,
        at=op.at,
        params=element_params(op.key, _opening_status(op), op.source),
    )


def _floor(slab: SlabOut, holes: list[HolePkg]) -> FloorPkg:
    status = weakest(
        [slab.status.outline, slab.status.thickness_mm, *(h.status for h in slab.holes)]
    )
    return FloorPkg(
        id=slab.key,
        level=slab.level,
        boundary=slab.polygon,
        holes=holes,
        thickness_mm=slab.thickness_mm,
        params=element_params(slab.key, status, slab.source),
    )


def _column(col: ColumnOut, height: float) -> ColumnPkg:
    return ColumnPkg(
        id=col.key,
        level=col.level,
        outline=col.polygon,
        height_mm=height,
        params=element_params(col.key, col.status, col.source),
    )


def _stack(stack: StackOut) -> StackPkg:
    return StackPkg(
        id=stack.key,
        level=stack.level,
        kind=stack.kind,
        outline=stack.polygon,
        slab_opening=stack.slab_opening,
        params=element_params(stack.key, stack.status, stack.source),
    )


def _room(room: RoomOut, point: Pt) -> RoomPkg:
    status = weakest([room.status.area_m2, room.status.type])
    return RoomPkg(
        id=room.key,
        level=room.level,
        tag=room.tag,
        type=room.type,
        area_m2=room.area_m2,
        boundary=room.polygon,
        point=point,
        params=element_params(room.key, status, room.source),
    )


def _review_summary(model: BuildingModel) -> ReviewSummary:
    counts: dict[str, dict[str, int]] = {"blocker": {}, "warning": {}, "info": {}}
    for item in model.review.items:
        bucket = counts[item.severity]
        bucket[item.code] = bucket.get(item.code, 0) + 1
    return ReviewSummary(
        blocker=dict(sorted(counts["blocker"].items())),
        warning=dict(sorted(counts["warning"].items())),
        info=dict(sorted(counts["info"].items())),
    )


class _HasParams(Protocol):
    @property
    def params(self) -> dict[str, str]: ...


def _count_assumed(items: Sequence[_HasParams]) -> int:
    return sum(1 for item in items if item.params.get("QTO_Status") == "assumed")


def _wall_types(walls: Sequence[WallPkg]) -> list[WallType]:
    """Заглушка до каталога типов шаблона (этап M6): тип по толщине, округлённой до 10 мм."""
    counts: dict[int, int] = {}
    for w in walls:
        cls = wall_type_class(w.thickness_mm)
        counts[cls] = counts.get(cls, 0) + 1
    return [
        WallType(id=f"QTO-W-{cls}", thickness_mm=float(cls), count=n)
        for cls, n in sorted(counts.items())
    ]


def build_package(
    model: BuildingModel, approval: ApprovalOut | None, model_sha256: str
) -> RevitPackage:
    """Пакет для Revit. Отказ (`RevitRefusalError`) перечисляет все причины сразу."""
    reasons = refusal_reasons(model, approval, model_sha256)
    if reasons:
        raise RevitRefusalError("; ".join(reasons))
    levels = _levels(model)
    heights = {lv.id: lv.height_mm for lv in levels}
    skipped: list[NotExported] = []

    def skip(key: str, kind: ElementKind, reason: NotExportedReason, at: Pt | None) -> None:
        skipped.append(NotExported(key=key, kind=kind, reason=reason, at=at))

    walls: list[WallPkg] = []
    for w in sorted(model.walls, key=lambda x: x.key):
        if dist(w.a, w.b) < ZERO_LENGTH_MM:
            skip(w.key, "wall", "zero_length_wall", w.a)
        else:
            walls.append(_wall(w, heights[w.level]))
    by_key = {w.id: w for w in walls}

    ambiguous = {
        i.element for i in model.review.items if i.code == "opening_ambiguous_host" and i.element
    }
    openings: list[OpeningPkg] = []
    for op in sorted(model.openings, key=lambda x: x.key):
        reason = _opening_reason(op, by_key, ambiguous)
        if reason is not None or op.host is None or op.offset_mm is None:
            skip(op.key, "opening", reason or "no_host", op.at)
        else:
            openings.append(_opening(op, op.host, op.offset_mm))

    floors: list[FloorPkg] = []
    hole_total = hole_ok = 0
    for slab in sorted(model.slabs, key=lambda x: x.key):
        holes_ok: list[HolePkg] = []
        floor_ok = not _degenerate(slab.polygon)
        for index, hole in enumerate(slab.holes):
            hole_total += 1
            hole_key = f"{slab.key}#hole{index}"
            if not floor_ok:
                skip(hole_key, "floor_hole", "no_host", _first(hole.polygon))
            elif _degenerate(hole.polygon):
                skip(hole_key, "floor_hole", "degenerate_polygon", _first(hole.polygon))
            else:
                hole_ok += 1
                holes_ok.append(HolePkg(kind=hole.kind, boundary=hole.polygon))
        if floor_ok:
            floors.append(_floor(slab, holes_ok))
        else:
            skip(slab.key, "floor", "degenerate_polygon", _first(slab.polygon))

    columns: list[ColumnPkg] = []
    for col in sorted(model.columns, key=lambda x: x.key):
        if _degenerate(col.polygon):
            skip(col.key, "column", "degenerate_polygon", _first(col.polygon))
        else:
            columns.append(_column(col, heights[col.level]))

    stacks: list[StackPkg] = []
    for stack in sorted(model.stacks, key=lambda x: x.key):
        broken = _degenerate(stack.polygon) or (
            stack.slab_opening is not None and _degenerate(stack.slab_opening)
        )
        if broken:
            skip(stack.key, "stack", "degenerate_polygon", _first(stack.polygon))
        else:
            stacks.append(_stack(stack))

    rooms: list[RoomPkg] = []
    for room in sorted(model.rooms, key=lambda x: x.key):
        point = None if _degenerate(room.polygon) else interior_point(room.polygon)
        if point is None:
            skip(room.key, "room", "degenerate_polygon", _first(room.polygon))
        else:
            rooms.append(_room(room, point))

    totals: dict[str, tuple[int, int]] = {
        "columns": (len(model.columns), len(columns)),
        "floor_holes": (hole_total, hole_ok),
        "floors": (len(model.slabs), len(floors)),
        "openings": (len(model.openings), len(openings)),
        "rooms": (len(model.rooms), len(rooms)),
        "stacks": (len(model.stacks), len(stacks)),
        "walls": (len(model.walls), len(walls)),
    }
    coverage = {
        name: Coverage(total=total, exported=ok, not_exported=total - ok)
        for name, (total, ok) in totals.items()
    }
    assumed = {
        "columns": _count_assumed(columns),
        "floors": _count_assumed(floors),
        "levels": sum(
            1 for lv in levels if "assumed" in (lv.status.elevation_mm, lv.status.height_mm)
        ),
        "openings": _count_assumed(openings),
        "rooms": _count_assumed(rooms),
        "stacks": _count_assumed(stacks),
        "walls": _count_assumed(walls),
    }
    values = {name: _number(model.params, name) for name in _PARAM_NAMES}
    manifest = Manifest(
        tender=TenderRef(
            number=model.tender.number,
            version=model.tender.version,
            manifest_sha256=model.tender.manifest_sha256,
        ),
        reader=ReaderRef(
            name=model.reader.name, version=model.reader.version, normalizer=model.reader.normalizer
        ),
        adapter=AdapterRef(name=ADAPTER_NAME, version=ADAPTER_VERSION),
        model_sha256=model_sha256,
        page=approval.page if approval is not None else _model_page(model),
        approval=approval,
        scale_status="human" if approval is not None else "candidate",
        origin=OriginRef(axes=model.origin.axes, source=model.origin.source),
        coverage=coverage,
        review_summary=_review_summary(model),
        assumptions=Assumptions(params=AssumedParams(**values), assumed_elements=assumed),
    )
    return RevitPackage(
        manifest=manifest,
        levels=levels,
        wall_types=_wall_types(walls),
        walls=walls,
        openings=openings,
        floors=floors,
        columns=columns,
        stacks=stacks,
        rooms=rooms,
        not_exported=sorted(skipped, key=lambda n: (n.kind, n.key, n.reason)),
    )
