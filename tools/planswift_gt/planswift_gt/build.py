"""Сборщик датасета поверх `planswift-gt-v1`: тайлы, цели, замороженное разбиение, виды для Qwen.

```text
<out>/split.json               замороженное разбиение по листам и кластерам, с SHA-256
<out>/build.json               конфиг без путей, отпечатки, счётчики, проверки утечки
<out>/tiles.jsonl              тайл: часть, политика отбора, преобразование, доли цели и чернил
<out>/tiles/<id>.png           тайл рабочего растра (полутон 8 бит)
<out>/targets/slab/<id>.png    маска площади с отверстиями (0/255)
<out>/targets/masonry/<id>.png цель осевой: 255 на линии, спад до 0 на radius_px
<out>/views/<вид>.jsonl        qwen_slab_localization_v1, qwen_slab_polygon_v0, qwen_masonry_roi_v0
```

Главная истина оценки — векторная разметка `planswift-gt-v1`; растровые цели — только для обучения.

**Утечка.** Для val и test тайлы — вся сетка, построенная по размеру листа; разметка в отборе не
участвует. Для train разрешены положительные окна вокруг разметки и отбор негативов по чернилам.
Инструкции Qwen не содержат ни числа объектов, ни меток, ни имён; имена файлов непрозрачны.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from planswift_gt.buildconfig import BuildConfig, DatasetRef
from planswift_gt.geometry2d import (
    Point,
    Ring,
    centerline_target,
    fill_rings,
    interior_point,
    phash,
    point_in_rings,
    simplify,
)
from planswift_gt.raster import TiffRaster, downscale, working_page, write_png_gray
from planswift_gt.splits import PageInfo, assign, clusters, freeze
from planswift_gt.tiles import TileTransform, crop, grid_origins, stable_fraction, tile_id

JsonObject = dict[str, object]

INSTRUCTIONS = {
    "qwen_slab_localization_v1": (
        "Найди на изображении фрагмента чертежа все области монолитных плит. Верни строго JSON"
        ' {"objects": [{"class": "slab", "bbox": [x0, y0, x1, y1], "seed_points": [[x, y]]}]}'
        " с целыми координатами 0..1000 относительно этого изображения. Нет плит — пустой список."
    ),
    "qwen_slab_polygon_v0": (
        "Обведи на изображении фрагмента чертежа контуры монолитных плит с отверстиями."
        ' Верни строго JSON {"polygons": [{"outer": [[x, y], ...], "holes": [[[x, y], ...]]}]}'
        " с целыми"
        " координатами 0..1000 относительно этого изображения."
    ),
    "qwen_masonry_roi_v0": (
        "Есть ли на изображении фрагмента чертежа стены кладки? Верни строго JSON"
        ' {"contains_masonry": true|false, "roi": [x0, y0, x1, y1] | null,'
        ' "guide_points": [[x, y]]}'
        " с целыми координатами 0..1000 относительно этого изображения."
    ),
}


@dataclass(frozen=True, slots=True)
class PageShapes:
    polygons: list[list[Ring]]  # внешний контур + отверстия, рабочие пиксели
    polylines: list[list[Point]]


def _obj(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _jsonl(path: Path) -> list[JsonObject]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _dump(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _selected(annotation: JsonObject, kinds: tuple[str, ...], labels: tuple[str, ...]) -> bool:
    return annotation.get("kind") in kinds and (not labels or annotation.get("label_raw") in labels)


def _shapes(
    annotations: list[JsonObject], config: BuildConfig, source: tuple[int, int]
) -> PageShapes:
    """Геометрия листа в рабочих пикселях. Одинаковые секции-дубли входят один раз."""
    scale_x = source[0] / config.downsample
    scale_y = source[1] / config.downsample

    def ring(annotation: JsonObject) -> list[Point]:
        return [
            (float(p[0]) * scale_x, float(p[1]) * scale_y)
            for p in _list(annotation.get("points_normalized"))
            if isinstance(p, list) and len(p) == 2
        ]

    slab = config.targets.get("slab")
    masonry = config.targets.get("masonry")
    holes: dict[str, list[Ring]] = {}
    for annotation in annotations:
        if annotation.get("kind") == "polygon_hole":
            holes.setdefault(str(annotation.get("parent_annotation_id")), []).append(
                ring(annotation)
            )

    seen: set[str] = set()
    polygons: list[list[Ring]] = []
    polylines: list[list[Point]] = []
    for annotation in annotations:
        key = _dump([annotation.get("kind"), annotation.get("points_source_px")])
        if key in seen:
            continue
        seen.add(key)
        if (
            slab
            and annotation.get("kind") == "polygon"
            and _selected(annotation, slab.kinds, slab.labels)
        ):
            polygons.append([ring(annotation), *holes.get(str(annotation["id"]), [])])
        if masonry and _selected(annotation, masonry.kinds, masonry.labels):
            polylines.append(ring(annotation))
    return PageShapes(polygons, polylines)


# ------------------------------------------------------------------------------ виды Qwen


def _clip_box(rings: list[Ring], t: TileTransform) -> tuple[float, float, float, float] | None:
    xs = [x - t.x0 for x, _ in rings[0]]
    ys = [y - t.y0 for _, y in rings[0]]
    left, top = max(0.0, min(xs)), max(0.0, min(ys))
    right, bottom = min(float(t.valid_width), max(xs)), min(float(t.valid_height), max(ys))
    return (left, top, right, bottom) if right > left and bottom > top else None


def _seed(
    rings: list[Ring], box: tuple[float, float, float, float], t: TileTransform
) -> Point | None:
    shifted = [[(x - t.x0, y - t.y0) for x, y in ring] for ring in rings]
    left, top, right, bottom = box
    whole = interior_point(shifted)
    if whole is not None and left <= whole[0] <= right and top <= whole[1] <= bottom:
        return whole
    steps = 16
    for j in range(steps):
        for i in range(steps):
            candidate = (
                left + (right - left) * (i + 0.5) / steps,
                top + (bottom - top) * (j + 0.5) / steps,
            )
            if point_in_rings(candidate, shifted):
                return candidate
    return None


def slab_views(
    shapes: PageShapes, t: TileTransform, config: BuildConfig
) -> tuple[JsonObject, JsonObject | None]:
    scale = config.qwen_coordinate_range
    objects: list[JsonObject] = []
    polygons: list[JsonObject] = []
    complete = True
    budget = 0
    for rings in shapes.polygons:
        box = _clip_box(rings, t)
        if box is None:
            continue
        seed = _seed(rings, box, t)
        objects.append(
            {
                "class": "slab",
                "bbox": [*t.to_qwen(box[0], box[1], scale), *t.to_qwen(box[2], box[3], scale)],
                "seed_points": [list(t.to_qwen(seed[0], seed[1], scale))] if seed else [],
            }
        )
        xs = [x - t.x0 for ring in rings for x, _ in ring]
        ys = [y - t.y0 for ring in rings for _, y in ring]
        inside = (
            min(xs) >= 0 and min(ys) >= 0 and max(xs) <= t.valid_width and max(ys) <= t.valid_height
        )
        if not inside:
            complete = False
            continue
        simplified = [
            simplify(
                [(x - t.x0, y - t.y0) for x, y in ring],
                config.qwen_simplify_tolerance_px,
                closed=True,
            )
            for ring in rings
        ]
        budget += sum(len(ring) for ring in simplified)
        polygons.append(
            {
                "outer": [list(t.to_qwen(x, y, scale)) for x, y in simplified[0]],
                "holes": [
                    [list(t.to_qwen(x, y, scale)) for x, y in ring] for ring in simplified[1:]
                ],
            }
        )
    objects.sort(key=lambda item: _dump(item["bbox"]))
    localization: JsonObject = {"objects": objects}
    # Полигональный вид — только когда в тайле все фигуры целиком и укладываются в бюджет вершин.
    polygon: JsonObject | None = None
    if complete and budget <= config.qwen_polygon_max_vertices:
        polygon = {"polygons": polygons}
    return localization, polygon


def masonry_view(shapes: PageShapes, t: TileTransform, config: BuildConfig) -> JsonObject:
    scale = config.qwen_coordinate_range
    inside: list[Point] = []
    for line in shapes.polylines:
        for (x0, y0), (x1, y1) in pairwise(line):
            steps = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0)) / 8))
            for index in range(steps + 1):
                u = x0 + (x1 - x0) * index / steps - t.x0
                v = y0 + (y1 - y0) * index / steps - t.y0
                if 0 <= u <= t.valid_width and 0 <= v <= t.valid_height:
                    inside.append((u, v))
    if not inside:
        return {"contains_masonry": False, "roi": None, "guide_points": []}
    count = min(config.qwen_masonry_guide_points, len(inside))
    guides = [inside[round(i * (len(inside) - 1) / max(1, count - 1))] for i in range(count)]
    xs, ys = [u for u, _ in inside], [v for _, v in inside]
    return {
        "contains_masonry": True,
        "roi": [*t.to_qwen(min(xs), min(ys), scale), *t.to_qwen(max(xs), max(ys), scale)],
        "guide_points": [list(t.to_qwen(u, v, scale)) for u, v in guides],
    }


# ------------------------------------------------------------------------------ сборка


def _fraction_nonzero(pixels: bytes, valid: int) -> float:
    return 0.0 if valid == 0 else (len(pixels) - pixels.count(0)) / valid


def _ink_fraction(pixels: bytes, valid: int) -> float:
    dark = pixels.translate(bytes(1 if value < 128 else 0 for value in range(256)))
    return 0.0 if valid == 0 else sum(dark) / valid


def page_infos(config: BuildConfig) -> list[PageInfo]:
    infos: list[PageInfo] = []
    for dataset in config.datasets:
        root = Path(dataset.dataset_dir)
        weights: Counter[str] = Counter()
        for row in _jsonl(root / "annotations.jsonl"):
            annotation = _obj(row.get("annotation"))
            if any(
                _selected(annotation, config.targets[task].kinds, config.targets[task].labels)
                for task in dataset.tasks
            ):
                weights[str(_obj(row.get("page")).get("page_guid"))] += 1
        for page in _jsonl(root / "pages.jsonl"):
            image = page.get("image")
            if not isinstance(image, dict):
                continue
            with TiffRaster(
                Path(dataset.source_root) / str(image["path"]), strip_cache=1
            ) as raster:
                small = downscale(raster, max_side=256)
            infos.append(
                PageInfo(
                    project_key=dataset.project_key,
                    page_guid=str(page["page_guid"]),
                    image_sha256=str(image["sha256"]),
                    phash=phash(small.pixels, small.width, small.height),
                    weight=weights[str(page["page_guid"])],
                )
            )
    return infos


def select_train_negatives(
    negatives: list[tuple[str, float]], positives: int, config: BuildConfig, page_guid: str
) -> set[str]:
    """Негативы train: сначала «трудные» (много чернил — текст, размеры, штампы), затем пустые."""
    quota = math.ceil(config.train_negative_ratio * max(positives, 1))
    ordered = sorted(
        negatives,
        key=lambda item: (
            item[1] < config.hard_negative_ink_fraction,
            stable_fraction(config.seed, page_guid, item[0]),
        ),
    )
    return {identifier for identifier, _ in ordered[:quota]}


def build(config: BuildConfig, out: Path, *, refreeze: bool = False) -> JsonObject:
    infos = page_infos(config)
    groups = clusters(infos, config.phash_hamming_threshold)
    assignment = assign(groups, config.split_fractions, config.seed)
    frozen = freeze(
        out / "split.json",
        config_fingerprint=config.split_fingerprint(),
        seed=config.seed,
        groups=groups,
        assignment=assignment,
        refreeze=refreeze,
    )
    split_of = {
        f"{_obj(page).get('project_key')}|{_obj(page).get('page_guid')}": str(
            _obj(page).get("split")
        )
        for page in _list(frozen.get("pages"))
    }

    for folder in ("tiles", "targets/slab", "targets/masonry", "views"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    tile_rows: list[str] = []
    views: dict[str, list[str]] = {name: [] for name in INSTRUCTIONS}
    counters: Counter[str] = Counter()

    for dataset in config.datasets:
        _build_dataset(dataset, config, out, split_of, tile_rows, views, counters)

    (out / "tiles.jsonl").write_text(
        "".join(row + "\n" for row in sorted(tile_rows)), encoding="utf-8"
    )
    view_hashes: dict[str, str] = {}
    for name, rows in views.items():
        payload = "".join(row + "\n" for row in sorted(rows)).encode("utf-8")
        (out / "views" / f"{name}.jsonl").write_bytes(payload)
        view_hashes[name] = hashlib.sha256(payload).hexdigest()

    manifest: JsonObject = {
        "build_id": config.build_id,
        "source_format": "planswift-gt-v1",
        "holdout": frozen["holdout"],
        "split_sha256": frozen["sha256"],
        "config_fingerprint": config.fingerprint(),
        "projects": {d.project_key: list(d.tasks) for d in config.datasets},
        "tiling": {
            "downsample": config.downsample,
            "tile_px": config.tile_px,
            "overlap_px": config.overlap_px,
        },
        "counters": dict(sorted(counters.items())),
        "tiles_sha256": hashlib.sha256((out / "tiles.jsonl").read_bytes()).hexdigest(),
        "views_sha256": view_hashes,
        "leakage": leakage_report(out),
    }
    (out / "build.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _build_dataset(
    dataset: DatasetRef,
    config: BuildConfig,
    out: Path,
    split_of: dict[str, str],
    tile_rows: list[str],
    views: dict[str, list[str]],
    counters: Counter[str],
) -> None:
    root = Path(dataset.dataset_dir)
    by_page: dict[str, list[JsonObject]] = {}
    for row in _jsonl(root / "annotations.jsonl"):
        by_page.setdefault(str(_obj(row.get("page")).get("page_guid")), []).append(
            _obj(row.get("annotation"))
        )

    for page in sorted(_jsonl(root / "pages.jsonl"), key=lambda item: str(item["page_guid"])):
        image = page.get("image")
        if not isinstance(image, dict):
            continue
        guid = str(page["page_guid"])
        split = split_of[f"{dataset.project_key}|{guid}"]
        source = (int(image["width_px"]), int(image["height_px"]))
        with TiffRaster(Path(dataset.source_root) / str(image["path"]), strip_cache=1) as raster:
            work = working_page(raster, config.downsample)
        shapes = _shapes(by_page.get(guid, []), config, source)

        targets: dict[str, bytearray] = {}
        if "slab" in dataset.tasks:
            mask = bytearray(work.width * work.height)
            for rings in shapes.polygons:
                fill_rings(mask, work.width, work.height, rings)
            targets["slab"] = mask
        if "masonry" in dataset.tasks:
            heat = bytearray(work.width * work.height)
            radius = config.targets["masonry"].radius_px
            for line in shapes.polylines:
                centerline_target(heat, work.width, work.height, line, radius)
            targets["masonry"] = heat

        candidates: list[tuple[int, int, str]] = [
            (x0, y0, "grid")
            for x0, y0 in grid_origins(work.width, work.height, config.tile_px, config.overlap_px)
        ]
        if split == "train":
            candidates += _positive_crops(shapes, work.width, work.height, config, guid)

        measured: list[tuple[int, int, str, str, TileTransform, float, dict[str, float]]] = []
        seen: set[str] = set()
        for x0, y0, policy in candidates:
            identifier = tile_id(
                dataset.project_key, guid, x0, y0, config.tile_px, config.downsample
            )
            if identifier in seen:
                continue
            seen.add(identifier)
            t = TileTransform(
                config.downsample,
                source[0],
                source[1],
                work.width,
                work.height,
                x0,
                y0,
                config.tile_px,
            )
            valid = t.valid_width * t.valid_height
            window = crop(
                work.pixels, work.width, work.height, x0, y0, config.tile_px, config.pad_value
            )
            fractions = {
                task: _fraction_nonzero(
                    crop(target, work.width, work.height, x0, y0, config.tile_px, 0), valid
                )
                for task, target in targets.items()
            }
            measured.append(
                (x0, y0, policy, identifier, t, _ink_fraction(window, valid), fractions)
            )

        def positive(fractions: dict[str, float]) -> bool:
            return any(
                value >= config.targets[task].min_positive_fraction
                for task, value in fractions.items()
            )

        keep: set[str]
        if split == "train":
            positives = [m for m in measured if positive(m[6])]
            negatives = [(m[3], m[5]) for m in measured if not positive(m[6]) and m[2] == "grid"]
            keep = {m[3] for m in positives} | select_train_negatives(
                negatives, len(positives), config, guid
            )
        else:
            # val/test: вся сетка, отбор не смотрит на разметку.
            keep = {m[3] for m in measured if m[2] == "grid"}

        for x0, y0, policy, identifier, t, ink, fractions in measured:
            if identifier not in keep:
                continue
            window = crop(
                work.pixels, work.width, work.height, x0, y0, config.tile_px, config.pad_value
            )
            write_png_gray(
                out / "tiles" / f"{identifier}.png", config.tile_px, config.tile_px, window
            )
            image_sha = hashlib.sha256(
                (out / "tiles" / f"{identifier}.png").read_bytes()
            ).hexdigest()
            for task, target in targets.items():
                patch = crop(target, work.width, work.height, x0, y0, config.tile_px, 0)
                write_png_gray(
                    out / "targets" / task / f"{identifier}.png",
                    config.tile_px,
                    config.tile_px,
                    patch,
                )
            tile_rows.append(
                _dump(
                    {
                        "tile_id": identifier,
                        "project_key": dataset.project_key,
                        "page_guid": guid,
                        "split": split,
                        "crop_policy": policy,
                        "tasks": list(dataset.tasks),
                        "image": f"tiles/{identifier}.png",
                        "image_sha256": image_sha,
                        "transform": t.record(),
                        "ink_fraction": round(ink, 6),
                        "target_fraction": {
                            task: round(value, 6) for task, value in fractions.items()
                        },
                        "positive": positive(fractions),
                    }
                )
            )
            counters[f"tiles:{split}:{policy}"] += 1
            counters[f"tiles:{split}:{'positive' if positive(fractions) else 'negative'}"] += 1
            base = {
                "tile_id": identifier,
                "split": split,
                "image": f"tiles/{identifier}.png",
                "image_sha256": image_sha,
                "image_size": [config.tile_px, config.tile_px],
                "coordinate_range": config.qwen_coordinate_range,
                "crop_policy": policy,
            }
            if "slab" in dataset.tasks:
                localization, polygon = slab_views(shapes, t, config)
                views["qwen_slab_localization_v1"].append(
                    _dump(
                        {
                            **base,
                            "view": "qwen_slab_localization_v1",
                            "instruction": INSTRUCTIONS["qwen_slab_localization_v1"],
                            "target": _dump(localization),
                        }
                    )
                )
                if polygon is not None:
                    views["qwen_slab_polygon_v0"].append(
                        _dump(
                            {
                                **base,
                                "view": "qwen_slab_polygon_v0",
                                "instruction": INSTRUCTIONS["qwen_slab_polygon_v0"],
                                "target": _dump(polygon),
                            }
                        )
                    )
                else:
                    counters["qwen_slab_polygon_v0:skipped_tiles"] += 1
            if "masonry" in dataset.tasks:
                views["qwen_masonry_roi_v0"].append(
                    _dump(
                        {
                            **base,
                            "view": "qwen_masonry_roi_v0",
                            "instruction": INSTRUCTIONS["qwen_masonry_roi_v0"],
                            "target": _dump(masonry_view(shapes, t, config)),
                        }
                    )
                )
        counters[f"pages:{split}"] += 1


def _positive_crops(
    shapes: PageShapes, width: int, height: int, config: BuildConfig, page_guid: str
) -> list[tuple[int, int, str]]:
    """Окна train вокруг разметки со сдвигом от seed. Для val/test не вызывается никогда."""
    centers: list[Point] = []
    for rings in shapes.polygons:
        xs, ys = [x for x, _ in rings[0]], [y for _, y in rings[0]]
        centers.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    for line in shapes.polylines:
        xs, ys = [x for x, _ in line], [y for _, y in line]
        centers.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    ordered = sorted(
        range(len(centers)),
        key=lambda index: stable_fraction(config.seed, page_guid, "crop", index),
    )[: config.train_positive_crops_per_page]
    crops: list[tuple[int, int, str]] = []
    for index in ordered:
        cx, cy = centers[index]
        jitter = config.tile_px / 8
        dx = (stable_fraction(config.seed, page_guid, "dx", index) - 0.5) * 2 * jitter
        dy = (stable_fraction(config.seed, page_guid, "dy", index) - 0.5) * 2 * jitter
        x0 = int(min(max(0, cx + dx - config.tile_px / 2), max(0, width - config.tile_px)))
        y0 = int(min(max(0, cy + dy - config.tile_px / 2), max(0, height - config.tile_px)))
        crops.append((x0, y0, "gt_positive"))
    return crops


def leakage_report(out: Path) -> JsonObject:
    """Проверки утечки по готовой сборке: отбор val/test и отсутствие подсказок в инструкциях."""
    tiles = _jsonl(out / "tiles.jsonl")
    evaluation = [t for t in tiles if t["split"] in ("val", "test")]
    pages_by_split: dict[str, set[str]] = {}
    for tile in tiles:
        pages_by_split.setdefault(str(tile["split"]), set()).add(str(tile["page_guid"]))
    overlap = sorted(
        (a, b)
        for a in pages_by_split
        for b in pages_by_split
        if a < b and pages_by_split[a] & pages_by_split[b]
    )
    # Инструкция — постоянная строка вида: в ней не может оказаться ни числа объектов, ни метки.
    instructions_clean = all(
        row.get("instruction") == INSTRUCTIONS[name]
        for name in INSTRUCTIONS
        if (out / "views" / f"{name}.jsonl").exists()
        for row in _jsonl(out / "views" / f"{name}.jsonl")
    )
    return {
        "evaluation_tiles_grid_only": all(t["crop_policy"] == "grid" for t in evaluation),
        "pages_in_one_split_only": not overlap,
        "instructions_without_counts": instructions_clean,
        "tile_filenames_opaque": all(str(t["image"]) == f"tiles/{t['tile_id']}.png" for t in tiles),
    }
