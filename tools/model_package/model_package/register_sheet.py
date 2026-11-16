"""Привязка листа PDF к модели по подписям осей (`method: grid_labels`).

Подписи осей на листе (слова текста PDF и содержимое аннотаций, например «AutoCAD SHX Text»)
сопоставляются с сеткой grids.json. Оси `U` (постоянная X) дают линейную зависимость вдоль
одной оси листа, `V` - вдоль другой: `лист_pt = a · модель_мм + b`. Перебираются повороты
листа 0/90/180/270° (зеркал нет; ось Y листа направлена вниз). Подгонка принимается, если
масштабы по двум направлениям совпали в пределах 0,5 %, на каждое направление совпало
не меньше 5 осей и невязка каждой подписи не больше 1 pt. Координаты листа - пространство
неповёрнутой страницы PDF, как их отдаёт PyMuPDF.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import numpy as np

from .titles import match_storey, page_elevations, parse_titles

PT_PER_MM = 72.0 / 25.4
SCALE_RANGE = (PT_PER_MM / 2000.0, PT_PER_MM / 10.0)  # от 1:2000 до 1:10
LAT2CYR = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")
AXIS_PARALLEL = math.radians(1.0)
# поворот → ((ось листа для U, знак), (ось листа для V, знак)); 0 - u листа, 1 - v листа
ORIENTATIONS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    0: ((0, 1), (1, -1)),
    90: ((1, -1), (0, -1)),
    180: ((0, -1), (1, 1)),
    270: ((1, 1), (0, 1)),
}


@dataclass(frozen=True, slots=True)
class Options:
    min_matched: int = 5
    tol_pt: float = 1.0
    scale_tol: float = 0.005
    budget: int = 40_000
    keep: int = 12


@dataclass(frozen=True, slots=True)
class Label:
    text: str
    u: float
    v: float


@dataclass(frozen=True, slots=True)
class AxisFit:
    a: float
    b: float
    matched: dict[str, float]  # нормализованная подпись → наблюдаемая координата листа
    resid_pt: dict[str, float]

    @property
    def n(self) -> int:
        return len(self.matched)

    @property
    def max_resid(self) -> float:
        return max(self.resid_pt.values(), default=math.inf)


@dataclass(slots=True)
class GridTags:
    """Подписи осей по направлениям: нормализованная подпись → (подпись источника, координата)."""

    u: dict[str, tuple[str, float]] = field(default_factory=dict)
    v: dict[str, tuple[str, float]] = field(default_factory=dict)


def normalize_tag(text: str) -> str:
    """Латинские двойники кириллицы → кириллица, верхний регистр, без пробелов по краям."""
    return text.strip().translate(LAT2CYR).upper()


def grid_tags(grids: dict[str, Any]) -> GridTags:
    """Оси, параллельные осям модели (в пределах 1°), с постоянной координатой."""
    out = GridTags()
    for axis in grids.get("axes", []):
        (x0, y0), (x1, y1) = axis["p0"], axis["p1"]
        length = math.hypot(x1 - x0, y1 - y0)
        if not axis.get("tag") or length == 0:
            continue
        tag = normalize_tag(axis["tag"])
        if axis["dir"] == "U" and abs(x1 - x0) <= length * math.sin(AXIS_PARALLEL):
            out.u.setdefault(tag, (axis["tag"], (x0 + x1) / 2))
        elif axis["dir"] == "V" and abs(y1 - y0) <= length * math.sin(AXIS_PARALLEL):
            out.v.setdefault(tag, (axis["tag"], (y0 + y1) / 2))
    return out


def page_labels(page: Any) -> list[Label]:
    """Слова страницы и короткие аннотации с центрами в pt неповёрнутой страницы."""
    labels = [
        Label(normalize_tag(w[4]), (w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
        for w in page.get_text("words")
        if w[4].strip()
    ]
    for annot in page.annots() or ():
        content = (annot.info or {}).get("content", "").strip()
        if content and len(content) <= 8:
            r = annot.rect
            labels.append(Label(normalize_tag(content), (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    return labels


def _occurrences(labels: Sequence[Label], tags: dict[str, Any], axis: int) -> dict[str, np.ndarray]:
    occ: dict[str, list[float]] = {t: [] for t in tags}
    for lab in labels:
        if lab.text in occ:
            occ[lab.text].append(lab.u if axis == 0 else lab.v)
    return {t: np.asarray(sorted(v)) for t, v in occ.items() if v}


def _hypotheses(c: np.ndarray, occ: list[np.ndarray], sign: int, opt: Options) -> np.ndarray:
    span = float(c.max() - c.min())
    pairs = [
        (i, j)
        for i in range(len(c))
        for j in range(i + 1, len(c))
        if abs(c[j] - c[i]) >= 0.25 * span > 0
    ]
    pairs.sort(key=lambda ij: (len(occ[ij[0]]) * len(occ[ij[1]]), -abs(c[ij[1]] - c[ij[0]])))
    out: list[np.ndarray] = []
    total = 0
    for i, j in pairs:
        a = (occ[j][None, :] - occ[i][:, None]) / (c[j] - c[i])
        b = occ[i][:, None] - a * c[i]
        ok = (np.sign(a) == sign) & (np.abs(a) >= SCALE_RANGE[0]) & (np.abs(a) <= SCALE_RANGE[1])
        h = np.column_stack([a[ok], b[ok]])
        out.append(h)
        total += len(h)
        if total >= opt.budget:
            break
    if not out:
        return np.empty((0, 2))
    return _dedupe(np.concatenate(out)[: opt.budget])


def _dedupe(hyp: np.ndarray) -> np.ndarray:
    key = np.column_stack([np.round(hyp[:, 0] * 1e6), np.round(hyp[:, 1] * 10)])
    _, idx = np.unique(key, axis=0, return_index=True)
    return hyp[np.sort(idx)]


def _score(hyp: np.ndarray, c: np.ndarray, padded: np.ndarray, tol: float) -> np.ndarray:
    """(число совпавших подписей, сумма невязок) для каждой гипотезы."""
    t, k = padded.shape
    chunk = max(1, 2_000_000 // max(1, t * k))
    counts = np.zeros(len(hyp))
    errs = np.zeros(len(hyp))
    for s in range(0, len(hyp), chunk):
        h = hyp[s : s + chunk]
        pred = h[:, :1] * c[None, :] + h[:, 1:]
        d = np.abs(padded[None, :, :] - pred[:, :, None])
        d = np.where(np.isnan(d), np.inf, d).min(axis=2)
        inl = d <= tol
        counts[s : s + chunk] = inl.sum(axis=1)
        errs[s : s + chunk] = np.where(inl, d, 0.0).sum(axis=1)
    return np.column_stack([counts, errs])


def _refine(
    a: float, b: float, tags: list[str], c: np.ndarray, occ: list[np.ndarray], tol: float
) -> AxisFit | None:
    for _ in range(3):
        obs: dict[int, float] = {}
        for i, o in enumerate(occ):
            near = o[np.abs(o - (a * c[i] + b)) <= tol]
            if len(near):
                obs[i] = float(near.mean())
        if len(obs) < 2:
            return None
        xs = np.array([c[i] for i in obs])
        ys = np.array(list(obs.values()))
        a, b = (float(v) for v in np.polyfit(xs, ys, 1))
    matched = {tags[i]: y for i, y in obs.items()}
    resid = {tags[i]: abs(a * c[i] + b - y) for i, y in obs.items()}
    return AxisFit(a, b, matched, resid)


def _distinct(hyp: np.ndarray, c: np.ndarray, order: np.ndarray, opt: Options) -> list[int]:
    """Лучшие гипотезы без почти-повторов (предсказания отличаются меньше допуска)."""
    picked: list[int] = []
    preds: list[np.ndarray] = []
    for idx in order[: opt.keep * 200]:
        pred = hyp[idx, 0] * c + hyp[idx, 1]
        if all(np.abs(pred - p).max() >= opt.tol_pt for p in preds):
            picked.append(int(idx))
            preds.append(pred)
            if len(picked) >= opt.keep * 2:
                break
    return picked


def fit_direction(
    coords: dict[str, float], occ: dict[str, np.ndarray], sign: int, opt: Options
) -> list[AxisFit]:
    """Лучшие подгонки `лист = a·модель + b` для одного направления сетки и оси листа."""
    tags = sorted(t for t in coords if t in occ)
    if len(tags) < 2:
        return []
    c = np.array([coords[t] for t in tags], dtype=float)
    lists = [occ[t] for t in tags]
    hyp = _hypotheses(c, lists, sign, opt)
    if not len(hyp):
        return []
    width = max(len(o) for o in lists)
    padded = np.full((len(tags), width), np.nan)
    for i, o in enumerate(lists):
        padded[i, : len(o)] = o
    score = _score(hyp, c, padded, opt.tol_pt)
    order = _distinct(hyp, c, np.lexsort((score[:, 1], -score[:, 0])), opt)
    fits: dict[tuple[str, ...], AxisFit] = {}
    for idx in order:
        fit = _refine(float(hyp[idx, 0]), float(hyp[idx, 1]), tags, c, lists, opt.tol_pt)
        if fit is None:
            continue
        key = (*sorted(fit.matched), str(round(fit.a, 6)))
        fits.setdefault(key, fit)
    ranked = sorted(fits.values(), key=lambda f: (-f.n, f.max_resid))
    return ranked[: opt.keep]


@dataclass(slots=True)
class _Candidate:
    orientation: int
    fu: AxisFit
    fv: AxisFit
    reasons: list[str]

    @property
    def total(self) -> int:
        return self.fu.n + self.fv.n


def _scale_gap(fu: AxisFit, fv: AxisFit) -> float:
    au, av = abs(fu.a), abs(fv.a)
    return abs(au - av) / ((au + av) / 2)


def _reasons(fu: AxisFit, fv: AxisFit, n_u: int, n_v: int, opt: Options) -> list[str]:
    out: list[str] = []
    if fu.n < opt.min_matched:
        out.append(f"оси U: совпало {fu.n} из {n_u}, нужно не меньше {opt.min_matched}")
    if fv.n < opt.min_matched:
        out.append(f"оси V: совпало {fv.n} из {n_v}, нужно не меньше {opt.min_matched}")
    gap = _scale_gap(fu, fv)
    if gap > opt.scale_tol:
        out.append(
            f"масштабы по U и V расходятся на {gap * 100:.2f} % (> {opt.scale_tol * 100:.1f} %)"
        )
    worst = max(fu.max_resid, fv.max_resid)
    if worst > opt.tol_pt:
        out.append(f"невязка {worst:.2f} pt больше {opt.tol_pt:.1f} pt")
    return out


def _best_pair(
    fus: list[AxisFit], fvs: list[AxisFit], orient: int, n_u: int, n_v: int, opt: Options
) -> _Candidate | None:
    best: _Candidate | None = None
    best_key: tuple[float, ...] = ()
    for fu in fus:
        for fv in fvs:
            reasons = _reasons(fu, fv, n_u, n_v, opt)
            key = (
                _scale_gap(fu, fv) <= opt.scale_tol,
                not reasons,
                fu.n + fv.n,
                -max(fu.max_resid, fv.max_resid),
            )
            if best is None or key > best_key:
                best, best_key = _Candidate(orient, fu, fv, reasons), key
    return best


def register_labels(labels: Sequence[Label], tags: GridTags, opt: Options) -> _Candidate | None:
    """Лучшая подгонка по всем поворотам листа или None, если подписей не хватило."""
    u_coords = {t: x for t, (_, x) in tags.u.items()}
    v_coords = {t: y for t, (_, y) in tags.v.items()}
    cache: dict[tuple[str, int, int], list[AxisFit]] = {}

    def fits(name: str, coords: dict[str, float], axis: int, sign: int) -> list[AxisFit]:
        if (name, axis, sign) not in cache:
            cache[(name, axis, sign)] = fit_direction(
                coords, _occurrences(labels, coords, axis), sign, opt
            )
        return cache[(name, axis, sign)]

    candidates = []
    for orient, ((ua, us), (va, vs)) in ORIENTATIONS.items():
        cand = _best_pair(
            fits("u", u_coords, ua, us),
            fits("v", v_coords, va, vs),
            orient,
            len(u_coords),
            len(v_coords),
            opt,
        )
        if cand is not None:
            candidates.append(cand)
    if not candidates:
        return None
    return max(
        candidates, key=lambda c: (not c.reasons, c.total, -max(c.fu.max_resid, c.fv.max_resid))
    )


def _placement(
    cand: _Candidate | None, tags: GridTags, pdf: str, page: int, size: tuple[float, float]
) -> dict[str, Any]:
    base: dict[str, Any] = {"pdf": pdf, "page": page, "method": "grid_labels"}
    if cand is None:
        return {
            **base,
            "sx": None,
            "sy": None,
            "scale_ratio": None,
            "matched_u": [],
            "matched_v": [],
            "resid_mm_max": None,
            "resid_mm_rms": None,
            "orientation": None,
            "ok": False,
            "reasons": ["подписи осей сетки на листе не найдены"],
            "affine": None,
            "page_size_pt": list(size),
        }
    fu, fv = cand.fu, cand.fv
    res_mm = [r / abs(fu.a) for r in fu.resid_pt.values()] + [
        r / abs(fv.a) for r in fv.resid_pt.values()
    ]
    (ua, _), (va, _) = ORIENTATIONS[cand.orientation]
    affine = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    affine[ua] = [fu.a, 0.0, fu.b]
    affine[va] = [0.0, fv.a, fv.b]
    return {
        **base,
        "sx": [fu.a, fu.b],
        "sy": [fv.a, fv.b],
        "scale_ratio": round(PT_PER_MM / ((abs(fu.a) + abs(fv.a)) / 2), 1),
        "matched_u": [tags.u[t][0] for t in sorted(fu.matched, key=lambda t: tags.u[t][1])],
        "matched_v": [tags.v[t][0] for t in sorted(fv.matched, key=lambda t: tags.v[t][1])],
        "resid_mm_max": round(max(res_mm), 2),
        "resid_mm_rms": round(math.sqrt(sum(r * r for r in res_mm) / len(res_mm)), 2),
        "orientation": cand.orientation,
        "ok": not cand.reasons,
        "reasons": cand.reasons,
        "affine": affine,
        "page_size_pt": list(size),
    }


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def register_page(
    page: Any, grids: dict[str, Any], pdf_name: str, page_index: int, opt: Options | None = None
) -> dict[str, Any]:
    """Привязка открытой страницы PyMuPDF к сетке осей."""
    tags = grid_tags(grids)
    cand = register_labels(page_labels(page), tags, opt or Options())
    size = (float(page.cropbox.width), float(page.cropbox.height))
    return _placement(cand, tags, pdf_name, page_index, size)


def register_sheet(
    grids: dict[str, Any] | Path | str,
    pdf: Path | str,
    page: int,
    opt: Options | None = None,
) -> dict[str, Any]:
    """placement.json для одной страницы: `лист_pt = a · модель_мм + b` по sx и sy."""
    grid_data = grids if isinstance(grids, dict) else load_json(Path(grids))
    with fitz.open(str(pdf)) as doc:
        if not 0 <= page < len(doc):
            raise ValueError(f"в PDF {len(doc)} страниц, страницы {page} нет")
        return register_page(doc[page], grid_data, Path(pdf).name, page, opt)


def _page_text(page: Any) -> str:
    notes = [(a.info or {}).get("content", "") for a in page.annots() or ()]
    return page.get_text() + "\n" + "\n".join(notes)


def register_all(
    grids: dict[str, Any],
    storeys: list[dict[str, Any]],
    pdf: Path | str,
    opt: Options | None = None,
) -> list[dict[str, Any]]:
    """Все страницы: заголовок «План … на отм.», этажи по отметке, привязка по осям."""
    rows: list[dict[str, Any]] = []
    with fitz.open(str(pdf)) as doc:
        for index, page in enumerate(doc):
            titles = parse_titles(_page_text(page))
            if not titles:
                rows.append({"page": index, "plan": False})
                continue
            matches = [match_storey(e, storeys) for e in page_elevations(titles)]
            placement = register_page(page, grids, Path(pdf).name, index, opt)
            rows.append(
                {
                    "page": index,
                    "plan": True,
                    "title": titles[0].text[:120],
                    "storeys": [
                        {
                            "elevation_mm": m.elevation_mm,
                            "storey_key": m.storey["storey_key"] if m.storey else None,
                            "storey_name": m.storey["name"] if m.storey else None,
                            "delta_mm": m.delta_mm,
                            "candidates": [c["storey_key"] for c in m.candidates],
                        }
                        for m in matches
                    ],
                    "warnings": [w for m in matches for w in m.warnings],
                    "placement": placement,
                }
            )
    return rows


def format_table(rows: list[dict[str, Any]]) -> str:
    """Таблица «страница → этаж → успех/невязка» для консоли."""
    head = (
        f"{'стр':>3}  {'отметка':>8}  {'этаж':<34} {'Δ,мм':>6}  {'ок':<3} {'U/V':>5} "
        f"{'1:N':>6} {'макс,мм':>7}  примечание"
    )
    lines = [head, "-" * len(head)]
    for row in rows:
        if not row["plan"]:
            lines.append(f"{row['page']:>3}  {'':>8}  {'(не план этажа)':<34}")
            continue
        p = row["placement"]
        uv = f"{len(p['matched_u'])}/{len(p['matched_v'])}"
        scale = f"{p['scale_ratio']:.1f}" if p["scale_ratio"] else "-"
        resid = f"{p['resid_mm_max']:.1f}" if p["resid_mm_max"] is not None else "-"
        note = "; ".join(row["warnings"] + p["reasons"])
        for i, st in enumerate(row["storeys"]):
            name = st["storey_name"] or ("неоднозначно" if len(st["candidates"]) > 1 else "нет")
            delta = f"{st['delta_mm']:+.0f}" if st["delta_mm"] is not None else "-"
            ok = ("да" if p["ok"] else "нет") if i == 0 else ""
            lines.append(
                f"{row['page']:>3}  {st['elevation_mm'] / 1000:>+8.3f}  {name[:34]:<34} "
                f"{delta:>6}  {ok:<3} {uv if i == 0 else '':>5} {scale if i == 0 else '':>6} "
                f"{resid if i == 0 else '':>7}  {note if i == 0 else ''}"
            )
    return "\n".join(lines)
