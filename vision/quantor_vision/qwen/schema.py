"""Строгий контракт ответа Qwen: сериализация цели SFT и разбор ответа модели.

Ответ — только компактный JSON заданной схемы. Проза, ограждение ```, лишние и повторённые ключи,
дробные координаты, выход за 0..1000, перевёрнутая или пустая рамка, превышение числа объектов и
точек — отказ с кодом ошибки. Отказ ничем не чинится: доля отказов по кодам — метрика прогона
(промты 13–14), а не повод дописать ответ другой моделью.

Координаты — целые 0..1000 относительно ровно того изображения, что подано модели. Физических
единиц в схеме нет и быть не может.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

SLAB_SCHEMA = "qwen_slab_localization_v1"
MASONRY_SCHEMA = "qwen_masonry_roi_v1"
COORDINATE_MAX = 1000

ERROR_CODES = (
    "empty",
    "prose_or_fence",
    "not_json",
    "duplicate_key",
    "not_object",
    "schema_mismatch",
    "missing_key",
    "extra_key",
    "wrong_type",
    "coordinate_out_of_range",
    "bbox_order",
    "bbox_area",
    "too_many_objects",
    "too_many_points",
    "point_outside_box",
    "inconsistent_roi",
)

Point = tuple[int, int]
Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Limits:
    max_objects: int = 16
    max_positive_points: int = 3
    max_negative_points: int = 3
    max_guide_points: int = 8


@dataclass(frozen=True, slots=True)
class SlabObject:
    bbox: Box
    positive_points: tuple[Point, ...]
    negative_points: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class MasonryRoi:
    contains_masonry: bool
    roi: Box | None
    guide_points: tuple[Point, ...]


class ResponseError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"неизвестный код ошибки {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# --- сериализация цели --------------------------------------------------------------------------


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def serialize_slab(objects: list[SlabObject]) -> str:
    """Цель SFT: ключи в порядке контракта, без пробелов — ровно то, что должна вернуть модель."""
    body = {
        "schema": SLAB_SCHEMA,
        "objects": [
            {
                "class": "slab",
                "bbox": list(item.bbox),
                "positive_points": [list(point) for point in item.positive_points],
                "negative_points": [list(point) for point in item.negative_points],
            }
            for item in objects
        ],
    }
    return _compact(body)


def serialize_masonry(value: MasonryRoi) -> str:
    return _compact(
        {
            "schema": MASONRY_SCHEMA,
            "contains_masonry": value.contains_masonry,
            "roi": list(value.roi) if value.roi is not None else None,
            "guide_points": [list(point) for point in value.guide_points],
        }
    )


# --- разбор ответа --------------------------------------------------------------------------------


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResponseError("duplicate_key", f"ключ {key!r} повторён")
        result[key] = value
    return result


def _reject_constant(name: str) -> object:
    raise ResponseError("not_json", f"константа {name} не входит в JSON")


def _load_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        raise ResponseError("empty", "пустой ответ")
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ResponseError("prose_or_fence", "ответ не начинается с { и не кончается }")
    try:
        value: object = json.loads(
            stripped,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ResponseError("not_json", error.msg) from error
    if not isinstance(value, dict):
        raise ResponseError("not_object", "корень ответа — не объект")
    return value


def _exact_keys(value: dict[str, object], expected: tuple[str, ...], where: str) -> None:
    missing = [key for key in expected if key not in value]
    if missing:
        raise ResponseError("missing_key", f"{where}: нет {missing}")
    extra = sorted(set(value) - set(expected))
    if extra:
        raise ResponseError("extra_key", f"{where}: лишние {extra}")


def _integer(value: object, where: str) -> int:
    # bool — подкласс int в Python, но в JSON это другой тип.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResponseError("wrong_type", f"{where}: ожидается целое")
    if not 0 <= value <= COORDINATE_MAX:
        raise ResponseError("coordinate_out_of_range", f"{where}: {value} вне 0..{COORDINATE_MAX}")
    return value


def _list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise ResponseError("wrong_type", f"{where}: ожидается список")
    return value


def _box(value: object, where: str) -> Box:
    items = _list(value, where)
    if len(items) != 4:
        raise ResponseError("wrong_type", f"{where}: рамка — ровно 4 числа")
    x0, y0, x1, y1 = (_integer(item, f"{where}[{index}]") for index, item in enumerate(items))
    if x0 > x1 or y0 > y1:
        raise ResponseError("bbox_order", f"{where}: ожидается [x0, y0, x1, y1] с x0≤x1, y0≤y1")
    if x0 == x1 or y0 == y1:
        raise ResponseError("bbox_area", f"{where}: рамка нулевой площади")
    return x0, y0, x1, y1


def _points(value: object, where: str, limit: int) -> tuple[Point, ...]:
    items = _list(value, where)
    if len(items) > limit:
        raise ResponseError("too_many_points", f"{where}: {len(items)} > {limit}")
    points: list[Point] = []
    for index, item in enumerate(items):
        pair = _list(item, f"{where}[{index}]")
        if len(pair) != 2:
            raise ResponseError("wrong_type", f"{where}[{index}]: точка — ровно 2 числа")
        points.append(
            (_integer(pair[0], f"{where}[{index}].x"), _integer(pair[1], f"{where}[{index}].y"))
        )
    return tuple(points)


def _inside(point: Point, box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _schema(value: dict[str, object], expected: str) -> None:
    if value.get("schema") != expected:
        raise ResponseError("schema_mismatch", f"schema {value.get('schema')!r} ≠ {expected!r}")


def parse_slab(text: str, limits: Limits | None = None) -> list[SlabObject]:
    limits = limits or Limits()
    value = _load_object(text)
    _schema(value, SLAB_SCHEMA)
    _exact_keys(value, ("schema", "objects"), "ответ")
    raw_objects = _list(value["objects"], "objects")
    if len(raw_objects) > limits.max_objects:
        raise ResponseError("too_many_objects", f"{len(raw_objects)} > {limits.max_objects}")
    objects: list[SlabObject] = []
    for index, raw in enumerate(raw_objects):
        where = f"objects[{index}]"
        if not isinstance(raw, dict):
            raise ResponseError("wrong_type", f"{where}: ожидается объект")
        _exact_keys(raw, ("class", "bbox", "positive_points", "negative_points"), where)
        if raw["class"] != "slab":
            raise ResponseError("schema_mismatch", f"{where}.class {raw['class']!r} ≠ 'slab'")
        box = _box(raw["bbox"], f"{where}.bbox")
        positive = _points(
            raw["positive_points"], f"{where}.positive_points", limits.max_positive_points
        )
        negative = _points(
            raw["negative_points"], f"{where}.negative_points", limits.max_negative_points
        )
        outside = [point for point in positive if not _inside(point, box)]
        if outside:
            raise ResponseError("point_outside_box", f"{where}: положительные точки {outside}")
        objects.append(SlabObject(bbox=box, positive_points=positive, negative_points=negative))
    return objects


def parse_masonry(text: str, limits: Limits | None = None) -> MasonryRoi:
    limits = limits or Limits()
    value = _load_object(text)
    _schema(value, MASONRY_SCHEMA)
    _exact_keys(value, ("schema", "contains_masonry", "roi", "guide_points"), "ответ")
    contains = value["contains_masonry"]
    if not isinstance(contains, bool):
        raise ResponseError("wrong_type", "contains_masonry: ожидается true или false")
    guides = _points(value["guide_points"], "guide_points", limits.max_guide_points)
    if not contains:
        if value["roi"] is not None or guides:
            raise ResponseError("inconsistent_roi", "нет кладки, но есть roi или guide_points")
        return MasonryRoi(contains_masonry=False, roi=None, guide_points=())
    if value["roi"] is None:
        raise ResponseError("inconsistent_roi", "кладка есть, а roi пуст")
    roi = _box(value["roi"], "roi")
    outside = [point for point in guides if not _inside(point, roi)]
    if outside:
        raise ResponseError("point_outside_box", f"guide_points вне roi: {outside}")
    return MasonryRoi(contains_masonry=True, roi=roi, guide_points=guides)


def failure_counts(codes: list[str | None]) -> dict[str, object]:
    """Метрика разбора: доля годных ответов и отказы по кодам (None — ответ разобран)."""
    failures = Counter(code for code in codes if code is not None)
    total = len(codes)
    return {
        "responses": total,
        "parsed": total - sum(failures.values()),
        "parse_rate": (total - sum(failures.values())) / total if total else 0.0,
        "failures": dict(sorted(failures.items())),
    }
