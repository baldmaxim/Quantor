"""Раскладка путей одного дерева в параллельные полосы (пучок) без пересечений внутри слоя.

Пути — списки узлов сетки от общего корня; общие участки у путей — общие рёбра (дерево). На каждом
ребре пути упорядочены одним глобальным компаратором по повороту в точке расхождения (влево 0,
прямо 1, вправо 2), поэтому порядок полос на любом общем ребре один и тот же. Смещение полосы —
перпендикуляр к ребру (влево от хода «от корня» положительно); углы — «острый» стык (miter),
смена смещения на прямом участке — короткий перескок.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Sequence
from itertools import pairwise

from cad_mep.result import Pt
from cad_mep.route import RouteGrid

Dir = tuple[int, int]
# положение перескока вдоль хода = JOG_K × смещение: у соседних полос перескоки не совпадают
JOG_K = 0.03
EPS = 1e-6
Mark = int | None


def grid_dirs(rg: RouteGrid, cells: Sequence[int]) -> list[Dir]:
    """Единичные направления (dx, dy) шагов пути."""
    out: list[Dir] = []
    for a, b in pairwise(cells):
        dx = float(rg.xy[b][0] - rg.xy[a][0])
        dy = float(rg.xy[b][1] - rg.xy[a][1])
        out.append(((dx > EPS) - (dx < -EPS), (dy > EPS) - (dy < -EPS)))
    return out


def turn_rank(din: Dir, dn: Dir) -> int:
    """Поворот относительно хода: влево 0, прямо 1, вправо 2, назад 3."""
    cross = din[0] * dn[1] - din[1] * dn[0]
    if cross > 0:
        return 0
    if cross < 0:
        return 2
    return 1 if din[0] * dn[0] + din[1] * dn[1] > 0 else 3


def jog_shift(before: float, after: float) -> float:
    """Положение перескока вдоль хода: уходящая к центру полоса идёт первой, без наложений."""
    return JOG_K * before if after < before else -JOG_K * before


def _simplify(pts: list[tuple[Pt, Mark]]) -> list[tuple[Pt, Mark]]:
    """Убрать повторы и лишние вершины на прямой; помеченные вершины остаются."""
    out: list[tuple[Pt, Mark]] = []
    for p, m in pts:
        if out and math.hypot(p[0] - out[-1][0][0], p[1] - out[-1][0][1]) < EPS:
            if out[-1][1] is None:
                out[-1] = (out[-1][0], m)
            continue
        out.append((p, m))
    res: list[tuple[Pt, Mark]] = []
    for i, (p, m) in enumerate(out):
        if 0 < i < len(out) - 1 and m is None and res:
            a, b = res[-1][0], out[i + 1][0]
            cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
            dot = (p[0] - a[0]) * (b[0] - p[0]) + (p[1] - a[1]) * (b[1] - p[1])
            if abs(cross) < EPS and dot > 0:
                continue
        res.append((p, m))
    return res


def _trim_reversed(pts: list[tuple[Pt, Mark]], outs: list[Dir | None]) -> None:
    """Крайние вершины, лежащие «назад» от хода, убрать (outs — направление хода из вершины).

    Бывает, когда до первого (последнего) поворота меньше, чем смещение полосы: угол полосы
    оказывается за началом (концом) пути.
    """

    def backward(i: int) -> bool:
        d = outs[i]
        if d is None:
            return False
        dx, dy = pts[i + 1][0][0] - pts[i][0][0], pts[i + 1][0][1] - pts[i][0][1]
        return dx * d[0] + dy * d[1] <= EPS

    while len(pts) > 2 and pts[0][1] is None and backward(0):
        pts.pop(0)
        outs.pop(0)
    while len(pts) > 2 and pts[-1][1] is None and backward(len(pts) - 2):
        pts.pop()
        outs.pop()


class Layout:
    """Порядок и смещения полос путей одного дерева."""

    def __init__(
        self,
        rg: RouteGrid,
        paths: Sequence[Sequence[int]],
        widths: Sequence[int],
        step: float,
        snap_mm: float,
    ) -> None:
        self.rg, self.step, self.snap = rg, step, snap_mm
        self.paths = [list(p) for p in paths]
        self.widths = list(widths)
        self.dirs = [grid_dirs(rg, p) for p in self.paths]
        self.offs: list[list[list[float]]] = [
            [[0.0] * max(len(p) - 1, 0) for _ in range(self.widths[i])]
            for i, p in enumerate(self.paths)
        ]
        edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for i, p in enumerate(self.paths):
            for k, e in enumerate(pairwise(p)):
                edges.setdefault(e, []).append((i, k))
        cache: dict[tuple[int, int], int] = {}

        def cmp(x: int, y: int) -> int:
            if (x, y) not in cache:
                cache[(x, y)] = self._cmp(x, y) or (x - y)
            return cache[(x, y)]

        for users in edges.values():
            at = dict(users)
            order = sorted(at, key=functools.cmp_to_key(cmp))
            total = sum(self.widths[i] for i in order)
            slot = 0
            for i in order:
                for j in range(self.widths[i]):
                    self.offs[i][j][at[i]] = ((total - 1) / 2 - slot) * step
                    slot += 1
        # на прямом участке полоса не перестраивается: смещение первого ребра участка держится до
        # поворота, поэтому на тройниках уходящие полосы не освобождают места «на ходу»
        for i, dirs in enumerate(self.dirs):
            for k in range(1, len(dirs)):
                if dirs[k] == dirs[k - 1]:
                    for lane in self.offs[i]:
                        lane[k] = lane[k - 1]
        extent = max((abs(o) for lanes in self.offs for ln in lanes for o in ln[:1]), default=0.0)
        # полосы шире допуска узла сводятся к нему веером: длина у всех полос одна, не больше
        # самого короткого первого прямого участка; отрезки веера сходятся только в узле
        # то же при нескольких направлениях у корня: полосы разных направлений иначе пересекутся
        first_edges = {tuple(p[:2]) for p in self.paths if len(p) > 1}
        self.start_fan: float | None = None
        if extent > snap_mm or (len(first_edges) > 1 and extent > 0):
            runs = [
                math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
                for i, p in enumerate(self.paths)
                for j in range(self.widths[i])
                for pts in [self.polyline(p, self.offs[i][j])[0]]
                if len(pts) >= 2
            ]
            self.start_fan = min([extent + step, *runs])

    def _cmp(self, x: int, y: int) -> int:
        cx, cy = self.paths[x], self.paths[y]
        k = 0
        while k + 1 < len(cx) and k + 1 < len(cy) and cx[k + 1] == cy[k + 1]:
            k += 1
        if k == 0 or not self.dirs[x]:
            return 0
        din = self.dirs[x][k - 1]
        nx = self.dirs[x][k] if k < len(self.dirs[x]) else din
        ny = self.dirs[y][k] if k < len(self.dirs[y]) else din
        return turn_rank(din, nx) - turn_rank(din, ny)

    def xy(self, n: int) -> Pt:
        return (float(self.rg.xy[n][0]), float(self.rg.xy[n][1]))

    def polyline(
        self,
        cells: Sequence[int],
        offs: Sequence[float],
        marks: Sequence[int] = (),
        jog: dict[int, float] | None = None,
    ) -> tuple[list[Pt], dict[int, int]]:
        """Ломаная полосы по узлам и смещениям рёбер; marks — узлы, которым нужен индекс вершины.

        Возвращает вершины и соответствие «номер узла пути → индекс вершины».
        """
        dirs = grid_dirs(self.rg, cells)
        nrm = [(-dy, dx) for dx, dy in dirs]
        keep = set(marks)
        if not dirs:
            return [self.xy(cells[0])], {0: 0} if 0 in keep else {}
        x0, y0 = self.xy(cells[0])
        pts: list[tuple[Pt, Mark]] = [
            ((x0 + offs[0] * nrm[0][0], y0 + offs[0] * nrm[0][1]), 0 if 0 in keep else None)
        ]
        outs: list[Dir | None] = [dirs[0]]
        for k in range(1, len(cells) - 1):
            x, y = self.xy(cells[k])
            mk = k if k in keep else None
            din, dout, oi, oo = dirs[k - 1], dirs[k], offs[k - 1], offs[k]
            if din == dout:
                if abs(oi - oo) > EPS:
                    t = (jog or {}).get(k, jog_shift(oi, oo))
                    px, py = x + din[0] * t, y + din[1] * t
                    pts.append(((px + oi * nrm[k - 1][0], py + oi * nrm[k - 1][1]), None))
                    pts.append(((px + oo * nrm[k][0], py + oo * nrm[k][1]), mk))
                    outs += [None, dout]
                elif mk is not None:
                    pts.append(((x + oi * nrm[k - 1][0], y + oi * nrm[k - 1][1]), mk))
                    outs.append(dout)
            else:
                vx = x + oi * nrm[k - 1][0] + oo * nrm[k][0]
                vy = y + oi * nrm[k - 1][1] + oo * nrm[k][1]
                pts.append(((vx, vy), mk))
                outs.append(dout)
        x, y = self.xy(cells[-1])
        last = len(cells) - 1
        pts.append(
            ((x + offs[-1] * nrm[-1][0], y + offs[-1] * nrm[-1][1]), last if last in keep else None)
        )
        outs.append(None)
        _trim_reversed(pts, outs)
        clean = _simplify(pts)
        return [p for p, _ in clean], {m: i for i, (_, m) in enumerate(clean) if m is not None}

    def lane(self, i: int, j: int, marks: Sequence[int] = ()) -> tuple[list[Pt], dict[int, int]]:
        """Полоса j пути i с веером у корня и сведением конца к узлу, если он далеко."""
        cells = self.paths[i]
        pts, idx = self.polyline(cells, self.offs[i][j], marks)
        a, b = self.xy(cells[0]), self.xy(cells[-1])
        offs = self.offs[i][j]
        o_start, o_end = (abs(offs[0]), abs(offs[-1])) if offs else (0.0, 0.0)
        return fan(pts, idx, a, self.start_fan, b, o_end > self.snap, o_start > self.snap)


def fan(
    pts: list[Pt],
    idx: dict[int, int],
    start: Pt,
    delta: float | None,
    end: Pt,
    end_stub: bool,
    start_stub: bool = False,
) -> tuple[list[Pt], dict[int, int]]:
    """Веер у начала (все полосы корня сходятся в узле) и короткий отрезок на узел в конце."""
    out = list(pts)
    marks = dict(idx)
    if delta is not None and len(out) >= 2:
        a, b = out[0], out[1]
        run = math.hypot(b[0] - a[0], b[1] - a[1])
        if run > EPS:
            ux, uy = (b[0] - a[0]) / run, (b[1] - a[1]) / run
            out[0] = (a[0] + ux * min(delta, run), a[1] + uy * min(delta, run))
        out.insert(0, start)
        marks = {k: v + 1 for k, v in marks.items()}
    elif start_stub and out:
        out.insert(0, start)
        marks = {k: v + 1 for k, v in marks.items()}
    if end_stub and len(out) >= 2:
        out.append(end)
    return out, marks


def lanes(
    rg: RouteGrid,
    paths: Sequence[Sequence[int]],
    widths: Sequence[int],
    step: float,
    snap_mm: float = 130.0,
) -> list[list[Pt]]:
    """Полосы всех путей подряд: у пути i — widths[i] ломаных слева направо (от корня)."""
    lay = Layout(rg, paths, widths, step, snap_mm)
    return [lay.lane(i, j)[0] for i in range(len(lay.paths)) for j in range(lay.widths[i])]
