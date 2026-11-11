"""Смещение дерева трасс (цепочки между ветвлениями) со стыковкой: без висячих концов на тройниках.

Цепочки ориентируются от корня; смещение — на off в одну сторону хода у всех цепочек поддерева
корневой цепочки (положительное — влево, если она идёт по +X, при вертикали — по +Y). Начало
дочерней
цепочки — пересечение продолжения её первого отрезка со смещённой линией родителя; конец родителя
продлевается или обрезается до крайнего такого пересечения. Начало цепочек корня и концы-цели
соединяются с исходной точкой коротким отрезком, так что концы лежат на узлах, а не рядом.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from cad_mep.result import Pt

EPS = 1e-6
KeyT = tuple[int, int]


def _key(p: Pt) -> KeyT:
    return (round(p[0]), round(p[1]))


def _clean(pts: Sequence[Pt]) -> list[Pt]:
    out: list[Pt] = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > EPS:
            out.append(p)
    return out


def offset_pts(pts: Sequence[Pt], off: float, miter_limit: float = 3.0) -> list[Pt]:
    """Параллельная ломаная на off слева от хода; острые углы — miter с ограничением длины."""
    line = _clean(pts)
    if len(line) < 2:
        return list(line)
    segs: list[tuple[Pt, Pt]] = []
    for a, b in pairwise(line):
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        u = ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)
        segs.append((u, (-u[1], u[0])))
    out = [(line[0][0] + off * segs[0][1][0], line[0][1] + off * segs[0][1][1])]
    for k in range(1, len(line) - 1):
        n1, n2 = segs[k - 1][1], segs[k][1]
        denom = max(1.0 + n1[0] * n2[0] + n1[1] * n2[1], 1.0 / miter_limit)
        out.append(
            (
                line[k][0] + off * (n1[0] + n2[0]) / denom,
                line[k][1] + off * (n1[1] + n2[1]) / denom,
            )
        )
    out.append((line[-1][0] + off * segs[-1][1][0], line[-1][1] + off * segs[-1][1][1]))
    return out


def _side(pts: Sequence[Pt]) -> float:
    """+1, если цепочка в целом идёт по +X (при вертикали — по +Y), иначе -1."""
    dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
    return -1.0 if dx < -EPS or (abs(dx) <= EPS and dy < 0) else 1.0


def _unit(a: Pt, b: Pt) -> Pt:
    ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)


def _dock(end: Pt, u_par: Pt, start: Pt, u_ch: Pt, limit: float) -> float:
    """Расстояние вдоль родителя от его смещённого конца до пересечения с линией ребёнка."""
    cross = u_par[0] * u_ch[1] - u_par[1] * u_ch[0]
    if abs(cross) < 1e-3:
        return 0.0
    dx, dy = start[0] - end[0], start[1] - end[1]
    s = (dx * u_ch[1] - dy * u_ch[0]) / cross
    return max(-limit, min(limit, s))


def _trim_overlap(child: list[Pt], end: Pt, u_par: Pt) -> None:
    """Ребёнок, продолжающий родителя по прямой, начинается там, где родитель кончается."""
    while len(child) >= 2:
        u = _unit(child[0], child[1])
        if abs(u[0] * u_par[1] - u[1] * u_par[0]) > 1e-3 or u[0] * u_par[0] + u[1] * u_par[1] <= 0:
            return
        reach = (end[0] - child[0][0]) * u[0] + (end[1] - child[0][1]) * u[1]
        seg = math.hypot(child[1][0] - child[0][0], child[1][1] - child[0][1])
        if reach <= 0:
            return
        if reach >= seg - EPS and len(child) > 2:
            child.pop(0)
            continue
        child[0] = (child[0][0] + u[0] * min(reach, seg), child[0][1] + u[1] * min(reach, seg))
        return


def offset_tree(
    chains: Sequence[Sequence[Pt]], root: Pt, off: float, tips: bool = False
) -> list[list[Pt]]:
    """Смещённые цепочки в том же порядке и с тем же направлением, что на входе.

    tips — концы-цели остаются смещёнными (тупик ветки), иначе к цели добавляется короткий
    отрезок на исходную точку.
    """
    if abs(off) < EPS or not chains:
        return [list(c) for c in chains]
    at: dict[KeyT, list[int]] = {}
    for i, c in enumerate(chains):
        at.setdefault(_key(c[0]), []).append(i)
        at.setdefault(_key(c[-1]), []).append(i)
    oriented: dict[int, list[Pt]] = {}
    parent: dict[int, int | None] = {}
    flipped: set[int] = set()
    queue: list[tuple[KeyT, int | None]] = [(_key(root), None)]
    order: list[int] = []
    while queue:
        node, par = queue.pop(0)
        for i in at.get(node, []):
            if i in oriented:
                continue
            c = list(chains[i])
            if _key(c[0]) != node:
                c = c[::-1]
                flipped.add(i)
            oriented[i], parent[i] = c, par
            order.append(i)
            queue.append((_key(c[-1]), i))
    for i, c in enumerate(chains):  # цепочки, не связанные с корнем: смещаются сами по себе
        if i not in oriented:
            oriented[i], parent[i] = list(c), None
            order.append(i)
    # сторона смещения у корневой цепочки — как у цепочки, направленной «вправо или вверх», у
    # потомков — та же сторона хода: так линии систем держатся своих сторон коридора, а на
    # тройниках смещённые линии не заворачиваются друг через друга
    sign: dict[int, float] = {}
    for i in order:
        par = parent[i]
        sign[i] = _side(oriented[i]) if par is None else sign[par]
    shifted = {i: offset_pts(oriented[i], off * sign[i]) for i in oriented}
    limit = max(4 * abs(off), 300.0)
    kids: dict[int, list[int]] = {}
    for i in order:
        p = parent[i]
        if p is not None:
            kids.setdefault(p, []).append(i)
    for p in order:  # от корня к листьям: начало родителя уже состыковано с его родителем
        ids = kids.get(p)
        if not ids:
            continue
        po = shifted[p]
        if len(po) < 2:
            continue
        u_par = _unit(po[-2], po[-1])
        ts = []
        for i in ids:
            co = shifted[i]
            if len(co) < 2:
                ts.append(0.0)
                continue
            ts.append(_dock(po[-1], u_par, co[0], _unit(co[0], co[1]), limit))
        last = math.hypot(po[-1][0] - po[-2][0], po[-1][1] - po[-2][1])
        t_star = max(max(ts), 1.0 - last)
        base = po[-1]
        free_start = len(po) == 2 and parent[p] is None
        for i, t in zip(ids, ts, strict=True):
            t_dock = t if free_start else max(t, -last)
            shifted[i][0] = (base[0] + u_par[0] * t_dock, base[1] + u_par[1] * t_dock)
        po[-1] = (base[0] + u_par[0] * t_star, base[1] + u_par[1] * t_star)
        if free_start and min(ts) < -last:  # стык раньше начала короткой корневой цепочки
            po[0] = (base[0] + u_par[0] * min(ts), base[1] + u_par[1] * min(ts))
        for i in ids:
            _trim_overlap(shifted[i], po[-1], u_par)
    owner: dict[KeyT, int] = {}
    for i in order:
        owner.setdefault(_key(oriented[i][-1]), i)
    result: list[list[Pt]] = []
    for i in range(len(chains)):
        pts = shifted[i]
        if parent[i] is None:
            pts = [oriented[i][0], *pts]
        if i not in kids:
            node = _key(oriented[i][-1])
            if owner[node] != i and len(at[node]) > 1:  # замыкает петлю на чужой узел ветвления
                pts = [*pts, shifted[owner[node]][-1]]
            elif not tips:
                pts = [*pts, oriented[i][-1]]
        pts = _clean(pts)
        result.append(pts[::-1] if i in flipped else pts)
    return result
