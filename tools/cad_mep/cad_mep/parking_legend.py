"""Легенда машиномест и классификация места по содержимому (глиф машины, штриховка).

Символ легенды — серый прямоугольник из 4 линий с глифом внутри, вне рамки плана; подпись — слова
справа от него в экранных координатах. Место относится к типу символа, чьё содержимое (растр в
системе координат места) похоже сильнее всего. Только numpy: scipy в образе исполнителя нет.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cad_mep import parking_const as pc
from cad_mep.pdfsrc import GrayPath, ParkingPage, WordPt

F64 = NDArray[np.float64]
BoolGrid = NDArray[np.bool_]
Zone = tuple[float, float, float, float]
Box = tuple[float, float, float, float]

UNKNOWN = "unknown"
NO_LEGEND_NOTE = "легенда машиномест не найдена"
_QUOTES = re.compile("[\"«»“”'`]")


@dataclass(frozen=True)
class Template:
    """Символ легенды: растр содержимого, признак штриховки, тип и подпись."""

    grid: BoolGrid
    hatch: bool
    parking_type: str
    label: str


@dataclass(frozen=True)
class Classified:
    parking_type: str
    label: str | None
    margin: float | None
    notes: list[str]


class PathIndex:
    """Серые пути страницы массивами: центры, габариты, признак штриховки."""

    def __init__(self, paths: list[GrayPath]) -> None:
        self.paths = paths
        bb = np.array([p.bbox for p in paths], dtype=np.float64).reshape(-1, 4)
        self.centers: F64 = np.stack([(bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2], axis=1)
        self.maxside: F64 = np.maximum(bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1])
        self.hatch = np.array([p.hatch for p in paths], dtype=np.bool_)


def rect_frame(corners: F64) -> tuple[F64, F64, F64, float, float]:
    """Центр, оси u (вдоль длинной стороны) и v, длина и ширина прямоугольника из 4 вершин."""
    e0 = corners[1] - corners[0]
    e1 = corners[2] - corners[1]
    if np.hypot(*e0) < np.hypot(*e1):
        e0, e1 = e1, e0
    length = float(np.hypot(*e0))
    u = e0 / length
    return corners.mean(axis=0), u, np.array([-u[1], u[0]]), length, float(np.hypot(*e1))


def inside_rect(idx: PathIndex, corners: F64, pad_pt: float) -> NDArray[np.int64]:
    """Номера путей, чей центр внутри прямоугольника (раздутого на pad) и габарит мельче рамки."""
    c, u, v, length, width = rect_frame(corners)
    rel = idx.centers - c
    ok = (np.abs(rel @ u) <= length / 2 + pad_pt) & (np.abs(rel @ v) <= width / 2 + pad_pt)
    ok &= idx.maxside <= pc.PIECE_MAX_RATIO * length
    return np.flatnonzero(ok)


def _sample(segs: F64, c: F64, u: F64, v: F64, length: float) -> F64:
    """Точки вдоль отрезков в системе места: (u, v) в долях длины места."""
    if len(segs) == 0:
        return np.zeros((0, 2))
    a, b = segs[:, :2], segs[:, 2:]
    n = np.maximum(2, (np.hypot(*(b - a).T) / length * pc.SAMPLES_PER_LENGTH).astype(np.int64))
    owner = np.repeat(np.arange(len(segs)), n)
    first = np.cumsum(n) - n
    t = (np.arange(int(n.sum())) - first[owner]) / (n[owner] - 1)
    p = a[owner] + (b - a)[owner] * t[:, None] - c
    return np.stack([p @ u, p @ v], axis=1) / length


def _dilate(g: BoolGrid) -> BoolGrid:
    d = g.copy()
    d[1:] |= g[:-1]
    d[:-1] |= g[1:]
    d[:, 1:] |= g[:, :-1]
    d[:, :-1] |= g[:, 1:]
    return d


def _grid(uv: F64) -> BoolGrid:
    g = np.zeros((pc.GRID_U, pc.GRID_V), dtype=np.bool_)
    if len(uv):
        iu = np.clip(((uv[:, 0] + 0.5) * pc.GRID_U).astype(np.int64), 0, pc.GRID_U - 1)
        iv = np.clip(((uv[:, 1] + pc.V_HALF) * 2 * pc.GRID_V).astype(np.int64), 0, pc.GRID_V - 1)
        g[iu, iv] = True
    return _dilate(g)


def content_grid(idx: PathIndex, corners: F64, pad_pt: float) -> tuple[BoolGrid, bool]:
    """Растр серого содержимого прямоугольника и признак штриховки (точек штриховки достаточно)."""
    c, u, v, length, _ = rect_frame(corners)
    sel = inside_rect(idx, corners, pad_pt)
    parts: dict[bool, list[F64]] = {False: [], True: []}
    for k in sel:
        p = idx.paths[int(k)]
        parts[p.hatch] += [p.segs, p.chords]
    gray = _sample(
        np.concatenate(parts[False]) if parts[False] else np.zeros((0, 4)), c, u, v, length
    )
    hatch = _sample(
        np.concatenate(parts[True]) if parts[True] else np.zeros((0, 4)), c, u, v, length
    )
    return _grid(gray), len(hatch) > pc.HATCH_POINTS_MIN


def similarity(a: BoolGrid, b: BoolGrid) -> float:
    """IoU растров, максимум по четырём отражениям (u, v): направление места не важно."""
    best = 0.0
    for fu in (False, True):
        for fv in (False, True):
            x = a[::-1] if fu else a
            x = x[:, ::-1] if fv else x
            best = max(best, int((x & b).sum()) / max(1, int((x | b).sum())))
    return best


def classify(idx: PathIndex, corners: F64, templates: list[Template]) -> Classified:
    """Тип места по легенде; запас — разрыв между лучшим типом и лучшим из остальных типов."""
    if not templates:
        return Classified(UNKNOWN, None, None, [NO_LEGEND_NOTE])
    grid, hatch = content_grid(idx, corners, pc.CONTENT_PAD_STALL_PT)
    scored = sorted(
        (
            (similarity(grid, t.grid) - (0.0 if hatch == t.hatch else pc.HATCH_MISMATCH_PENALTY), i)
            for i, t in enumerate(templates)
        ),
        reverse=True,
    )
    best = templates[scored[0][1]]
    rest = [
        (s, templates[i]) for s, i in scored[1:] if templates[i].parking_type != best.parking_type
    ]
    margin = scored[0][0] - (rest[0][0] if rest else 0.0)
    notes = []
    if rest and margin < pc.TYPE_MARGIN_MIN:
        notes.append(f"тип под вопросом: {rest[0][1].parking_type}")
    return Classified(best.parking_type, best.label, round(margin, 2), notes)


def parking_type(label: str) -> str | None:
    """Код типа по подписи легенды (регистр и кавычки не важны); None — не распознано."""
    s = _QUOTES.sub("", label.lower())
    guest = "гост" in s
    rules = (
        ("мгн" in s and ("м4" in s or "m4" in s), "mgn_m4"),
        ("мгн" in s, "mgn_m1_3"),
        ("large" in s and guest, "large_guest"),
        ("large" in s, "large"),
        ("medium" in s and guest, "medium_guest"),
        ("medium" in s, "medium"),
        (guest, "guest"),
        ("временн" in s, "temporary"),
        ("постоянн" in s, "permanent"),
    )
    return next((code for cond, code in rules if cond), None)


def _quad_at(segs: F64, r: int) -> F64 | None:
    """Вершины рамки по трём подряд идущим сторонам, начиная с r (четвёртая может не доходить)."""
    sel = np.roll(segs, -r, axis=0)[:3]
    if np.abs(sel[:2, 2:] - sel[1:, :2]).max() > pc.LEGEND_CLOSE_TOL_PT:
        return None
    vec = sel[:, 2:] - sel[:, :2]
    unit = vec / np.maximum(np.hypot(vec[:, 0], vec[:, 1]), 1e-9)[:, None]
    if np.abs((unit[:2] * unit[1:]).sum(axis=1)).max() > pc.LEGEND_RIGHT_SIN_MAX:
        return None
    return np.array([sel[0, :2], sel[1, :2], sel[2, :2], sel[2, 2:]])


def _quad(p: GrayPath) -> F64 | None:
    """Вершины прямоугольной рамки из 4 линий пути: три стороны подряд образуют цепочку с прямыми
    углами, у четвёртой стороны в чертеже бывает разрыв."""
    if len(p.segs) != 4 or len(p.chords):
        return None
    return next((q for r in range(4) if (q := _quad_at(p.segs, r)) is not None), None)


def legend_symbols(idx: PathIndex, zone: Zone) -> list[F64]:
    """Рамки символов легенды: серые прямоугольники с глифом вне рамки плана, без дублей."""
    out: list[F64] = []
    seen: set[tuple[float, float]] = set()
    for p in idx.paths:
        corners = None if p.hatch else _quad(p)
        if corners is None:
            continue
        c, _, _, length, width = rect_frame(corners)
        aspect = length / max(width, 1e-9)
        key = (round(float(c[0]), pc.LEGEND_KEY_DIGITS), round(float(c[1]), pc.LEGEND_KEY_DIGITS))
        in_plan = zone[0] <= c[0] <= zone[2] and zone[1] <= c[1] <= zone[3]
        if (
            in_plan
            or not pc.LEGEND_SIZE_MIN_PT <= length <= pc.LEGEND_SIZE_MAX_PT
            or not pc.LEGEND_ASPECT_MIN <= aspect <= pc.LEGEND_ASPECT_MAX
            or key in seen
        ):
            continue
        glyph = inside_rect(idx, corners, 0.0)
        if int((~idx.hatch[glyph]).sum()) >= pc.GLYPH_PIECES_MIN:
            seen.add(key)
            out.append(corners)
    return out


def _to_screen(page: ParkingPage, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = page.rotation
    return a * x + c * y + e, b * x + d * y + f


def _screen_box(
    page: ParkingPage, pts: list[tuple[float, float]]
) -> tuple[float, float, float, float]:
    s = [_to_screen(page, x, y) for x, y in pts]
    xs, ys = [p[0] for p in s], [p[1] for p in s]
    return min(xs), min(ys), max(xs), max(ys)


def _word_box(page: ParkingPage, w: WordPt) -> Box:
    return _screen_box(page, [(w.x0, w.y0), (w.x1, w.y0), (w.x1, w.y1), (w.x0, w.y1)])


def _read_order(words: list[tuple[Box, str]]) -> str:
    """Слова подписи в порядке чтения: строки сверху вниз, слова слева направо."""
    rows: list[list[tuple[Box, str]]] = []
    for item in sorted(words, key=lambda w: (w[0][1] + w[0][3]) / 2):
        cy, h = (item[0][1] + item[0][3]) / 2, item[0][3] - item[0][1]
        last = rows[-1][-1][0] if rows else None
        if last is not None and abs(cy - (last[1] + last[3]) / 2) <= pc.LABEL_LINE_TOL * h:
            rows[-1].append(item)
        else:
            rows.append([item])
    text = " ".join(w[1] for row in rows for w in sorted(row, key=lambda w: w[0][0]))
    return re.sub(r"^[-–—\s]+", "", re.sub(r"\s+", " ", text)).strip()


def _connected(
    items: list[tuple[Box, str]], right_edge: float, max_gap: float
) -> list[tuple[Box, str]]:
    """Слова, начинающиеся не дальше max_gap от символа или продолжающие свою строку."""
    kept: list[tuple[Box, str]] = []
    for item in sorted(items, key=lambda w: w[0][0]):
        box = item[0]
        h = box[3] - box[1]
        near = box[0] - right_edge <= max_gap
        chain = any(
            abs((k[1] + k[3]) / 2 - (box[1] + box[3]) / 2) <= pc.LABEL_LINE_TOL * h
            and 0.0 <= box[0] - k[2] <= pc.LABEL_WORD_GAP * h
            for k, _ in kept
        )
        if near or chain:
            kept.append(item)
    return kept


def symbol_labels(page: ParkingPage, symbols: list[F64]) -> list[str]:
    """Подпись каждого символа: слова справа от него (экранные координаты), в порядке чтения."""
    boxes = [_screen_box(page, [(float(x), float(y)) for x, y in s]) for s in symbols]
    mine: list[list[tuple[Box, str]]] = [[] for _ in symbols]
    for w in page.words:
        wb = _word_box(page, w)
        cy = (wb[1] + wb[3]) / 2
        best: tuple[tuple[int, float], int] | None = None
        for k, sb in enumerate(boxes):
            h = sb[3] - sb[1]
            gap = wb[0] - sb[2]
            dy = abs(cy - (sb[1] + sb[3]) / 2)
            if dy > pc.LABEL_HALF_BAND * h or gap < 0.0:
                continue
            key = (round(dy / (pc.LABEL_ROW_BIN * h)), gap)
            if best is None or key < best[0]:
                best = (key, k)
        if best is not None:
            mine[best[1]].append((wb, w.text))
    return [
        _read_order(_connected(m, sb[2], pc.LABEL_MAX_LENGTHS * rect_frame(s)[3]))
        for m, sb, s in zip(mine, boxes, symbols, strict=True)
    ]


def find_templates(page: ParkingPage, idx: PathIndex, zone: Zone) -> list[Template]:
    """Шаблоны типов по легенде листа; символ без распознанной подписи пропускается."""
    symbols = legend_symbols(idx, zone)
    out: list[Template] = []
    for sym, label in zip(symbols, symbol_labels(page, symbols), strict=True):
        code = parking_type(label)
        if code is None:
            continue
        grid, hatch = content_grid(idx, sym, pc.CONTENT_PAD_LEGEND_PT)
        out.append(Template(grid, hatch, code, label))
    return out
