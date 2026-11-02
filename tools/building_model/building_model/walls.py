"""Стены: колонны отдельно, фильтр тонких и коротких участков, склейка с учётом проёмов.

Стены не удлиняются и не соединяются друг с другом: висячие концы только считаются.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from building_model.coords import Frame
from building_model.elements import (
    AxisSource,
    Column,
    DanglingEnd,
    MergedWall,
    OpeningDraft,
    OutlineOutcome,
    Piece,
    Rejected,
    natural_key,
)
from building_model.geometry import (
    Pt,
    SegmentGrid,
    canonical_polygon,
    dist,
    dot,
    line_angle_deg,
    point_segment_distance,
    rnd_pt,
    sub,
)
from building_model.openings import key_points, midpoint_for_direction, reference_point
from building_model.outline import RealAxes, covered_share, rectangle_axis
from building_model.params import Params
from building_model.reader import SheetIn


@dataclass(frozen=True)
class WallsResult:
    walls: list[MergedWall]
    columns: list[Column]
    rejected: list[Rejected]
    dangling: list[DanglingEnd]
    pieces_total: int
    outline_outcomes: list[OutlineOutcome]
    input_area_m2: float
    bridged_gaps: int
    bridged_gap_mm: float
    kept_length_mm: float


def _ordered(a: Pt, b: Pt) -> tuple[Pt, Pt]:
    """Канонический порядок концов: направление a/b не должно влиять ни на что."""
    return (a, b) if rnd_pt(a, 3) <= rnd_pt(b, 3) else (b, a)


def _clusters(values: Sequence[float], tol: float) -> list[list[int]]:
    """Группы близких значений: новая группа, когда значение дальше tol от начала группы."""
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    groups: list[list[int]] = []
    start = 0.0
    for i in order:
        if not groups or values[i] - start > tol:
            groups.append([i])
            start = values[i]
        else:
            groups[-1].append(i)
    return groups


def _shifted_angle(piece: Piece) -> float:
    """Угол прямой в [-45, 135): оси 0° и 90° не попадают на разрез."""
    angle = line_angle_deg(sub(piece.b, piece.a))
    return angle - 180.0 if angle >= 135.0 else angle


class _OpeningIndex:
    """Проёмы для проверки «в разрыве лежит дверь, окно или пустой проём»."""

    def __init__(self, drafts: Sequence[OpeningDraft]) -> None:
        self.drafts = list(drafts)
        refs = [reference_point(d) for d in self.drafts]
        self.grid = SegmentGrid([(r, r) for r in refs])
        self.max_width = max((d.width for d in self.drafts), default=0.0)

    def in_gap(
        self, s_lo: float, s_hi: float, u: Pt, n: Pt, d_line: float, thickness: float, p: Params
    ) -> list[OpeningDraft]:
        if not self.drafts:
            return []
        p0 = (u[0] * s_lo + n[0] * d_line, u[1] * s_lo + n[1] * d_line)
        p1 = (u[0] * s_hi + n[0] * d_line, u[1] * s_hi + n[1] * d_line)
        reach = self.max_width + p.host_tol_mm + 500.0
        found = self.grid.query(
            min(p0[0], p1[0]) - reach,
            min(p0[1], p1[1]) - reach,
            max(p0[0], p1[0]) + reach,
            max(p0[1], p1[1]) + reach,
        )
        hits: list[OpeningDraft] = []
        for i in found:
            op = self.drafts[i]
            m = midpoint_for_direction(op, u, p)
            if m is None:
                continue
            if abs(dot(m, n) - d_line) > thickness / 2.0 + p.host_tol_mm:
                continue
            s_mid = dot(m, u)
            if s_lo - p.join_gap_mm <= s_mid <= s_hi + p.join_gap_mm:
                hits.append(op)
        return hits


@dataclass
class _Tally:
    """Склейки через проёмы: сколько разрывов и какой суммарной длины они перекрыли."""

    gaps: int = 0
    gap_mm: float = 0.0


@dataclass
class _Run:
    lo: float
    hi: float
    members: list[Piece]
    bridged: list[str]


def _make_wall(run: _Run, u: Pt, n: Pt, d_line: float, thickness: float) -> MergedWall:
    a = (u[0] * run.lo + n[0] * d_line, u[1] * run.lo + n[1] * d_line)
    b = (u[0] * run.hi + n[0] * d_line, u[1] * run.hi + n[1] * d_line)
    a, b = _ordered(a, b)
    by_role: dict[str, float] = {}
    for piece in run.members:
        by_role[piece.role] = by_role.get(piece.role, 0.0) + piece.length
    role = sorted(by_role.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    ids = sorted({p.wall_id for p in run.members}, key=natural_key)
    sources = {p.outline for p in run.members}
    axis_source: AxisSource = (
        "mixed" if len(sources) == 2 else ("outline" if True in sources else "segments")
    )
    return MergedWall(
        a=a,
        b=b,
        thickness=thickness,
        role=role,
        wall_ids=tuple(ids),
        pieces=len(run.members),
        bridged_openings=tuple(sorted(set(run.bridged), key=natural_key)),
        axis_source=axis_source,
    )


def _sweep_line(
    members: list[tuple[float, float, Piece]],
    u: Pt,
    n: Pt,
    d_line: float,
    thickness: float,
    index: _OpeningIndex,
    params: Params,
    tally: _Tally,
) -> list[MergedWall]:
    """Склейка участков одной прямой: зазор ≤ join_gap — всегда; больше — только через проём."""
    members.sort(key=lambda m: (m[0], m[1], natural_key(m[2].wall_id)))
    walls: list[MergedWall] = []
    run: _Run | None = None
    for lo, hi, piece in members:
        if run is None:
            run = _Run(lo, hi, [piece], [])
            continue
        gap = lo - run.hi
        merge = gap <= params.join_gap_mm
        bridge: list[OpeningDraft] = []
        if not merge:
            bridge = index.in_gap(run.hi, lo, u, n, d_line, thickness, params)
            allowed = sum(op.width for op in bridge) + params.opening_gap_slack_mm
            if bridge and gap <= allowed:
                merge = True
                tally.gaps += 1
                tally.gap_mm += gap
        if merge:
            run.hi = max(run.hi, hi)
            run.members.append(piece)
            for op in bridge:
                run.bridged.extend(op.ids)
        else:
            walls.append(_make_wall(run, u, n, d_line, thickness))
            run = _Run(lo, hi, [piece], [])
    if run is not None:
        walls.append(_make_wall(run, u, n, d_line, thickness))
    return walls


def _merge(
    pieces: Sequence[Piece], index: _OpeningIndex, params: Params
) -> tuple[list[MergedWall], _Tally]:
    walls: list[MergedWall] = []
    tally = _Tally()
    for t_group in _clusters([p.thickness for p in pieces], params.thickness_tol_mm):
        t_members = [pieces[i] for i in t_group]
        angles = [_shifted_angle(p) for p in t_members]
        for a_group in _clusters(angles, params.angle_tol_deg):
            group = [t_members[i] for i in a_group]
            weights = [p.length for p in group]
            total = sum(weights) or 1.0
            mean_angle = sum(angles[i] * w for i, w in zip(a_group, weights, strict=True)) / total
            u = (math.cos(math.radians(mean_angle)), math.sin(math.radians(mean_angle)))
            n = (-u[1], u[0])
            offsets = [dot(((p.a[0] + p.b[0]) / 2.0, (p.a[1] + p.b[1]) / 2.0), n) for p in group]
            for d_group in _clusters(offsets, params.axis_tol_mm):
                line = [group[i] for i in d_group]
                w_line = [weights[i] for i in d_group]
                w_sum = sum(w_line) or 1.0
                d_line = sum(offsets[i] * w for i, w in zip(d_group, w_line, strict=True)) / w_sum
                thickness = sum(p.thickness * w for p, w in zip(line, w_line, strict=True)) / w_sum
                spans: list[tuple[float, float, Piece]] = []
                for p in line:
                    sa, sb = dot(p.a, u), dot(p.b, u)
                    spans.append((min(sa, sb), max(sa, sb), p))
                walls.extend(_sweep_line(spans, u, n, d_line, thickness, index, params, tally))
    walls.sort(
        key=lambda w: (
            rnd_pt(w.a, 1),
            rnd_pt(w.b, 1),
            round(w.thickness, 1),
            tuple(natural_key(i) for i in w.wall_ids),
        )
    )
    return walls, tally


def _dangling(
    walls: Sequence[MergedWall], drafts: Sequence[OpeningDraft], params: Params
) -> list[DanglingEnd]:
    """Конец висит, если дальше dangling_tol + t/2 от оси любой другой стены."""
    grid = SegmentGrid([(w.a, w.b) for w in walls])
    max_half = max((w.thickness for w in walls), default=0.0) / 2.0
    points = [p for d in drafts for p in key_points(d)]
    point_grid = SegmentGrid([(p, p) for p in points])
    result: list[DanglingEnd] = []
    for i, wall in enumerate(walls):
        for end, point in (("a", wall.a), ("b", wall.b)):
            reach = params.dangling_tol_mm + max_half + params.dangling_report_reach_mm
            candidates = grid.query(
                point[0] - reach, point[1] - reach, point[0] + reach, point[1] + reach
            )
            faces = [
                point_segment_distance(point, walls[j].a, walls[j].b) - walls[j].thickness / 2.0
                for j in candidates
                if j != i
            ]
            gap = min(faces) if faces else None
            if gap is not None and gap <= params.dangling_tol_mm:
                continue
            r = params.host_tol_mm
            near = any(
                dist(point, points[k]) <= r
                for k in point_grid.query(point[0] - r, point[1] - r, point[0] + r, point[1] + r)
            )
            result.append(
                DanglingEnd(
                    wall_index=i,
                    end=end,
                    point=point,
                    near_opening=near,
                    gap_to_face_mm=gap,
                )
            )
    return result


def _classify(piece: Piece, params: Params) -> str | None:
    if piece.thickness < params.min_wall_thickness_mm:
        return "wall_rejected_thin"
    if piece.length < params.min_wall_length_mm:
        return "wall_rejected_short"
    return None


def _outline_pieces(
    bare: Sequence[tuple[str, float, Sequence[Pt], str]],
    real: Sequence[Piece],
    frame: Frame,
    params: Params,
) -> tuple[list[Piece], list[Rejected], list[OutlineOutcome]]:
    """Оси по контуру для стен без segments: фильтры как у обычных участков, затем отсев дублей."""
    kept: list[Piece] = []
    rejected: list[Rejected] = []
    outcomes: list[OutlineOutcome] = []
    axes = RealAxes(real)
    for wall_id, area, polygon, role in bare:
        result = rectangle_axis([frame.to_model(p) for p in polygon], params)
        if isinstance(result, str):
            outcomes.append(OutlineOutcome(wall_id, area, result, 0.0, None, None))
            continue
        a, b = _ordered(result.a, result.b)
        piece = Piece(a, b, result.thickness, role, wall_id, outline=True)
        code = _classify(piece, params)
        if code is not None:
            rejected.append(Rejected(code, piece))
            outcomes.append(OutlineOutcome(wall_id, area, "filtered", piece.length, a, b))
        elif covered_share((a, b), axes, params) >= params.outline_axis_duplicate_share:
            outcomes.append(OutlineOutcome(wall_id, area, "duplicate", piece.length, a, b))
        else:
            kept.append(piece)
            outcomes.append(OutlineOutcome(wall_id, area, "used", piece.length, a, b))
    return kept, rejected, outcomes


def build_walls(
    sheet: SheetIn, frame: Frame, drafts: Sequence[OpeningDraft], params: Params
) -> WallsResult:
    columns: list[Column] = []
    pieces: list[Piece] = []
    rejected: list[Rejected] = []
    bare: list[tuple[str, float, Sequence[Pt], str]] = []
    input_area = 0.0
    total = 0
    for wall in sorted(sheet.walls, key=lambda w: natural_key(w.id)):
        if wall.role == "column":
            polygon = canonical_polygon([frame.to_model(p) for p in wall.polygon_mm])
            columns.append(Column(wall.id, tuple(polygon), wall.thickness_mm))
            continue
        input_area += wall.area_m2
        if not wall.segments:
            bare.append((wall.id, wall.area_m2, wall.polygon_mm, wall.role or ""))
        for seg in wall.segments:
            a, b = _ordered(frame.to_model(seg.a), frame.to_model(seg.b))
            piece = Piece(a, b, seg.thickness_mm, wall.role or "", wall.id)
            total += 1
            code = _classify(piece, params)
            if code is not None:
                rejected.append(Rejected(code, piece))
            else:
                pieces.append(piece)
    real_length = sum(p.length for p in pieces)
    # Дубли ищутся только среди настоящих осей: порядок записей входа на итог не влияет.
    real_sorted = sorted(
        pieces, key=lambda p: (rnd_pt(p.a, 1), rnd_pt(p.b, 1), p.thickness, natural_key(p.wall_id))
    )
    extra, extra_rejected, outcomes = _outline_pieces(bare, real_sorted, frame, params)
    pieces = real_sorted + extra
    rejected.extend(extra_rejected)
    pieces.sort(key=lambda p: (rnd_pt(p.a, 1), rnd_pt(p.b, 1), p.thickness, natural_key(p.wall_id)))
    rejected.sort(
        key=lambda r: (
            r.code,
            rnd_pt(r.piece.a, 1),
            rnd_pt(r.piece.b, 1),
            natural_key(r.piece.wall_id),
        )
    )
    outcomes.sort(key=lambda o: natural_key(o.wall_id))
    index = _OpeningIndex(drafts)
    merged, tally = _merge(pieces, index, params)
    return WallsResult(
        walls=merged,
        columns=columns,
        rejected=rejected,
        dangling=_dangling(merged, drafts, params),
        pieces_total=total,
        outline_outcomes=outcomes,
        input_area_m2=input_area,
        bridged_gaps=tally.gaps,
        bridged_gap_mm=tally.gap_mm,
        kept_length_mm=real_length,
    )
