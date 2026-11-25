"""Синтетический лист плана: оси с марками в кружках, стены, штриховка и ложные подписи.

Ложные подписи: экспликация (столбец номеров 1-9), «ложный ряд» тех же цифр в масштабе 1:200
(даёт свою линейную подгонку по 9 подписям) и разбросанные номера помещений. Текст ставится
шрифтом с кириллицей так, чтобы центр рамки слова совпал с расчётной точкой.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz

PT_PER_MM = 72.0 / 25.4
A_100 = PT_PER_MM / 100.0
U_TAGS = {
    "1": 0.0,
    "2": 4200.0,
    "3": 8400.0,
    "4": 12000.0,
    "5": 16800.0,
    "6": 21000.0,
    "7": 24600.0,
    "8": 29400.0,
    "9": 33600.0,
}
V_TAGS = {"А": 0.0, "Б": 4800.0, "В": 9000.0, "Г": 12600.0, "Д": 18000.0, "Е": 22800.0}
EXT = 3000.0
FONT = fitz.Font("cjk")

Transform = Callable[[float, float], tuple[float, float]]


@dataclass(frozen=True)
class SheetTruth:
    orientation: int
    a: float
    bu: float  # смещение по оси листа, на которую ложится X модели
    bv: float  # то же для Y модели


def grids_dict(u_tags: dict[str, float] | None = None) -> dict[str, object]:
    u_tags = U_TAGS if u_tags is None else u_tags
    ys = (min(V_TAGS.values()) - EXT, max(V_TAGS.values()) + EXT)
    xs = (min(u_tags.values()) - EXT, max(u_tags.values()) + EXT)
    axes = [{"tag": t, "dir": "U", "p0": [x, ys[0]], "p1": [x, ys[1]]} for t, x in u_tags.items()]
    axes += [{"tag": t, "dir": "V", "p0": [xs[0], y], "p1": [xs[1], y]} for t, y in V_TAGS.items()]
    return {"source": "IfcGrid", "axes": axes}


def transform(orientation: int, a: float, ou: float, ov: float) -> Transform:
    """Модель (мм) → лист (pt) для поворота листа; ou/ov - смещения по u и v листа."""
    table: dict[int, Transform] = {
        0: lambda x, y: (a * x + ou, -a * y + ov),
        90: lambda x, y: (-a * y + ou, -a * x + ov),
        180: lambda x, y: (-a * x + ou, a * y + ov),
        270: lambda x, y: (a * y + ou, a * x + ov),
    }
    return table[orientation]


def put_text(page: fitz.Page, text: str, u: float, v: float, size: float = 10.0) -> None:
    width = FONT.text_length(text, fontsize=size)
    baseline = v + (FONT.ascender + FONT.descender) / 2 * size
    page.insert_text((u - width / 2, baseline), text, fontname="F0", fontsize=size)


def _axes(page: fitz.Page, tr: Transform, grids: dict[str, object], labels: bool) -> None:
    for axis in grids["axes"]:  # type: ignore[union-attr]
        p0, p1 = fitz.Point(*tr(*axis["p0"])), fitz.Point(*tr(*axis["p1"]))
        page.draw_line(p0, p1, color=(0.3, 0.3, 0.3), width=0.3, dashes="[8 3 1 3] 0")
        if not labels:
            continue
        d = (p1 - p0) / abs(p1 - p0)
        for end, sign in ((p0, -1.0), (p1, 1.0)):
            c = end + d * (12.0 * sign)
            page.draw_circle(c, 8.0, color=(0, 0, 0), width=0.4)
            put_text(page, axis["tag"], c.x, c.y)


def _building(page: fitz.Page, tr: Transform, rng: random.Random) -> None:
    xs, ys = list(U_TAGS.values()), list(V_TAGS.values())
    corners = [tr(xs[0], ys[0]), tr(xs[-1], ys[-1])]
    rect = fitz.Rect(*corners[0], *corners[1]).normalize()
    page.draw_rect(rect, color=(0, 0, 0), width=1.5)
    step = 6.0
    k = rect.x0 - rect.height
    while k < rect.x1:
        a = fitz.Point(max(k, rect.x0), rect.y1 - max(0.0, rect.x0 - k))
        b = fitz.Point(min(k + rect.height, rect.x1), rect.y0 + max(0.0, k + rect.height - rect.x1))
        page.draw_line(a, b, color=(0.6, 0.6, 0.6), width=0.2)
        k += step
    for x in xs[1:-1]:
        u0, v0 = tr(x - 100, ys[0])
        u1, v1 = tr(x + 100, ys[-1])
        page.draw_rect(fitz.Rect(u0, v0, u1, v1).normalize(), color=(0, 0, 0), fill=(0.2, 0.2, 0.2))
    for _ in range(60):
        u = rng.uniform(rect.x0 + 10, rect.x1 - 10)
        v = rng.uniform(rect.y0 + 10, rect.y1 - 10)
        put_text(page, rng.choice(["1", "2", "3", "5", "7", "9", "Б", "В", "12", "3.05"]), u, v, 7)


def _decoys(page: fitz.Page, width: float) -> None:
    x0 = width - 160.0
    for i in range(1, 10):
        put_text(page, str(i), x0, 200.0 + 18.0 * i, 8)
        put_text(page, f"{10 + 2.5 * i:.1f}", x0 + 60.0, 200.0 + 18.0 * i, 8)
    fake = transform(0, A_100 / 2, 900.0, 0.0)
    for tag, x in U_TAGS.items():
        u, _ = fake(x, 0.0)
        put_text(page, tag, u, 80.0, 9)


def make_sheet(
    path: Path,
    *,
    orientation: int = 0,
    labels: bool = True,
    decoys: bool = True,
    grids: dict[str, object] | None = None,
    title: str | None = "План 1 этажа, на отм. ±0.000",
    extra_pages: list[str] | None = None,
    seed: int = 7,
) -> SheetTruth:
    """PDF 2384×1684 pt с одним листом плана (и, при желании, страницами-заглушками)."""
    width, height = 2384.0, 1684.0
    ou, ov = {0: (400.0, 1350.0), 90: (1500.0, 1450.0), 180: (1700.0, 300.0), 270: (400.0, 300.0)}[
        orientation
    ]
    tr = transform(orientation, A_100, ou, ov)
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_font(fontname="F0", fontbuffer=FONT.buffer)
    rng = random.Random(seed)  # noqa: S311 - воспроизводимые тестовые данные
    _building(page, tr, rng)
    _axes(page, tr, grids or grids_dict(), labels)
    if decoys:
        _decoys(page, width)
    if title:
        put_text(page, title, width - 400.0, height - 60.0, 14)
    for text in extra_pages or []:
        extra = doc.new_page(width=width, height=height)
        extra.insert_font(fontname="F0", fontbuffer=FONT.buffer)
        put_text(extra, text, width / 2, height / 2, 14)
    doc.save(str(path))
    doc.close()
    bu, bv = (ou, ov) if orientation in (0, 180) else (ov, ou)
    return SheetTruth(orientation, A_100, bu, bv)
