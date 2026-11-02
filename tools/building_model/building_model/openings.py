"""Проёмы: склейка двойных дверей, сторона открывания, поиск хозяина по геометрии."""

from __future__ import annotations

from collections.abc import Sequence

from building_model.coords import Frame
from building_model.elements import (
    HingeEnd,
    HostResult,
    LeafDraft,
    MergedWall,
    OpeningDraft,
    OpeningKind,
    OpensTo,
    Swing,
    natural_key,
)
from building_model.geometry import (
    Pt,
    SegmentGrid,
    cross,
    dist,
    dot,
    line_angle_diff_deg,
    mid,
    project,
    sub,
    unit,
)
from building_model.params import Params
from building_model.reader import DoorIn, GapIn, SheetIn


def _leaf(door: DoorIn, frame: Frame) -> LeafDraft:
    return LeafDraft(
        hinge=frame.to_model(door.hinge_mm),
        end_a=frame.to_model(door.end_a_mm),
        end_b=frame.to_model(door.end_b_mm),
        plangeom_host=door.host_wall,
    )


def _door_draft(doors: Sequence[DoorIn], frame: Frame, pair_missing: bool) -> OpeningDraft:
    ordered = sorted(doors, key=lambda d: natural_key(d.id))
    first = ordered[0]
    gaps = [d.gap_mm for d in ordered if d.gap_mm is not None]
    return OpeningDraft(
        kind="door",
        ids=tuple(d.id for d in ordered),
        width=first.opening_mm,
        a=None,
        b=None,
        leaves=tuple(_leaf(d, frame) for d in ordered),
        gap_mm=gaps[0] if gaps else None,
        pair_missing=pair_missing,
    )


def _pair_doubles(doubles: Sequence[DoorIn], frame: Frame, params: Params) -> list[list[DoorIn]]:
    """Пары полотен одного проёма: раскрытия равны, расстояние между петлями ≈ раскрытию."""
    ordered = sorted(doubles, key=lambda d: natural_key(d.id))
    candidates: list[tuple[float, int, int]] = []
    for i, first in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            second = ordered[j]
            if abs(first.opening_mm - second.opening_mm) > params.pair_opening_tol_mm:
                continue
            hinge_gap = dist(frame.to_model(first.hinge_mm), frame.to_model(second.hinge_mm))
            error = abs(hinge_gap - first.opening_mm)
            if error <= params.double_door_hinge_tol_mm:
                candidates.append((error, i, j))
    candidates.sort()
    used: set[int] = set()
    pairs: list[list[DoorIn]] = []
    for _, i, j in candidates:
        if i in used or j in used:
            continue
        used.update((i, j))
        pairs.append([ordered[i], ordered[j]])
    pairs.extend([ordered[i]] for i in range(len(ordered)) if i not in used)
    return pairs


def _gap_draft(item: GapIn, kind: OpeningKind, frame: Frame) -> OpeningDraft:
    return OpeningDraft(
        kind=kind,
        ids=(item.id,),
        width=item.width_mm,
        a=frame.to_model(item.a_mm),
        b=frame.to_model(item.b_mm),
        leaves=(),
        gap_mm=None,
        pair_missing=False,
    )


def prepare_openings(sheet: SheetIn, frame: Frame, params: Params) -> list[OpeningDraft]:
    """Двери (пары склеены), окна и пустые проёмы в системе модели, в каноническом порядке."""
    drafts: list[OpeningDraft] = []
    singles = [d for d in sheet.doors if d.leaves != 2]
    doubles = [d for d in sheet.doors if d.leaves == 2]
    drafts.extend(_door_draft([d], frame, pair_missing=False) for d in singles)
    for group in _pair_doubles(doubles, frame, params):
        drafts.append(_door_draft(group, frame, pair_missing=len(group) == 1))
    drafts.extend(_gap_draft(w, "window", frame) for w in sheet.windows)
    drafts.extend(_gap_draft(o, "opening", frame) for o in sheet.openings)
    drafts.sort(key=lambda d: (d.kind, tuple(natural_key(i) for i in d.ids)))
    return drafts


def reference_point(op: OpeningDraft) -> Pt:
    """Опорная точка проёма для грубой выборки по рамке (до выбора хозяина)."""
    if op.a is not None and op.b is not None:
        return mid(op.a, op.b)
    return op.leaves[0].hinge


def key_points(op: OpeningDraft) -> list[Pt]:
    """Точки, у которых стена обрывается: концы разрыва окна, петля и концы дуги двери."""
    if op.a is not None and op.b is not None:
        return [op.a, op.b]
    points: list[Pt] = []
    for leaf in op.leaves:
        points.extend((leaf.hinge, leaf.end_a, leaf.end_b))
    return points


def closed_end(leaf: LeafDraft, u: Pt) -> tuple[Pt, Pt, float]:
    """(закрытый конец, открытый конец, |cos| с осью u): закрытое полотно лежит вдоль стены."""
    va = unit(sub(leaf.end_a, leaf.hinge))
    vb = unit(sub(leaf.end_b, leaf.hinge))
    ca = abs(dot(va, u)) if va is not None else 0.0
    cb = abs(dot(vb, u)) if vb is not None else 0.0
    if cb > ca:
        return (leaf.end_b, leaf.end_a, cb)
    return (leaf.end_a, leaf.end_b, ca)


def midpoint_for_direction(op: OpeningDraft, u: Pt, params: Params) -> Pt | None:
    """Середина проёма, если он ориентирован вдоль оси u (допуск из Params); иначе None."""
    if op.a is not None and op.b is not None:
        if line_angle_diff_deg(sub(op.b, op.a), u) > params.host_window_angle_deg:
            return None
        return mid(op.a, op.b)
    if len(op.leaves) == 2:
        h1, h2 = op.leaves[0].hinge, op.leaves[1].hinge
        if line_angle_diff_deg(sub(h2, h1), u) > params.door_wall_angle_deg:
            return None
        return mid(h1, h2)
    leaf = op.leaves[0]
    closed, _, _ = closed_end(leaf, u)
    if line_angle_diff_deg(sub(closed, leaf.hinge), u) > params.door_wall_angle_deg:
        return None
    return mid(leaf.hinge, closed)


def _fallback(op: OpeningDraft) -> tuple[Pt, tuple[Pt, Pt]]:
    """Положение проёма без хозяина: только то, что читается из самого проёма."""
    if op.a is not None and op.b is not None:
        return (mid(op.a, op.b), (op.a, op.b))
    if len(op.leaves) == 2:
        h1, h2 = op.leaves[0].hinge, op.leaves[1].hinge
        return (mid(h1, h2), (h1, h2))
    hinge = op.leaves[0].hinge
    return (hinge, (hinge, hinge))


def _swings(op: OpeningDraft, mid_pt: Pt, u: Pt) -> tuple[Swing, ...]:
    result: list[Swing] = []
    for leaf in op.leaves:
        _, open_end, _ = closed_end(leaf, u)
        hinge_at: HingeEnd = "a" if dot(sub(leaf.hinge, mid_pt), u) < 0 else "b"
        opens_to: OpensTo = "left" if cross(u, sub(open_end, leaf.hinge)) > 0 else "right"
        result.append(Swing(hinge_at=hinge_at, opens_to=opens_to))
    return tuple(sorted(result, key=lambda s: (s.hinge_at, s.opens_to)))


def _hosted_span(op: OpeningDraft, u: Pt) -> tuple[Pt, Pt]:
    if op.a is not None and op.b is not None:
        return (op.a, op.b)
    if len(op.leaves) == 2:
        return (op.leaves[0].hinge, op.leaves[1].hinge)
    leaf = op.leaves[0]
    closed, _, _ = closed_end(leaf, u)
    return (leaf.hinge, closed)


def assign_hosts(
    drafts: Sequence[OpeningDraft], walls: Sequence[MergedWall], params: Params
) -> list[HostResult]:
    """Хозяин ищется заново среди склеенных стен; host_wall plangeom не используется.

    Условие: проекция середины проёма попадает на отрезок оси, расстояние до оси не больше
    половины толщины + host_tol_mm, направление окна/проёма вдоль оси. Нет кандидата или два
    равноценных (разница расстояний до оси ≤ host_ambiguity_mm) — хозяин не угадывается.
    """
    grid = SegmentGrid([(w.a, w.b) for w in walls])
    results: list[HostResult] = []
    for op in drafts:
        ref = reference_point(op)
        reach = op.width + 2.0 * params.host_tol_mm + 500.0
        found = grid.query(ref[0] - reach, ref[1] - reach, ref[0] + reach, ref[1] + reach)
        scored: list[tuple[float, int, Pt, Pt, float]] = []
        for index in found:
            wall = walls[index]
            u = unit(sub(wall.b, wall.a))
            if u is None:
                continue
            m = midpoint_for_direction(op, u, params)
            if m is None:
                continue
            along, perp, length = project(m, wall.a, wall.b)
            if not 0.0 <= along <= length:
                continue
            if perp > wall.thickness / 2.0 + params.host_tol_mm:
                continue
            scored.append((perp, index, m, u, along))
        scored.sort(key=lambda s: (s[0], s[1]))
        fallback_mid, fallback_span = _fallback(op)
        if not scored:
            results.append(
                HostResult(op, "no_host", None, fallback_mid, fallback_span, None, (), 0)
            )
            continue
        if len(scored) > 1 and scored[1][0] - scored[0][0] <= params.host_ambiguity_mm:
            results.append(
                HostResult(
                    op, "ambiguous", None, fallback_mid, fallback_span, None, (), len(scored)
                )
            )
            continue
        _, index, m, u, along = scored[0]
        swings = _swings(op, m, u) if op.kind == "door" else ()
        results.append(
            HostResult(op, "hosted", index, m, _hosted_span(op, u), along, swings, len(scored))
        )
    return results
