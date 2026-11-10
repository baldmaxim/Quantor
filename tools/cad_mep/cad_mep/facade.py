"""Фасад: простенки и участки остекления вдоль контура здания, места приборов по модулям.

Контур здания разворачивается в одну ось s (мм вдоль контура). На каждом шаге по внутренней
нормали меряется глубина сплошного материала в полосе фасада: заливки стен PDF и штриховки
монолита, кладки и утеплителя DXF вида. Глубже порога — простенок, иначе — остекление.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray

from cad_mep.params import Params
from cad_mep.raster import BoolArr, label
from cad_mep.rooms import Model

IdxArr = NDArray[np.int64]
Pt = tuple[float, float]


@dataclass(frozen=True)
class Profile:
    ds: float  # длина шага вдоль контура, мм
    solid: BoolArr  # шаг контура занят простенком


@dataclass(frozen=True)
class Run:
    """Участок наружной стены помещения: связная полоса клеток на линии приборов."""

    ys: IdxArr
    xs: IdxArr
    rel: IdxArr  # шаг контура каждой клетки, считая от начала участка
    start: int  # шаг контура, с которого участок начинается
    count: int  # длина участка в шагах контура
    solid: BoolArr  # простенки на шагах участка

    def length(self, ds: float) -> float:
        return self.count * ds


@dataclass(frozen=True)
class Spot:
    """Место прибора: клетка линии приборов и участок, на середину которого он поставлен."""

    xy: Pt
    span_mm: float
    assumed: bool  # число приборов взято по шагу модулей, а не по простенкам


def _true_runs(flags: BoolArr) -> list[tuple[int, int]]:
    """Отрезки подряд идущих True: (начало, длина)."""
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b - a)) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def _drop_narrow(solid: BoolArr, min_bins: int) -> BoolArr:
    """Сплошные участки уже min_bins — импосты, а не простенки (контур замкнут)."""
    if not solid.any() or solid.all():
        return solid
    shift = int(np.argmin(solid))  # начинаем с остекления: ни один участок не разорван краем
    rolled = np.roll(solid, -shift)
    for a, ln in _true_runs(rolled):
        if ln < min_bins:
            rolled[a : a + ln] = False
    out: BoolArr = np.roll(rolled, shift)
    return out


def build_profile(m: Model, solid: BoolArr, params: Params) -> Profile:
    """Простенки вдоль контура здания: глубина сплошного материала в полосе фасада."""
    ext = m.hull.exterior
    step = m.gr.step
    n = max(int(ext.length // step), 1)
    ds = ext.length / n
    s = (np.arange(n) + 0.5) * ds
    here = shapely.get_coordinates(shapely.line_interpolate_point(ext, s))
    ahead = shapely.get_coordinates(shapely.line_interpolate_point(ext, (s + 1.0) % ext.length))
    tangent = ahead - here
    tangent /= np.maximum(np.hypot(tangent[:, 0], tangent[:, 1]), 1e-9)[:, None]
    sign = 1.0 if ext.is_ccw else -1.0  # внутренняя нормаль — слева при обходе против часовой
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1) * sign
    band = params.num("facade_band_mm") + params.num("device_offset_mm")
    depth = np.zeros(n)
    for d in np.arange(step / 2, band, step):
        q = here + normal * d
        ix = np.clip((q[:, 0] // step).astype(np.int64), 0, m.gr.nx - 1)
        iy = np.clip((q[:, 1] // step).astype(np.int64), 0, m.gr.ny - 1)
        depth += solid[iy, ix] * step
    piers = depth >= params.num("pier_min_depth_mm")
    return Profile(ds, _drop_narrow(piers, math.ceil(params.num("pier_min_width_mm") / ds)))


def comp_runs(m: Model, prof: Profile, cid: int, params: Params) -> list[Run]:
    """Участки наружной стены помещения — связные полосы клеток на линии приборов."""
    comp = m.comps[cid]
    step = m.gr.step
    band0 = params.num("facade_band_mm") + params.num("device_offset_mm")
    x0, y0 = int(comp.bbox[0] // step), int(comp.bbox[1] // step)
    x1, y1 = int(comp.bbox[2] // step) + 1, int(comp.bbox[3] // step) + 1
    ring = (m.lab[y0:y1, x0:x1] == cid) & (np.abs(m.edist[y0:y1, x0:x1] - band0) <= step)
    parts, count = label(ring, diagonal=True)
    n = len(prof.solid)
    min_cells = params.count("device_ring_min_cells")
    runs: list[Run] = []
    for k in range(1, count + 1):
        ys, xs = np.nonzero(parts == k)
        if len(ys) < min_cells:
            continue
        ys, xs = ys + y0, xs + x0
        pts = shapely.points(np.c_[(xs + 0.5) * step, (ys + 0.5) * step])
        along = np.asarray(shapely.line_locate_point(m.hull.exterior, pts), dtype=np.float64)
        bins: IdxArr = (along // prof.ds).astype(np.int64) % n
        used = np.unique(bins)
        # участок не замыкает контур: начинается сразу за самым длинным пустым промежутком
        gaps = np.diff(np.concatenate((used, [used[0] + n])))
        start = int(used[(int(np.argmax(gaps)) + 1) % len(used)])
        rel: IdxArr = (bins - start) % n
        # на остром углу здания полоса огибает угол, а шаги контура пропускаются: это две стены,
        # граница между ними — середина пропуска (угловой простенок достаётся обеим)
        steps = np.unique(rel)
        cuts = [
            (int(steps[c]) + int(steps[c + 1])) // 2
            for c in np.flatnonzero(np.diff(steps) * prof.ds > band0)
        ]
        lows = [0, *(c + 1 for c in cuts)]
        highs = [*cuts, int(steps[-1])]
        for lo, hi in zip(lows, highs, strict=True):
            part = (rel >= lo) & (rel <= hi)
            if int(part.sum()) < min_cells:
                continue
            solid = prof.solid[(start + lo + np.arange(hi - lo + 1)) % n]
            runs.append(
                Run(ys[part], xs[part], rel[part] - lo, (start + lo) % n, hi - lo + 1, solid)
            )
    runs.sort(key=lambda r: r.start)
    return runs


def _spot(m: Model, run: Run, at: float, band0: float) -> Pt:
    """Клетка участка, ближайшая к шагу at (вдоль контура), затем — к линии приборов."""
    along = np.abs(run.rel + 0.5 - at)
    off = np.abs(m.edist[run.ys, run.xs] - band0)
    k = int(np.lexsort((run.xs, run.ys, off, along))[0])
    return m.gr.xy(int(run.ys[k]), int(run.xs[k]))


def _even(
    m: Model, run: Run, a: int, ln: int, n: int, prof: Profile, band0: float, assumed: bool
) -> list[Spot]:
    """n приборов поровну на шагах [a, a + ln) участка."""
    return [
        Spot(_spot(m, run, a + ln * (k + 0.5) / n, band0), ln * prof.ds / n, assumed)
        for k in range(n)
    ]


def place(m: Model, prof: Profile, runs: list[Run], params: Params) -> list[Spot]:
    """Места приборов помещения: по одному на модуль остекления.

    Участок остекления между простенками не короче glazing_min_mm — прибор в его середине; длиннее
    glazing_module_max_mm — делится поровну. Простенков на стене нет — приборы по шагу модулей
    glazing_module_mm. Остекление не найдено вовсе — так же по самой длинной наружной стене.
    """
    ds = prof.ds
    module = params.num("glazing_module_mm")
    module_max = params.num("glazing_module_max_mm")
    min_len = params.num("glazing_min_mm")
    band0 = params.num("facade_band_mm") + params.num("device_offset_mm")
    spots: list[Spot] = []
    for run in runs:
        if not run.solid.any():
            if run.length(ds) >= min_len:
                n = math.ceil(run.length(ds) / module)
                spots += _even(m, run, 0, run.count, n, prof, band0, n > 1)
            continue
        for a, ln in _true_runs(~run.solid):
            if ln * ds >= min_len:
                n = math.ceil(ln * ds / module_max)
                spots += _even(m, run, a, ln, n, prof, band0, False)
    if not spots and runs:
        longest = max(runs, key=lambda r: (r.count, -r.start))
        if longest.length(ds) >= min_len:
            n = math.ceil(longest.length(ds) / module)
            spots = _even(m, longest, 0, longest.count, n, prof, band0, True)
    return spots


def facade_length(prof: Profile, runs: list[Run]) -> float:
    return float(sum(r.length(prof.ds) for r in runs))
