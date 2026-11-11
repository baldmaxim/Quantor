"""Тесты пучка полос (lanes), роста пучка (bundle) и смещения дерева (treeoff) на малой сетке."""

from __future__ import annotations

import math
from itertools import combinations, pairwise

import numpy as np
from shapely.geometry import LineString, Point

from cad_mep.bundle import grow
from cad_mep.lanes import Layout, lanes
from cad_mep.params import load_params
from cad_mep.route import DIRS, RouteGrid, spt
from cad_mep.treeoff import offset_tree

STEP = 50.0
SIZE = 40


def _grid() -> RouteGrid:
    """Открытое поле 40 x 40 клеток по 50 мм: проходимо всё, веса единичные."""
    pas = np.ones((SIZE, SIZE), dtype=np.bool_)
    idx = np.arange(SIZE * SIZE, dtype=np.int64).reshape(SIZE, SIZE)
    ys, xs = np.nonzero(pas)
    padded = -np.ones((SIZE + 2, SIZE + 2), dtype=np.int64)
    padded[1:-1, 1:-1] = idx
    nbr = [padded[ys + 1 + dy, xs + 1 + dx].tolist() for dy, dx in DIRS]
    return RouteGrid(
        STEP,
        pas,
        np.full((SIZE, SIZE), 1000.0),
        idx,
        np.c_[(xs + 0.5) * STEP, (ys + 0.5) * STEP],
        np.zeros((SIZE, SIZE), dtype=np.int32),
        np.zeros((SIZE, SIZE), dtype=np.bool_),
        nbr,
        [1.0] * (SIZE * SIZE),
        500.0,
    )


def _cell(rg: RouteGrid, ix: int, iy: int) -> int:
    return int(rg.idx[iy, ix])


def _line(rg: RouteGrid, pts: list[tuple[int, int]]) -> list[int]:
    """Путь по прямым между опорными клетками (ix, iy)."""
    out = [_cell(rg, *pts[0])]
    for (x0, y0), (x1, y1) in pairwise(pts):
        n = max(abs(x1 - x0), abs(y1 - y0))
        for k in range(1, n + 1):
            out.append(_cell(rg, x0 + (x1 - x0) * k // n, y0 + (y1 - y0) * k // n))
    return out


def _proper_crossings(lines: list[list[tuple[float, float]]]) -> int:
    geoms = [LineString(p) for p in lines]
    return sum(1 for a, b in combinations(geoms, 2) if a.crosses(b))


def test_bundle_trunk_with_branches_has_no_crossings() -> None:
    rg = _grid()
    trunk = [(20, 0), (20, 12)]
    paths = [
        _line(rg, [*trunk, (8, 12), (8, 20)]),  # ствол и отвод влево
        _line(rg, [*trunk, (20, 25)]),  # прямо
        _line(rg, [*trunk, (32, 12), (32, 20)]),  # вправо
        _line(rg, [(20, 0), (20, 6), (14, 6), (14, 10)]),  # ранний отвод влево
        _line(rg, [(20, 0), (20, 8), (26, 8), (26, 3)]),  # ранний отвод вправо
    ]
    result = lanes(rg, paths, [2] * len(paths), 30.0)
    assert len(result) == 2 * len(paths)
    assert _proper_crossings(result) == 0
    lay = Layout(rg, paths, [2] * len(paths), 30.0, 145.0)
    # полосы одного пути лежат рядом: T1 (левая) левее T2 на шаг
    assert math.isclose(lay.offs[0][0][0] - lay.offs[0][1][0], 30.0)


def test_bundle_lanes_share_order_on_common_edges() -> None:
    rg = _grid()
    paths = [_line(rg, [(20, 0), (20, 10), (10, 10)]), _line(rg, [(20, 0), (20, 10), (30, 10)])]
    lay = Layout(rg, paths, [2, 2], 30.0, 145.0)
    # на общем стволе левый путь (уходит влево) — слева: его смещения больше
    assert lay.offs[0][0][0] > lay.offs[1][0][0]
    assert lay.offs[0][1][0] > lay.offs[1][0][0]
    # на общем ребре четыре полосы: ±15 и ±45
    assert sorted(round(o) for ln in (lay.offs[0] + lay.offs[1]) for o in ln[:1]) == [
        -45,
        -15,
        15,
        45,
    ]


def test_grow_far_to_near_builds_tree_without_reentry() -> None:
    rg = _grid()
    params = load_params(None)
    root = _cell(rg, 20, 0)
    targets = [_cell(rg, 5, 30), _cell(rg, 35, 28), _cell(rg, 20, 10)]
    paths = grow(rg, root, targets, [], params)
    assert all(p and p[0] == root and p[-1] == t for p, t in zip(paths, targets, strict=True))
    edges = {frozenset(e) for p in paths for e in pairwise(p)}
    nodes = {c for p in paths for c in p}
    assert len(edges) == len(nodes) - 1  # дерево: петель нет
    # путь к ближней цели идёт по стволу дальних (скидка ALPHA): общий префикс не короче корня
    assert paths[2][:3] == paths[0][:3] or paths[2][:3] == paths[1][:3]


def test_spt_init_and_extra_are_backward_compatible() -> None:
    rg = _grid()
    src = _cell(rg, 5, 5)
    dst = _cell(rg, 30, 5)
    plain = spt(rg, [src], [dst])[dst]
    assert spt(rg, [src], [dst], False, None, None)[dst] == plain
    assert math.isclose(spt(rg, [src], [dst], False, {src: 100.0})[dst], plain + 100.0)
    blocked = {_cell(rg, x, 5): math.inf for x in range(10, 20)}
    assert spt(rg, [src], [dst], False, None, blocked)[dst] > plain


def test_offset_tree_docks_every_end_on_the_layer() -> None:
    root = (0.0, 0.0)
    chains = [
        [(0.0, 0.0), (0.0, 1000.0)],  # ствол
        [(0.0, 1000.0), (-1500.0, 1000.0)],  # влево
        [(0.0, 1000.0), (1500.0, 1000.0), (1500.0, 1600.0)],  # вправо и вверх
        [(0.0, 1000.0), (0.0, 2500.0)],  # прямо
    ]
    for off in (150.0, -250.0):
        out = offset_tree(chains, root, off)
        pts = [LineString(c) for c in out]
        leaves = {(-1500.0, 1000.0), (1500.0, 1600.0), (0.0, 2500.0)}
        for i, c in enumerate(out):
            for end in (c[0], c[-1]):
                if end == root or end in leaves:
                    continue
                others = [g for j, g in enumerate(pts) if j != i]
                assert min(g.distance(Point(end)) for g in others) < 1e-6, (i, end)
        assert {c[-1] for c in out[1:]} == leaves
        assert _proper_crossings(out) == 0


def test_offset_tree_zero_offset_is_identity() -> None:
    chains = [[(0.0, 0.0), (0.0, 100.0)], [(0.0, 100.0), (50.0, 100.0)]]
    assert offset_tree(chains, (0.0, 0.0), 0.0) == chains
