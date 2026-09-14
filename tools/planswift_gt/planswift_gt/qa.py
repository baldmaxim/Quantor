"""Визуальная проверка ground truth: оверлеи листов и проверка совмещения с растром.

Оверлей — уменьшенный растр листа (осветлён, чтобы разметка читалась) и поверх него:

```text
контур площади     синий, сплошной
отверстие          красный, штрих
осевая линия       зелёный
точка счёта        пурпурный крест
debug-вариант      + порядковый номер аннотации у первой точки и легенда номер → id
```

Картинки — частные артефакты рядом с датасетом, не в git.

**Совмещение.** Человек смотрит оверлеи; до него машина отвечает на узкий вопрос: лежит ли разметка
на линиях чертежа именно в своих координатах. Вдоль рёбер берутся точки, и для сетки сдвигов
считается доля точек рядом с тёмным пикселем. Верные координаты дают пик в нулевом сдвиге; ошибка
масштаба, перевёрнутая ось или чужой лист — пик в стороне или его отсутствие. Это свидетельство,
а не замена просмотра глазами.
"""

from __future__ import annotations

import json
import statistics
from collections import OrderedDict
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from planswift_gt.raster import DARK_BELOW, TiffRaster, downscale, write_png

JsonObject = dict[str, object]

COLORS: dict[str, tuple[int, int, int]] = {
    "polygon": (30, 90, 220),
    "polygon_hole": (220, 40, 40),
    "polyline": (20, 160, 60),
    "count": (200, 30, 200),
}
LABEL_COLOR = (0, 0, 0)

# Цифры 3×5 для номеров аннотаций: шрифтов в стандартной библиотеке нет, а номер должен читаться.
_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


class Canvas:
    def __init__(self, width: int, height: int, gray: bytes) -> None:
        self.width = width
        self.height = height
        # Осветление: чертёж — фон, разметка должна читаться поверх любых линий.
        light = gray.translate(bytes(150 + value * 105 // 255 for value in range(256)))
        self.rgb = bytearray(len(light) * 3)
        self.rgb[0::3] = light
        self.rgb[1::3] = light
        self.rgb[2::3] = light

    def dot(self, x: int, y: int, color: tuple[int, int, int], size: int = 1) -> None:
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                px, py = x + dx, y + dy
                if 0 <= px < self.width and 0 <= py < self.height:
                    offset = (py * self.width + px) * 3
                    self.rgb[offset : offset + 3] = bytes(color)

    def line(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        color: tuple[int, int, int],
        *,
        dashed: bool = False,
        size: int = 1,
    ) -> None:
        x0, y0, x1, y1 = round(a[0]), round(a[1]), round(b[0]), round(b[1])
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for index in range(steps + 1):
            if dashed and (index // 6) % 2 == 1:
                continue
            t = index / steps
            self.dot(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), color, size)

    def cross(self, x: float, y: float, color: tuple[int, int, int]) -> None:
        cx, cy = round(x), round(y)
        self.line((cx - 6, cy - 6), (cx + 6, cy + 6), color)
        self.line((cx - 6, cy + 6), (cx + 6, cy - 6), color)

    def number(self, value: int, x: float, y: float) -> None:
        cursor = round(x) + 4
        top = round(y) - 12
        for char in str(value):
            for row, pattern in enumerate(_DIGITS[char]):
                for column, bit in enumerate(pattern):
                    if bit == "1":
                        for sy in range(2):
                            for sx in range(2):
                                self.dot(
                                    cursor + column * 2 + sx, top + row * 2 + sy, LABEL_COLOR, 0
                                )
            cursor += 8

    def save(self, path: Path) -> None:
        write_png(path, self.width, self.height, self.rgb)


def _pairs(value: object) -> list[tuple[float, float]]:
    """Точки аннотации из JSON: список пар чисел, иначе пусто."""
    if not isinstance(value, list):
        return []
    return [
        (float(point[0]), float(point[1]))
        for point in value
        if isinstance(point, list) and len(point) == 2
    ]


def _annotations_by_page(dataset: Path) -> OrderedDict[str, list[JsonObject]]:
    grouped: OrderedDict[str, list[JsonObject]] = OrderedDict()
    for line in (dataset / "annotations.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        grouped.setdefault(str(row["page"]["page_guid"]), []).append(row["annotation"])
    return grouped


def _pages(dataset: Path) -> list[JsonObject]:
    return [
        json.loads(line)
        for line in (dataset / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def render_page(
    raster: TiffRaster,
    annotations: list[JsonObject],
    out_path: Path,
    *,
    max_side: int,
    debug: bool,
) -> dict[int, str]:
    gray = downscale(raster, max_side=max_side)
    canvas = Canvas(gray.width, gray.height, gray.pixels)
    sx = raster.width / gray.step
    sy = raster.height / gray.step
    legend: dict[int, str] = {}
    # Отверстия поверх контуров, счёт поверх всего: мелкое не прячется под крупным.
    order = {"polygon": 0, "polyline": 1, "polygon_hole": 2, "count": 3}
    ordered = sorted(enumerate(annotations, start=1), key=lambda item: order[str(item[1]["kind"])])
    for number, annotation in ordered:
        kind = str(annotation["kind"])
        color = COLORS[kind]
        points = [(x * sx, y * sy) for x, y in _pairs(annotation["points_normalized"])]
        if kind == "count":
            for x, y in points:
                canvas.cross(x, y, color)
        else:
            closed = kind in ("polygon", "polygon_hole")
            pairs = list(
                zip(points, points[1:] + points[:1] if closed else points[1:], strict=False)
            )
            for a, b in pairs:
                canvas.line(a, b, color, dashed=kind == "polygon_hole")
        if debug:
            canvas.number(number, points[0][0], points[0][1])
            legend[number] = str(annotation["id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return legend


# ------------------------------------------------------------------------------ совмещение


@dataclass(frozen=True, slots=True)
class Alignment:
    samples: int
    score_at_zero: float
    best_offset_px: tuple[int, int]
    best_score: float
    median_score: float

    @property
    def aligned(self) -> bool:
        dx, dy = self.best_offset_px
        return (
            self.samples > 0
            and max(abs(dx), abs(dy)) <= ALIGN_TOLERANCE_PX
            and self.score_at_zero >= 1.5 * max(self.median_score, 1e-9)
        )


OFFSETS = tuple(range(-48, 49, 12))
ALIGN_TOLERANCE_PX = 12
SAMPLE_SPACING_PX = 8
MAX_SAMPLES = 4000
_PROBE = ((0, 0), (2, 0), (-2, 0), (0, 2), (0, -2))


def _samples(annotations: list[JsonObject], width: int, height: int) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for annotation in annotations:
        kind = annotation["kind"]
        if kind == "count":
            continue
        ring = _pairs(annotation["points_source_px"])
        if kind in ("polygon", "polygon_hole"):
            ring = [*ring, ring[0]]
        for (x0, y0), (x1, y1) in pairwise(ring):
            length = max(abs(x1 - x0), abs(y1 - y0))
            count = max(1, int(length // SAMPLE_SPACING_PX))
            for index in range(count):
                t = index / count
                points.append((round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t)))
    if len(points) > MAX_SAMPLES:
        stride = len(points) / MAX_SAMPLES
        points = [points[int(index * stride)] for index in range(MAX_SAMPLES)]
    margin = max(OFFSETS) + 3
    return [
        (x, y) for x, y in points if margin <= x < width - margin and margin <= y < height - margin
    ]


def alignment(raster: TiffRaster, annotations: list[JsonObject]) -> Alignment:
    samples = _samples(annotations, raster.width, raster.height)
    rows: OrderedDict[int, bytes] = OrderedDict()

    def dark(x: int, y: int) -> bool:
        line = rows.get(y)
        if line is None:
            line = raster.row(y)
            rows[y] = line
            if len(rows) > 4096:
                rows.popitem(last=False)
        return line[x] < DARK_BELOW

    scores: dict[tuple[int, int], float] = {}
    for dy in OFFSETS:
        for dx in OFFSETS:
            hits = sum(
                1 for x, y in samples if any(dark(x + dx + px, y + dy + py) for px, py in _PROBE)
            )
            scores[(dx, dy)] = hits / len(samples) if samples else 0.0
    best = max(scores, key=lambda key: (scores[key], -abs(key[0]) - abs(key[1])))
    return Alignment(
        samples=len(samples),
        score_at_zero=round(scores[(0, 0)], 4),
        best_offset_px=best,
        best_score=round(scores[best], 4),
        median_score=round(statistics.median(scores.values()), 4),
    )


def run(
    dataset: Path,
    source_root: Path,
    out_dir: Path,
    *,
    debug_pages: int,
    max_side: int,
) -> JsonObject:
    grouped = _annotations_by_page(dataset)
    pages = sorted(_pages(dataset), key=lambda page: str(page["page_guid"]))
    # Выборка debug-листов детерминирована: первые по GUID, а не случайные.
    debug_guids = {str(page["page_guid"]) for page in pages[:debug_pages]}
    report: list[JsonObject] = []
    probes: list[Alignment] = []
    for number, page in enumerate(pages, start=1):
        guid = str(page["page_guid"])
        image = page.get("image")
        if not isinstance(image, dict):
            report.append({"page": number, "page_guid": guid, "status": "no_image"})
            continue
        annotations = grouped.get(guid, [])
        path = source_root / str(image["path"])
        with TiffRaster(path, strip_cache=2) as raster:
            render_page(
                raster,
                annotations,
                out_dir / f"page-{number:03d}.png",
                max_side=max_side,
                debug=False,
            )
            legend: dict[int, str] = {}
            if guid in debug_guids:
                legend = render_page(
                    raster,
                    annotations,
                    out_dir / f"page-{number:03d}-debug.png",
                    max_side=max_side,
                    debug=True,
                )
            probe = alignment(raster, annotations)
        if probe.samples:
            probes.append(probe)
        entry: JsonObject = {
            "page": number,
            "page_guid": guid,
            "annotations": len(annotations),
            "alignment": {
                "samples": probe.samples,
                "score_at_zero": probe.score_at_zero,
                "best_offset_px": list(probe.best_offset_px),
                "best_score": probe.best_score,
                "median_score": probe.median_score,
                "aligned": probe.aligned,
            },
        }
        if legend:
            entry["debug_legend"] = {str(key): value for key, value in legend.items()}
        report.append(entry)

    summary: JsonObject = {
        "pages": len(report),
        "pages_with_geometry": len(probes),
        "pages_aligned": sum(1 for probe in probes if probe.aligned),
        "min_score_at_zero": min((probe.score_at_zero for probe in probes), default=None),
        "max_median_score": max((probe.median_score for probe in probes), default=None),
        "legend_colors": {
            kind: "#{:02x}{:02x}{:02x}".format(*color) for kind, color in COLORS.items()
        },
        "pages_report": report,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "qa-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
