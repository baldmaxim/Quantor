"""Привязка PDF -> DXF: x = (px - ox) * s, y = (oy - py) * s (пт -> мм) и локальный сдвиг растра."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray

from cad_mep.errors import MepError
from cad_mep.params import Params

Arr2 = NDArray[np.float64]


@dataclass(frozen=True)
class TieStats:
    voters: int
    n_checked: int
    err_median_mm: float
    err_p90_mm: float
    share_under_limit: float
    limit_mm: float


@dataclass(frozen=True)
class Frame:
    """scale — мм на пункт PDF (калибровка листа), (ox, oy) — начало DXF на листе, пт.

    Локальные координаты = координаты DXF минус (x0, y0): все растры строятся в них.
    """

    scale: float
    ox: float
    oy: float
    x0: float
    y0: float

    def pt_to_local(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.ox) * self.scale - self.x0, (self.oy - y) * self.scale - self.y0)

    def pts_to_dxf(self, pts: Arr2) -> Arr2:
        out = np.empty_like(pts)
        out[:, 0] = (pts[:, 0] - self.ox) * self.scale
        out[:, 1] = (self.oy - pts[:, 1]) * self.scale
        return out

    def dxf_to_pt(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x / self.scale, self.oy - y / self.scale)

    def local_to_dxf(self, x: float, y: float) -> tuple[float, float]:
        return (x + self.x0, y + self.y0)

    def dxf_to_local(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x0, y - self.y0)

    def with_local(self, x0: float, y0: float) -> Frame:
        return Frame(self.scale, self.ox, self.oy, x0, y0)


def _pick(points: Arr2, k: int) -> Arr2:
    """Детерминированная выборка k точек, равномерно по отсортированному списку."""
    order = np.lexsort((points[:, 1], points[:, 0]))
    idx = np.unique(np.linspace(0, len(points) - 1, num=min(k, len(points))).astype(np.int64))
    picked: Arr2 = points[order][idx]
    return picked


def find_frame(
    vertices_pt: Arr2, dxf_pts: Arr2, scale: float, params: Params
) -> tuple[Frame, TieStats]:
    """Находит начало DXF на листе по совпадению вершин векторов PDF и контуров стен DXF.

    Масштаб задан калибровкой листа (scale.json). Начало ищется голосованием: каждая из выбранных
    точек DXF «голосует» за начало, при котором она совпадает с вершиной PDF; затем проверка по
    случайным точкам: ошибка меньше допуска у подавляющего большинства, иначе frame_mismatch.
    """
    limit = params.num("tie_max_err_mm")
    if len(dxf_pts) < 4 or len(vertices_pt) < 4:
        raise MepError("frame_mismatch", "нет контуров стен DXF или векторов PDF для привязки")
    verts = np.unique(np.round(vertices_pt, 2), axis=0)
    bin_pt = params.num("tie_vote_bin_pt")
    samples = _pick(dxf_pts, params.count("tie_vote_samples"))
    keys: list[NDArray[np.int64]] = []
    cands: list[Arr2] = []
    for x, y in samples:
        c = np.stack([verts[:, 0] - x / scale, verts[:, 1] + y / scale], axis=1)
        cands.append(c)
        q = np.floor(c / bin_pt).astype(np.int64) + (1 << 30)
        keys.append(q[:, 0] * (1 << 31) + q[:, 1])
    uniq, counts = np.unique(np.concatenate(keys), return_counts=True)
    best = int(np.argmax(counts))
    voters = int(counts[best])
    if voters < params.count("tie_min_votes"):
        raise MepError(
            "frame_mismatch",
            f"контуры стен DXF не совпали с векторами PDF (голосов {voters}, масштаб {scale})",
        )
    kx, ky = divmod(int(uniq[best]), 1 << 31)
    centre = np.array([(kx - (1 << 30) + 0.5) * bin_pt, (ky - (1 << 30) + 0.5) * bin_pt])
    near = np.concatenate([c[np.all(np.abs(c - centre) < 1.5 * bin_pt, axis=1)] for c in cands])
    ox, oy = (float(v) for v in np.median(near, axis=0))
    frame = Frame(scale, ox, oy, 0.0, 0.0)
    stats = _verify(frame, verts, dxf_pts, voters, limit, params)
    # уточнение: остаток медианного смещения по близким совпадениям
    ref = _residual_shift(frame, verts, dxf_pts, params)
    if ref is not None:
        frame = Frame(scale, ox + ref[0] / scale, oy - ref[1] / scale, 0.0, 0.0)
        stats = _verify(frame, verts, dxf_pts, voters, limit, params)
    if not (
        stats.share_under_limit >= params.num("tie_min_share")
        and stats.err_median_mm <= params.num("tie_median_max_mm")
    ):
        raise MepError(
            "frame_mismatch",
            f"привязка PDF->DXF не прошла проверку: медиана {stats.err_median_mm:.1f} мм, "
            f"доля в допуске {stats.share_under_limit:.2f}",
        )
    return frame, stats


def _check_points(dxf_pts: Arr2, n: int) -> Arr2:
    idx = np.unique(np.linspace(0, len(dxf_pts) - 1, num=min(n, len(dxf_pts))).astype(np.int64))
    out: Arr2 = dxf_pts[idx]
    return out


def _nearest(frame: Frame, verts: Arr2, dxf_pts: Arr2, params: Params) -> tuple[Arr2, Arr2]:
    """(контрольные точки DXF, вектор до ближайшей вершины PDF в мм)."""
    check = _check_points(dxf_pts, params.count("tie_check_points"))
    vmm = frame.pts_to_dxf(verts)
    tree = shapely.STRtree(np.asarray(shapely.points(vmm)))
    idx = tree.query_nearest(np.asarray(shapely.points(check)), all_matches=False)
    delta: Arr2 = vmm[idx[1]] - check[idx[0]]
    return check[idx[0]], delta


def _verify(
    frame: Frame, verts: Arr2, dxf_pts: Arr2, voters: int, limit: float, params: Params
) -> TieStats:
    _, delta = _nearest(frame, verts, dxf_pts, params)
    err = np.hypot(delta[:, 0], delta[:, 1])
    return TieStats(
        voters,
        len(err),
        float(np.median(err)),
        float(np.percentile(err, 90)),
        float((err < limit).mean()),
        limit,
    )


def _residual_shift(
    frame: Frame, verts: Arr2, dxf_pts: Arr2, params: Params
) -> tuple[float, float] | None:
    _, delta = _nearest(frame, verts, dxf_pts, params)
    close = np.hypot(delta[:, 0], delta[:, 1]) < params.num("tie_refine_radius_mm")
    if int(close.sum()) < 8:
        return None
    sx, sy = np.median(delta[close], axis=0)
    # delta = (вершина PDF в мм) - (точка DXF): сдвинуть начало так, чтобы delta -> 0
    return (float(sx), float(sy))
