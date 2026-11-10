"""Приборы отопления квартиры: отапливаемые комнаты и приборы на модулях остекления."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from cad_mep import facade
from cad_mep.issues import Issue
from cad_mep.labels import Labels
from cad_mep.params import Params
from cad_mep.rooms import Apartment, Model
from cad_mep.route import RouteGrid

Pt = tuple[float, float]

# почему у отапливаемой комнаты нет прибора
NO_DEVICE_REASON = {
    "not_on_plan": "марки на плане нет, по площади помещение не найдено",
    "no_outer_wall": "нет наружной стены",
    "no_glazing": "на наружной стене нет участка для прибора",
    "glazing_of_neighbour": "своего остекления нет, приборы общего помещения отнесены к соседним",
    "no_node": "у наружной стены нет проходимой точки для прибора",
    "unreachable": "путь от коллектора до прибора не найден",
}


@dataclass
class Device:
    room_id: str
    xy: Pt
    node: int
    span_m: float  # длина остекления (или стены), приходящаяся на прибор
    assumed: bool  # число приборов — по шагу модулей, а не по простенкам
    path_m: float | None = None  # по дереву лучей от коллектора


@dataclass
class HeatRoom:
    apt: int
    room_id: str
    name: str
    comp: int | None
    placed_by: str  # label — марка на плане, area — по площади, none — марки нет
    heating: str  # listed — по списку названий, assumed — название неизвестно, есть остекление
    status: str  # ok либо ключ NO_DEVICE_REASON
    facade_m: float | None = None  # наружная стена помещения (общая для слитых комнат)
    devices: list[Device] = field(default_factory=list)


@dataclass
class _Owner:
    room_id: str
    name: str
    known: bool  # название в списке отапливаемых
    by_area: bool
    points: list[Pt] = field(default_factory=list)


def heat_class(name: str, params: Params) -> str:
    """heated | unheated | unknown — по началу названия из экспликации."""
    low = name.strip().lower()
    if any(low.startswith(w) for w in params.texts("heated_room_words")):
        return "heated"
    if any(low.startswith(w) for w in params.texts("unheated_room_words")):
        return "unheated"
    return "unknown"


def _owners(m: Model, labels: Labels, cid: int, params: Params) -> list[_Owner]:
    """Комнаты помещения, которым может принадлежать наружная стена: всё, кроме неотапливаемых."""
    comp = m.comps[cid]
    out: dict[str, _Owner] = {}
    for rl in comp.room_labels:
        row = labels.expl.get(rl.room_id)
        cls = heat_class(row.name if row else "", params)
        if cls == "unheated":
            continue
        owner = out.setdefault(
            rl.room_id, _Owner(rl.room_id, row.name if row else "", cls == "heated", rl.assigned)
        )
        owner.points.append(rl.word.c)
    if not comp.room_labels:
        out[f"#{cid}"] = _Owner(f"#{cid}", "", False, False, [comp.centroid])
    return [out[k] for k in sorted(out)]


def place(
    m: Model, labels: Labels, rg: RouteGrid, prof: facade.Profile, params: Params, ap: Apartment
) -> tuple[list[HeatRoom], list[Issue]]:
    """Отапливаемые комнаты квартиры и их приборы (без лучей).

    Комнаты берутся из экспликации (даже если на плане их нет) и из марок на плане. В помещении
    из нескольких комнат прибор относится к ближайшей марке отапливаемой комнаты.
    """
    room_re = re.compile(params.text("room_id_regex"))
    radius = params.num("device_node_radius_mm")
    module = params.num("glazing_module_mm")
    rooms: dict[str, HeatRoom] = {}
    issues: list[Issue] = []
    for rid in sorted(labels.expl):
        mm = room_re.match(rid)
        if (
            mm
            and mm.group(3) == "/"
            and (mm.group(1), int(mm.group(2))) == (ap.section, ap.k)
            and heat_class(labels.expl[rid].name, params) == "heated"
        ):
            rooms[rid] = HeatRoom(
                ap.idx, rid, labels.expl[rid].name, None, "none", "listed", "not_on_plan"
            )
    for cid in ap.comps:
        owners = _owners(m, labels, cid, params)
        if not owners:
            continue
        runs = facade.comp_runs(m, prof, cid, params)
        spots = facade.place(m, prof, runs, params)
        wall_m = round(facade.facade_length(prof, runs) / 1000, 2) if runs else None
        empty = "glazing_of_neighbour" if spots else ("no_glazing" if runs else "no_outer_wall")
        for o in owners:
            if o.known:
                room = rooms.setdefault(
                    o.room_id, HeatRoom(ap.idx, o.room_id, o.name, None, "none", "listed", empty)
                )
                if not room.devices:
                    room.comp, room.status, room.facade_m = cid, empty, wall_m
                    room.placed_by = "area" if o.by_area else "label"
        taken: set[int] = set()
        assumed = 0
        for spot in spots:
            owner = min(owners, key=lambda o: min(math.dist(spot.xy, p) for p in o.points))
            node = rg.node(spot.xy[0], spot.xy[1], r_mm=radius, comp=cid)
            if node is None or node in taken:
                if node is None and owner.known and not rooms[owner.room_id].devices:
                    rooms[owner.room_id].status = "no_node"
                continue
            taken.add(node)
            if owner.room_id not in rooms:  # название неизвестно, но остекление есть
                marked = "label" if m.comps[cid].room_labels else "none"
                rooms[owner.room_id] = HeatRoom(
                    ap.idx, owner.room_id, owner.name, cid, marked, "assumed", "ok", wall_m
                )
                shown = f"«{owner.name}»" if owner.name else "без названия"
                issues.append(
                    Issue(
                        "room_heating_assumed",
                        f"{ap.number}: {owner.room_id} {shown} — названия нет в списках "
                        "отапливаемых и неотапливаемых, есть наружное остекление: принята "
                        "отапливаемой",
                        ap.number,
                    )
                )
            room = rooms[owner.room_id]
            room.status = "ok"
            room.comp = cid
            xy = (float(rg.xy[node][0]), float(rg.xy[node][1]))
            room.devices.append(
                Device(owner.room_id, xy, node, round(spot.span_mm / 1000, 2), spot.assumed)
            )
            assumed += spot.assumed
        if assumed:
            names = ", ".join(o.room_id for o in owners)
            issues.append(
                Issue(
                    "glazing_modules_assumed",
                    f"{ap.number}: {names} — модули остекления на наружной стене не определены "
                    f"(нет простенков или остекления): приборов {assumed}, поставлены по шагу "
                    f"{module:.0f} мм (стена {wall_m} м)",
                    ap.number,
                )
            )
    return list(rooms.values()), issues
