"""Замена scipy: метки связности и расстояния на numpy."""

from __future__ import annotations

import numpy as np

from cad_mep import raster


def test_label_matches_flood_fill_order() -> None:
    mask = np.zeros((6, 8), dtype=bool)
    mask[0, 0:2] = True
    mask[1, 1] = True  # соединён с первой по вертикали
    mask[3, 5:8] = True
    mask[4, 7] = True
    mask[5, 0] = True
    lab, n = raster.label(mask)
    assert n == 3
    assert lab[0, 0] == lab[1, 1] == 1
    assert lab[3, 5] == lab[4, 7] == 2
    assert lab[5, 0] == 3


def test_label_diagonal_connectivity() -> None:
    mask = np.zeros((3, 3), dtype=bool)
    mask[0, 0] = mask[1, 1] = mask[2, 2] = True
    assert raster.label(mask)[1] == 3
    assert raster.label(mask, diagonal=True)[1] == 1


def test_nearest_true_is_exact_within_radius() -> None:
    rng = np.random.default_rng(1)
    target = rng.random((40, 50)) > 0.985
    target[0, 0] = True
    res = raster.nearest_true(target, 12)
    ys, xs = np.nonzero(target)
    for iy, ix in [(5, 7), (20, 30), (39, 49), (0, 0), (25, 25)]:
        d = np.hypot(ys - iy, xs - ix)
        k = int(np.argmin(d))
        if d[k] <= 12:
            assert abs(res.dist[iy, ix] - d[k]) < 1e-9
            assert abs(np.hypot(res.iy[iy, ix] - iy, res.ix[iy, ix] - ix) - d[k]) < 1e-9
        else:
            assert res.dist[iy, ix] == 13


def test_comp_stats() -> None:
    mask = np.zeros((5, 6), dtype=bool)
    mask[1:3, 1:4] = True
    lab, n = raster.label(mask)
    st = raster.comp_stats(lab, n)
    assert st.counts[0] == 6
    assert (st.x0[0], st.y0[0], st.x1[0], st.y1[0]) == (1, 1, 3, 2)
    assert abs(st.cx[0] - 2.0) < 1e-9 and abs(st.cy[0] - 1.5) < 1e-9
