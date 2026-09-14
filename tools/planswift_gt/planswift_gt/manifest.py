"""Формат `planswift-gt-v1`: запись, проверка и сводка без базы данных.

Каталог результата — открытые текстовые файлы, которые сравниваются `diff` и проверяются заново:

```text
manifest.json       формат, версия инструмента, счётчики, SHA-256 трёх файлов ниже
pages.jsonl         лист: GUID, растр по пути и хешу, размер, ScaleX/ScaleY как свидетельство
annotations.jsonl   аннотация в форме контракта GroundTruth v1 (одна строка — одна секция)
rejections.jsonl    отвергнутые файлы и секции с причиной
```

Порядок строк и ключей фиксирован, меток времени нет: повторный импорт тех же данных даёт те же
байты. Растры не копируются — на них ссылаются путь и хеш.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from planswift_gt import FORMAT, TOOL_NAME, TOOL_VERSION
from planswift_gt.images import sha256_file
from planswift_gt.parser import MIN_POINTS_BY_KIND, Annotation, Page, ParseResult, Rejection

MANIFEST = "manifest.json"
PAGES = "pages.jsonl"
ANNOTATIONS = "annotations.jsonl"
REJECTIONS = "rejections.jsonl"

JsonObject = dict[str, object]


def _dumps(value: object) -> str:
    # allow_nan=False: NaN и бесконечность в JSON не пишутся никогда — лучше отказ записи.
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def dataset_fingerprint(files: dict[str, str]) -> str:
    """Отпечаток датасета: формат и хеши трёх файлов. Те же данные — тот же отпечаток."""
    lines = [FORMAT, *(f"{name} {files[name]}" for name in sorted(files))]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def source_fingerprint(result: ParseResult) -> str:
    """Отпечаток источника: все прочитанные XML и растры листов по пути и хешу."""
    lines = [f"xml {path} {digest}" for path, digest in sorted(result.sources)]
    lines += sorted(
        f"image {page.image_path} {page.image.sha256}"
        for page in result.pages
        if page.image is not None
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def page_record(page: Page) -> JsonObject:
    image = page.image
    return {
        "page_guid": page.page_guid,
        "name": page.name,
        "order_index": page.order_index,
        "image": None
        if image is None
        else {
            "path": page.image_path,
            "sha256": image.sha256,
            "width_px": image.width_px,
            "height_px": image.height_px,
            "size_bytes": image.size_bytes,
            "format": image.format,
        },
        "image_rejection": page.image_rejection,
        "scale_evidence": {
            "scale_x": page.scale_x,
            "scale_y": page.scale_y,
            "scale_units": page.scale_units,
        },
        "source_path": page.source_path,
        "source_xml_sha256": page.source_xml_sha256,
    }


def annotation_record(
    annotation: Annotation, page: Page, *, dataset_id: str, project_key: str
) -> JsonObject:
    image = page.image
    return {
        "dataset_id": dataset_id,
        "source": "planswift",
        "project_key": project_key,
        "page": {
            "page_guid": page.page_guid,
            "image_sha256": image.sha256 if image else None,
            "width_px": image.width_px if image else None,
            "height_px": image.height_px if image else None,
        },
        "annotation": {
            "id": annotation.id,
            "kind": annotation.kind,
            "section_class": annotation.section_class,
            "label_raw": annotation.label_raw,
            "label_path": annotation.label_path,
            "points_normalized": annotation.points_normalized,
            "points_source_px": annotation.points_source_px,
            "point_types": annotation.point_types,
            "object_count": annotation.object_count,
            "parent_annotation_id": annotation.parent_annotation_id,
            "page_guid_inherited": annotation.page_guid_inherited,
            "source_path": annotation.source_path,
            "source_xml_sha256": annotation.source_xml_sha256,
        },
    }


def rejection_record(rejection: Rejection) -> JsonObject:
    return {
        "source_path": rejection.source_path,
        "source_xml_sha256": rejection.source_xml_sha256,
        "section_class": rejection.section_class,
        "guid": rejection.guid,
        "reason": rejection.reason,
        "detail": rejection.detail,
    }


def summary(result: ParseResult) -> JsonObject:
    kinds = Counter(annotation.kind for annotation in result.annotations)
    objects = Counter[str]()
    for annotation in result.annotations:
        objects[annotation.kind] += annotation.object_count
    return {
        "pages": len(result.pages),
        "pages_without_image": sum(1 for page in result.pages if page.image is None),
        "annotations": len(result.annotations),
        "annotations_by_kind": dict(sorted(kinds.items())),
        "objects_by_kind": dict(sorted(objects.items())),
        "rejections": len(result.rejections),
        "rejections_by_reason": dict(sorted(Counter(r.reason for r in result.rejections).items())),
        "counters": dict(sorted(result.counters.items())),
    }


def write(result: ParseResult, out_dir: Path, *, dataset_id: str, project_key: str) -> JsonObject:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = {page.page_guid: page for page in result.pages}

    lines: dict[str, list[str]] = {
        PAGES: [_dumps(page_record(page)) for page in result.pages],
        ANNOTATIONS: [
            _dumps(
                annotation_record(
                    item, pages[item.page_guid], dataset_id=dataset_id, project_key=project_key
                )
            )
            for item in result.annotations
        ],
        REJECTIONS: [_dumps(rejection_record(item)) for item in result.rejections],
    }
    files: dict[str, str] = {}
    for name, rows in lines.items():
        payload = "".join(row + "\n" for row in rows).encode("utf-8")
        (out_dir / name).write_bytes(payload)
        files[name] = hashlib.sha256(payload).hexdigest()

    manifest: JsonObject = {
        "format": FORMAT,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "dataset_id": dataset_id,
        "project_key": project_key,
        "source": "planswift",
        "project_name": result.project_name,
        "files": files,
        "dataset_fingerprint": dataset_fingerprint(files),
        "source_fingerprint": source_fingerprint(result),
        "summary": summary(result),
    }
    (out_dir / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


# ------------------------------------------------------------------------------ проверка


@dataclass(frozen=True, slots=True)
class Problem:
    where: str
    message: str


def _load_jsonl(path: Path, problems: list[Problem]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append(Problem(f"{path.name}:{number}", f"не JSON: {error}"))
            continue
        if not isinstance(value, dict):
            problems.append(Problem(f"{path.name}:{number}", "строка не объект"))
            continue
        rows.append(value)
    return rows


def _mapping(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _points_ok(value: object, minimum: int) -> str | None:
    if not isinstance(value, list) or len(value) < minimum:
        return f"меньше {minimum} точек"
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            return "точка не пара чисел"
        for coordinate in point:
            if isinstance(coordinate, bool) or not isinstance(coordinate, int | float):
                return "координата не число"
            if not math.isfinite(coordinate) or not 0.0 <= coordinate <= 1.0:
                return f"координата {coordinate} вне [0, 1]"
    return None


def validate(out_dir: Path, *, source_root: Path | None = None) -> list[Problem]:
    """Проверяет каталог результата без базы: целостность, ссылки, форма геометрии."""
    problems: list[Problem] = []
    manifest_path = out_dir / MANIFEST
    if not manifest_path.is_file():
        return [Problem(MANIFEST, "нет файла")]
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("format") != FORMAT:
        problems.append(Problem(MANIFEST, f"формат {manifest.get('format')!r}, ожидается {FORMAT}"))

    files = _mapping(manifest.get("files"))
    for name in (PAGES, ANNOTATIONS, REJECTIONS):
        path = out_dir / name
        if not path.is_file():
            problems.append(Problem(name, "нет файла"))
            continue
        if files.get(name) != sha256_file(path):
            problems.append(Problem(name, "SHA-256 не совпадает с manifest.json"))
    if problems:
        return problems
    typed_files = {str(key): str(value) for key, value in files.items()}
    if manifest.get("dataset_fingerprint") != dataset_fingerprint(typed_files):
        problems.append(Problem(MANIFEST, "dataset_fingerprint не соответствует файлам"))

    pages = {str(row.get("page_guid")): row for row in _load_jsonl(out_dir / PAGES, problems)}
    annotations = _load_jsonl(out_dir / ANNOTATIONS, problems)
    by_id: dict[str, JsonObject] = {}

    for index, row in enumerate(annotations, start=1):
        where = f"{ANNOTATIONS}:{index}"
        annotation = _mapping(row.get("annotation"))
        page_ref = _mapping(row.get("page"))
        identifier = str(annotation.get("id"))
        if identifier in by_id:
            problems.append(Problem(where, f"повтор id {identifier}"))
        by_id[identifier] = annotation

        kind = str(annotation.get("kind"))
        if kind not in MIN_POINTS_BY_KIND:
            problems.append(Problem(where, f"неизвестный kind {kind!r}"))
            continue
        issue = _points_ok(annotation.get("points_normalized"), MIN_POINTS_BY_KIND[kind])
        if issue is not None:
            problems.append(Problem(where, issue))

        page = pages.get(str(page_ref.get("page_guid")))
        image = _mapping(page.get("image")) if page is not None else {}
        if page is None:
            problems.append(Problem(where, "лист не найден в pages.jsonl"))
        elif (
            image.get("sha256") != page_ref.get("image_sha256")
            or image.get("width_px") != page_ref.get("width_px")
            or image.get("height_px") != page_ref.get("height_px")
        ):
            problems.append(Problem(where, "растр листа расходится с pages.jsonl"))
        else:
            issue = _source_consistent(annotation, image, kind)
            if issue is not None:
                problems.append(Problem(where, issue))

    page_of = {
        str(_mapping(row.get("annotation")).get("id")): _mapping(row.get("page")).get("page_guid")
        for row in annotations
    }
    for index, row in enumerate(annotations, start=1):
        annotation = _mapping(row.get("annotation"))
        parent_id = annotation.get("parent_annotation_id")
        if annotation.get("kind") != "polygon_hole":
            if parent_id is not None:
                problems.append(Problem(f"{ANNOTATIONS}:{index}", "родитель у не-отверстия"))
            continue
        parent = by_id.get(str(parent_id))
        if parent is None or parent.get("kind") != "polygon":
            problems.append(
                Problem(f"{ANNOTATIONS}:{index}", "отверстие без многоугольника-родителя")
            )
        elif _mapping(row.get("page")).get("page_guid") != page_of.get(str(parent_id)):
            problems.append(
                Problem(f"{ANNOTATIONS}:{index}", "отверстие на другом листе, чем родитель")
            )

    if source_root is not None:
        for guid, page in pages.items():
            image = _mapping(page.get("image"))
            if not image:
                continue
            path = source_root / str(image.get("path"))
            if not path.is_file():
                problems.append(Problem(f"{PAGES}:{guid}", f"растр не найден: {image.get('path')}"))
            elif sha256_file(path) != image.get("sha256"):
                problems.append(Problem(f"{PAGES}:{guid}", "SHA-256 растра изменился"))
    return problems


NORMALIZATION_TOLERANCE = 1e-12


def _source_consistent(annotation: JsonObject, image: JsonObject, kind: str) -> str | None:
    """Исходные пиксели конечны, не заглушки, внутри растра и дают записанную нормализацию."""
    width, height = image.get("width_px"), image.get("height_px")
    source = annotation.get("points_source_px")
    normalized = annotation.get("points_normalized")
    types = annotation.get("point_types")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return "размер растра не задан"
    if not isinstance(source, list) or not isinstance(normalized, list):
        return "нет точек"
    if len(source) != len(normalized) or not isinstance(types, list) or len(types) != len(source):
        return "число исходных точек, нормализованных и типов расходится"
    for raw, norm in zip(source, normalized, strict=True):
        if not isinstance(raw, list) or len(raw) != 2 or not isinstance(norm, list):
            return "точка не пара чисел"
        x, y = raw
        if not all(isinstance(v, int | float) and math.isfinite(v) for v in (x, y)):
            return "исходная координата не конечна"
        if x < 0 or y < 0:
            return "заглушка или отрицательная координата"
        if x > width or y > height:
            return "исходная точка за краем растра"
        if (
            abs(norm[0] - x / width) > NORMALIZATION_TOLERANCE
            or abs(norm[1] - y / height) > NORMALIZATION_TOLERANCE
        ):
            return "нормализация не совпадает с исходными пикселями"
    expected_objects = len(source) if kind == "count" else 1
    if annotation.get("object_count") != expected_objects:
        return f"object_count {annotation.get('object_count')}, ожидается {expected_objects}"
    return None


def findings(out_dir: Path) -> JsonObject:
    """Замечания, не делающие датасет негодным, но видимые: дубли и повторы вершин."""
    problems: list[Problem] = []
    annotations = _load_jsonl(out_dir / ANNOTATIONS, problems)
    geometry: dict[str, list[str]] = {}
    repeated_vertices: list[str] = []
    for row in annotations:
        annotation = _mapping(row.get("annotation"))
        points = annotation.get("points_source_px")
        key = _dumps([_mapping(row.get("page")).get("page_guid"), annotation.get("kind"), points])
        geometry.setdefault(key, []).append(str(annotation.get("id")))
        if isinstance(points, list) and any(a == b for a, b in pairwise(points)):
            repeated_vertices.append(str(annotation.get("id")))
    duplicates = sorted(ids for ids in geometry.values() if len(ids) > 1)
    return {
        "duplicate_geometry_groups": len(duplicates),
        "duplicate_geometry_annotations": sum(len(ids) for ids in duplicates),
        "duplicate_geometry_examples": duplicates[:5],
        "repeated_consecutive_vertex_annotations": len(repeated_vertices),
        "repeated_consecutive_vertex_examples": repeated_vertices[:5],
    }


# ------------------------------------------------------------------------------ сводка


def stats(out_dir: Path) -> JsonObject:
    manifest = _mapping(json.loads((out_dir / MANIFEST).read_text(encoding="utf-8")))
    problems: list[Problem] = []
    annotations = _load_jsonl(out_dir / ANNOTATIONS, problems)
    per_page: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    holes_per_polygon: Counter[str] = Counter()
    for row in annotations:
        annotation = _mapping(row.get("annotation"))
        per_page[f"{_mapping(row.get('page')).get('page_guid')}:{annotation.get('kind')}"] += 1
        labels[f"{annotation.get('kind')}:{annotation.get('label_raw')}"] += 1
        if annotation.get("kind") == "polygon_hole":
            holes_per_polygon[str(annotation.get("parent_annotation_id"))] += 1
    return {
        "dataset_id": manifest.get("dataset_id"),
        "project_key": manifest.get("project_key"),
        "summary": manifest.get("summary"),
        "annotations_per_page_kind": dict(sorted(per_page.items())),
        "labels": dict(labels.most_common()),
        "polygons_with_holes": len(holes_per_polygon),
        "max_holes_per_polygon": max(holes_per_polygon.values(), default=0),
    }


@dataclass(frozen=True, slots=True)
class ExpectationRow:
    metric: str
    expected: float
    actual: float
    tolerance: float
    within: bool


def compare_expectations(
    summary_value: JsonObject, expectations: JsonObject
) -> list[ExpectationRow]:
    """Сверка с внешними ожиданиями. Расхождение — повод разобраться, а не подогнать разбор."""
    rows: list[ExpectationRow] = []
    counts = _mapping(summary_value.get("annotations_by_kind"))
    objects = _mapping(summary_value.get("objects_by_kind"))
    for metric, raw in sorted(expectations.items()):
        spec = _mapping(raw)
        expected = spec.get("expected")
        tolerance = spec.get("tolerance", 0)
        if not isinstance(expected, int | float) or not isinstance(tolerance, int | float):
            continue
        source, _, key = metric.partition(":")
        actual_raw = (
            summary_value.get(key)
            if source == "summary"
            else counts.get(key, 0)
            if source == "annotations"
            else objects.get(key, 0)
            if source == "objects"
            else None
        )
        if not isinstance(actual_raw, int | float):
            actual_raw = 0
        rows.append(
            ExpectationRow(
                metric=metric,
                expected=float(expected),
                actual=float(actual_raw),
                tolerance=float(tolerance),
                within=abs(float(actual_raw) - float(expected)) <= float(tolerance),
            )
        )
    return rows
