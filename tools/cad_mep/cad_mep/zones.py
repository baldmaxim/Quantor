"""Зоны помещений квартир по плану этажа: PDF + DXF вида + калибровка -> zones.json.

Каждой марке экспликации «секция-квартира/комната» ставится в соответствие замкнутый
многоугольник на плане. Основа — помещения детектора (cad_mep.rooms) на сетке 25 мм; они
уточняются на тонком растре с учётом реальных препятствий (заливки и тёмные штрихи PDF), слитые
помещения делятся тонкими чёрными линиями плана, затем области растут до препятствий.
Результат — кандидат: площадь многоугольника только сверяется с экспликацией.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon

from cad_mep import pdfsrc
from cad_mep import zones_const as zc
from cad_mep.errors import EXIT_NO_ROUTES, MepError
from cad_mep.labels import ExplRow, RoomLabel
from cad_mep.params import Params
from cad_mep.parking import find_parking
from cad_mep.plan import PlanInput, PlanModel, build_plan_model, open_plan, read_scale
from cad_mep.version import GENERATOR_VERSION
from cad_mep.zones_grow import (
    absorb_residual,
    assign_pockets,
    collect_pockets,
    grow,
    residual_notes,
)
from cad_mep.zones_lines import (
    axis_mask,
    boundary_lines,
    door_arc_mask,
    label_frame_mask,
    localize,
)
from cad_mep.zones_poly import (
    densify_arcs,
    fix_invalid,
    norm_area_m2,
    remove_overlaps,
    seed_polygons,
    simplify_all,
    simplify_poly,
    to_norm,
)
from cad_mep.zones_raster import Field, build_obstacles, start_field
from cad_mep.zones_split import Splitter

SCHEMA = "quantor.cad_mep.zones.v1"
KIND = "room_apartment"


@dataclass(frozen=True)
class ZoneArgs:
    pdf: Path
    page_index: int
    view_dxf: Path
    scale: Path
    preview: Path
    params: Path | None
    out: Path


@dataclass
class _Zone:
    apartment_no: str
    room_mark: str
    name: str
    expl_area_m2: float
    poly_area_m2: float
    points: list[list[float]]
    notes: list[str]

    def as_json(self) -> dict[str, object]:
        return {
            "kind": KIND,
            "apartment_no": self.apartment_no,
            "room_mark": self.room_mark,
            "name": self.name,
            "expl_area_m2": self.expl_area_m2,
            "poly_area_m2": self.poly_area_m2,
            "points": self.points,
            "notes": self.notes,
        }


@dataclass
class _Mark:
    """Марка квартирной комнаты из экспликации."""

    room_id: str
    section: str
    k: int
    order: tuple[int, int, int]
    row: ExplRow


def _validate(args: ZoneArgs) -> None:
    for p, code in ((args.pdf, "pdf_unreadable"), (args.view_dxf, "dxf_unreadable")):
        if not p.is_file():
            raise MepError(code, f"нет файла {p.name}")


def _apartment_marks(pm: PlanModel, params: Params) -> tuple[list[_Mark], list[str]]:
    """Марки квартир (разделитель «/») из экспликации и марки плана, которых в ней нет."""
    room_re = re.compile(params.text("room_id_regex"))
    marks: list[_Mark] = []
    for rid, row in pm.lab.expl.items():
        m = room_re.match(rid)
        if m is None or m.group(3) != "/":
            continue
        order = (int(m.group(1)), int(m.group(2)), int(m.group(4)))
        marks.append(_Mark(rid, m.group(1), int(m.group(2)), order, row))
    marks.sort(key=lambda mk: mk.order)
    known = {mk.room_id for mk in marks}
    extra = sorted(
        {rl.room_id for rl in pm.lab.rooms if not rl.mop and rl.room_id not in known},
        key=lambda r: [int(x) for x in re.findall(r"\d+", r)],
    )
    return marks, extra


def _build_field(
    plan: PlanInput, pm: PlanModel, args: ZoneArgs
) -> tuple[Field, Splitter, dict[int, str]]:
    """Тонкий растр: препятствия, маски, разделение слитых помещений, рост и добор карманов.

    Третий элемент — замечания о присоединённых карманах по меткам областей.
    """
    model = pm.model
    strokes = pdfsrc.read_strokes(args.pdf, args.page_index, plan.zone, zc.DARK_MAX_CHANNEL)
    seg = localize(strokes, plan.frame)
    boxes = [rl.word.pt for rl in pm.lab.rooms if rl.word.pt != (0.0, 0.0, 0.0, 0.0)]
    in_frame = label_frame_mask(strokes.seg, boxes)
    axes = axis_mask(seg)
    arcs = door_arc_mask(seg, pm.doors)
    lines = boundary_lines(seg, in_frame | axes)

    step = model.gr.step
    k = max(1, round(step / zc.RASTER_MM))
    f = step / k
    ny, nx = model.lab.shape[0] * k, model.lab.shape[1] * k
    fill_pts = [pts for pts, col in strokes.fills if col != (1.0, 1.0, 1.0)]
    fill_local = [[plan.frame.pt_to_local(x, y) for x, y in pts] for pts in fill_pts]
    obst, fill = build_obstacles(f, nx, ny, pm.wall_polys, fill_local, seg, arcs | in_frame | axes)
    fld = start_field(f, k, model.lab, obst, fill)
    comp_marks: dict[int, list[RoomLabel]] = {
        c.id: list(c.room_labels)
        for c in model.comps.values()
        if c.kind in ("room", "mop") and c.room_labels
    }
    sp = Splitter(fld, model, pm.lab.expl, lines, pm.doors, comp_marks)
    sp.run()
    pockets = collect_pockets(fld, pm.doors, sp.label_apt)
    grow(fld, zc.GROW_LIMIT_MM)
    assign_pockets(fld, pockets)
    return fld, sp, residual_notes(absorb_residual(fld))


def _apartment_number(plan_model: PlanModel, mark: _Mark) -> str:
    for ap in plan_model.model.apts.values():
        if ap.section == mark.section and ap.k == mark.k:
            return ap.number.removeprefix("Кв ")
    return f"{mark.section}-{mark.k}"


def _point_limit(
    poly: Polygon, plan: PlanInput, width_pt: float, height_pt: float
) -> tuple[Polygon, list[list[float]]]:
    """Контур с числом вершин не больше MAX_POINTS (допуск упрощения растёт)."""
    norm = to_norm(poly, plan.frame, width_pt, height_pt)
    tol = zc.SIMPLIFY_MM
    while len(norm) > zc.MAX_POINTS:
        tol *= zc.SIMPLIFY_GROWTH
        poly = simplify_poly(poly, tol)
        norm = to_norm(poly, plan.frame, width_pt, height_pt)
    return poly, norm


@dataclass
class _Shapes:
    polys: dict[int, Polygon]
    region_notes: dict[int, list[str]]
    arc_notes: dict[int, str]
    absorbed_notes: dict[int, str]


def _shapes(sp: Splitter, fld: Field, absorbed_notes: dict[int, str]) -> _Shapes:
    """Многоугольники областей: контур, упрощение, дуги остекления, без перекрытий."""
    raw, notes = seed_polygons(fld, sorted(set(sp.mark_seed.values())))
    final = simplify_all(raw, notes)
    arc_notes: dict[int, str] = {}
    for sid in list(final):
        q, added = densify_arcs(final[sid])
        if added:
            final[sid] = q
            arc_notes[sid] = (
                f"дуга остекления: добавлено вершин {added} (шаг <= {zc.ARC_STEP_MM:.0f} мм)"
            )
    remove_overlaps(final)
    return _Shapes(final, notes, arc_notes, absorbed_notes)


def _zone_notes(sp: Splitter, sid: int, mk: _Mark, group: list[str], shapes: _Shapes) -> list[str]:
    notes = list(shapes.region_notes.get(sid, []))
    if sid in shapes.arc_notes:
        notes.append(shapes.arc_notes[sid])
    if sid in shapes.absorbed_notes:
        notes.append(shapes.absorbed_notes[sid])
    cid = next(
        (c for c, rls in sp.comp_marks.items() if any(r.room_id == mk.room_id for r in rls)), None
    )
    comp_notes = sp.comp_notes.get(cid, []) if cid is not None else []
    return notes + (comp_notes if len(group) > 1 else [n for n in comp_notes if mk.room_id in n])


def extract_zones(args: ZoneArgs) -> dict[str, object]:
    """Строит zones.json (словарь) по плану страницы."""
    _validate(args)
    try:
        plan = open_plan(
            args.pdf, args.page_index, args.view_dxf, args.scale, args.preview, args.params
        )
    except MepError as exc:
        if exc.code != "frame_mismatch":
            raise
        # повёрнутый лист и т. п.: квартиры без привязки рамки не строим, места — по странице
        scale = read_scale(args.scale)
        parking = find_parking(args.pdf, args.page_index, None, scale)
        if not parking["parking_spaces"]:
            raise
        return _output(args, scale, [], [], parking)
    pm = build_plan_model(plan)
    marks, extra = _apartment_marks(pm, plan.params)
    parking = find_parking(args.pdf, args.page_index, plan.zone, plan.frame.scale)
    if not marks:
        if not parking["parking_spaces"]:
            raise MepError(
                "no_explication",
                "в экспликации листа нет комнат квартир: зоны сопоставить не с чем",
                EXIT_NO_ROUTES,
            )
        return _output(args, plan.frame.scale, [], [], parking)  # лист автостоянки: только места
    fld, sp, absorbed_notes = _build_field(plan, pm, args)
    shapes = _shapes(sp, fld, absorbed_notes)
    polys = shapes.polys
    width_pt, height_pt, scale = plan.page.width, plan.page.height, plan.frame.scale
    by_id = {mk.room_id: mk for mk in marks}
    seed_marks: dict[int, list[str]] = {}
    for m, seed in sp.mark_seed.items():
        seed_marks.setdefault(seed, []).append(m)

    zones: list[_Zone] = []
    unmatched: list[dict[str, object]] = []
    for mk in marks:
        sid = sp.mark_seed.get(mk.room_id)
        if sid is None or sid not in polys:
            unmatched.append(_unmatched(mk, "полигон не построен"))
            continue
        group = sorted(seed_marks[sid])
        members = [g for g in group if g in by_id]
        if members[0] != mk.room_id:
            continue  # одна запись на объединённый полигон
        poly, fixed = fix_invalid(polys[sid])
        poly, norm = _point_limit(poly, plan, width_pt, height_pt)
        if len(norm) < 3 or not Polygon([(x * width_pt, y * height_pt) for x, y in norm]).is_valid:
            unmatched.append(_unmatched(mk, "полигон невалиден"))
            continue
        area = round(norm_area_m2(norm, width_pt, height_pt, scale), 3)
        expl_area = round(sum(by_id[g].row.area_m2 for g in members), 2)
        notes = _zone_notes(sp, sid, mk, group, shapes)
        if fixed:
            notes.append("исправлена невалидность buffer(0)")
        if len(members) > 1:
            notes.append(f"НЕ РАЗДЕЛЕНО: одна область на марки {', '.join(members)}")
        delta = (area - expl_area) / expl_area * 100 if expl_area else 0.0
        if abs(delta) > zc.MARK_AREA_NOTE_PCT:
            notes.append(f"площадь отличается от экспликации на {delta:+.1f} %")
        zones.append(
            _Zone(
                _apartment_number(pm, mk),
                "+".join(members),
                " | ".join(by_id[g].row.name for g in members),
                expl_area,
                area,
                norm,
                list(dict.fromkeys(notes)),
            )
        )
    for room_id in extra:
        unmatched.append(
            {
                "room_mark": room_id,
                "name": None,
                "expl_area_m2": None,
                "reason": "нет в экспликации",
            }
        )
    return _output(args, scale, zones, unmatched, parking)


def _output(
    args: ZoneArgs,
    scale: float,
    zones: list[_Zone],
    unmatched: list[dict[str, object]],
    parking: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "page_index": args.page_index,
        "scale_mm_per_pt": scale,
        "zones": [z.as_json() for z in zones],
        "unmatched_marks": unmatched,
        "summary": _summary(zones),
        **parking,
    }


def _unmatched(mk: _Mark, reason: str) -> dict[str, object]:
    return {
        "room_mark": mk.room_id,
        "name": mk.row.name,
        "expl_area_m2": mk.row.area_m2,
        "reason": reason,
    }


def _summary(zones: list[_Zone]) -> list[dict[str, object]]:
    """По квартирам: число зон, сумма площадей многоугольников и комнат экспликации."""
    acc: dict[str, list[float]] = {}
    for z in zones:
        row = acc.setdefault(z.apartment_no, [0.0, 0.0, 0.0])
        row[0] += 1
        row[1] += z.poly_area_m2
        row[2] += z.expl_area_m2
    return [
        {
            "apartment_no": apt,
            "zones": int(v[0]),
            "poly_area_m2": round(v[1], 2),
            "expl_area_m2": round(v[2], 2),
            "delta_pct": round((v[1] - v[2]) / v[2] * 100, 1) if v[2] else None,
        }
        for apt, v in sorted(acc.items())
    ]


def write_zones(args: ZoneArgs, data: dict[str, object]) -> None:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
