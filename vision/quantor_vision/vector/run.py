"""Векторизация прогноза плиты по листам и метрики против разметки PlanSwift.

```text
<run>/predictions/<split>/<tile_id>.png       маски тайлов (промты 10, 11, 14) — доказательство
<run>/vector/<config12>/config.json           настройка и её SHA-256
<run>/vector/<config12>/<split>/<page>.json   многоугольники листа, нормализованные координаты
<run>/vector/<config12>/<split>-metrics.json  метрики и происхождение
```

Настройка подбирается на val. Test векторизуется только настройкой, у которой уже есть
val-метрики, и только один раз; повтор — лишь с причиной `new_experiment` в отдельный файл.
Вектор — производный артефакт: в записи есть хеш каждой маски, из которой он получен.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quantor_vision import runrecord
from quantor_vision.vector.metrics import Polygon, VectorMetrics
from quantor_vision.vector.polygonize import (
    VECTORIZER_VERSION,
    PageFrame,
    TooComplexError,
    VectorConfig,
    vectorize_mask,
)
from quantor_vision.vector.stitch import TileMask, stitch

JsonObject = dict[str, object]


class VectorizeRefusedError(ValueError):
    pass


def _jsonl(path: Path) -> list[JsonObject]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_truth(
    dataset_dir: Path, kinds: tuple[str, ...], labels: tuple[str, ...]
) -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Плиты разметки `planswift-gt-v1` по листам: внешнее кольцо и отверстия, нормализованные.

    Отбор и снятие дублей секций — те же, что у сборщика промта 08 (`_shapes`).
    """
    rows = _jsonl(dataset_dir / "annotations.jsonl")
    holes: dict[str, list[list[tuple[float, float]]]] = {}
    for row in rows:
        annotation = row.get("annotation")
        if isinstance(annotation, dict) and annotation.get("kind") == "polygon_hole":
            holes.setdefault(str(annotation.get("parent_annotation_id")), []).append(
                _ring(annotation)
            )
    seen: set[str] = set()
    pages: dict[str, list[list[list[tuple[float, float]]]]] = {}
    for row in rows:
        annotation, page = row.get("annotation"), row.get("page")
        if not isinstance(annotation, dict) or not isinstance(page, dict):
            continue
        key = json.dumps([annotation.get("kind"), annotation.get("points_source_px")])
        if key in seen:
            continue
        seen.add(key)
        if annotation.get("kind") not in kinds or (
            labels and annotation.get("label_raw") not in labels
        ):
            continue
        pages.setdefault(str(page.get("page_guid")), []).append(
            [_ring(annotation), *holes.get(str(annotation.get("id")), [])]
        )
    return pages


def _ring(annotation: dict[str, object]) -> list[tuple[float, float]]:
    points = annotation.get("points_normalized")
    if not isinstance(points, list):
        return []
    return [
        (float(point[0]), float(point[1]))
        for point in points
        if isinstance(point, list) and len(point) == 2
    ]


def _truth_sources(build_config: Path) -> tuple[dict[str, Path], tuple[str, ...], tuple[str, ...]]:
    config = json.loads(build_config.read_text(encoding="utf-8"))
    slab = config["targets"]["slab"]
    datasets = {
        str(item["project_key"]): Path(os.path.expandvars(str(item["dataset_dir"])))
        for item in config["datasets"]
        if "slab" in item["tasks"]
    }
    return datasets, tuple(slab.get("kinds", ["polygon"])), tuple(slab.get("labels", []))


def _pair(value: object) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise VectorizeRefusedError(f"ожидается пара чисел, получено {value!r}")
    return int(value[0]), int(value[1])


def _page(
    project: str,
    guid: str,
    rows: list[JsonObject],
    predictions_dir: Path,
    expected: dict[str, str],
    truth_by_project: dict[str, dict[str, list[list[list[tuple[float, float]]]]]],
    config: VectorConfig,
    metrics: VectorMetrics,
) -> JsonObject:
    transform = rows[0]["transform"]
    if not isinstance(transform, dict):
        raise VectorizeRefusedError(f"лист {guid}: нет преобразования тайла")
    width, height = _pair(transform["working_size"])
    source_width, source_height = _pair(transform["source_size"])
    frame = PageFrame(int(transform["downsample"]), source_width, source_height)

    tiles: list[TileMask] = []
    evidence: list[JsonObject] = []
    for row in sorted(rows, key=lambda item: str(item["tile_id"])):
        tile_id = str(row["tile_id"])
        path = predictions_dir / f"{tile_id}.png"
        sha = runrecord.sha256_file(path) if path.is_file() else None
        if sha is None or sha != expected.get(tile_id):
            raise VectorizeRefusedError(f"маска тайла {tile_id} отсутствует или изменена")
        tile_transform = row["transform"]
        if not isinstance(tile_transform, dict):
            raise VectorizeRefusedError(f"тайл {tile_id}: нет преобразования")
        valid_width, valid_height = _pair(tile_transform["valid_size"])
        tiles.append(
            TileMask(path, _pair(tile_transform["origin_working_px"]), valid_width, valid_height)
        )
        evidence.append({"tile_id": tile_id, "mask_sha256": sha})

    mask, uncovered = stitch(tiles, width, height, config.vote_threshold)
    scale_x, scale_y = source_width / frame.downsample, source_height / frame.downsample
    truth: list[Polygon] = [
        [[(x * scale_x, y * scale_y) for x, y in ring] for ring in polygon]
        for polygon in truth_by_project.get(project, {}).get(guid, [])
    ]
    report: JsonObject = {"project_key": project, "page_guid": guid, "tiles": len(tiles)}
    try:
        vectors = vectorize_mask(mask, frame, config)
    except TooComplexError as error:
        # Лист, который не векторизуется в пределах бюджета, — отказ с причиной и нулевой площадью
        # прогноза в метриках: это ошибка конвейера, а не пропуск листа.
        metrics.add_page(
            [],
            truth,
            page_area_px=float(width * height),
            invalid_codes=["too_complex"],
            lattice_vertices=0,
            output_vertices=0,
        )
        report.update({"status": "too_complex", "reason": str(error)})
        report["vectors"] = {**report, "evidence": evidence}
        return report
    invalid = [polygon.issue or "unknown" for polygon in vectors.polygons if polygon.issue]
    page_metrics = metrics.add_page(
        vectors.working_rings,
        truth,
        page_area_px=float(width * height),
        invalid_codes=invalid,
        lattice_vertices=sum(polygon.lattice_vertices for polygon in vectors.polygons),
        output_vertices=sum(polygon.output_vertices for polygon in vectors.polygons),
    )
    report.update(
        {
            "status": "ok",
            "polygons": len(vectors.polygons),
            "invalid": len(invalid),
            "dropped_components": vectors.dropped_components,
            "filled_holes": vectors.filled_holes,
            "boundary_edges": vectors.boundary_edges,
            "uncovered_px": uncovered,
            **page_metrics,
        }
    )
    report["vectors"] = {
        "project_key": project,
        "page_guid": guid,
        "vectorizer": VECTORIZER_VERSION,
        "config_sha256": config.sha256(),
        "coordinates": "sheet_normalized_top_left",
        "evidence": evidence,
        "polygons": [asdict(polygon) for polygon in vectors.polygons],
        "digest": hashlib.sha256(
            json.dumps([asdict(polygon) for polygon in vectors.polygons]).encode("utf-8")
        ).hexdigest(),
    }
    return report


def vectorize_run(
    build_dir: Path,
    run_dir: Path,
    *,
    split: str,
    build_config: Path,
    config: VectorConfig,
    new_experiment: str | None = None,
) -> JsonObject:
    config.validate()
    digest = config.sha256()
    root = run_dir / "vector" / digest[:12]
    metrics_name = f"{split}-metrics.json"
    if split == "test":
        if not (root / "val-metrics.json").is_file():
            raise VectorizeRefusedError(
                "test векторизуется только настройкой, уже оценённой на val (нет val-метрик)"
            )
        if (root / metrics_name).exists():
            if not new_experiment:
                raise VectorizeRefusedError("test этой настройкой уже векторизован: один раз")
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            metrics_name = f"test-metrics-{stamp}.json"

    predictions_dir = run_dir / "predictions" / split
    manifest = run_dir / f"{split}-predictions.jsonl"
    if not predictions_dir.is_dir() or not manifest.is_file():
        raise VectorizeRefusedError(f"нет масок прогноза {predictions_dir} или {manifest.name}")
    expected = {str(row["tile_id"]): str(row["sha256"]) for row in _jsonl(manifest)}

    datasets, kinds, labels = _truth_sources(build_config)
    truth_by_project = {
        key: load_truth(path, kinds, labels) for key, path in sorted(datasets.items())
    }

    pages: dict[tuple[str, str], list[JsonObject]] = {}
    for row in _jsonl(build_dir / "tiles.jsonl"):
        tasks = row.get("tasks")
        if row.get("split") == split and isinstance(tasks, list) and "slab" in tasks:
            pages.setdefault((str(row["project_key"]), str(row["page_guid"])), []).append(row)
    if not pages:
        raise VectorizeRefusedError(f"в сборке нет тайлов плиты части {split}")

    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        _dump({"config": asdict(config), "sha256": digest}), encoding="utf-8"
    )
    (root / split).mkdir(exist_ok=True)
    metrics = VectorMetrics(config)
    page_reports: list[JsonObject] = []
    for (project, guid), rows in sorted(pages.items()):
        report = _page(
            project, guid, rows, predictions_dir, expected, truth_by_project, config, metrics
        )
        (root / split / f"{project}__{guid}.json").write_text(
            _dump(report["vectors"]), encoding="utf-8"
        )
        page_reports.append({key: value for key, value in report.items() if key != "vectors"})

    result: JsonObject = {
        "split": split,
        "vectorizer": VECTORIZER_VERSION,
        "config": asdict(config),
        "config_sha256": digest,
        "new_experiment": new_experiment,
        "run_id": json.loads((run_dir / runrecord.RUN_FILE).read_text(encoding="utf-8")).get(
            "run_id"
        )
        if (run_dir / runrecord.RUN_FILE).is_file()
        else None,
        "predictions_manifest_sha256": runrecord.sha256_file(manifest),
        "build_tiles_sha256": runrecord.sha256_file(build_dir / "tiles.jsonl"),
        "truth_sources_sha256": {
            key: runrecord.sha256_file(path / "annotations.jsonl")
            for key, path in sorted(datasets.items())
        },
        "summary": metrics.summary(),
        "pages": page_reports,
    }
    (root / metrics_name).write_text(_dump(result), encoding="utf-8")
    return {"metrics": str(root / metrics_name), "summary": result["summary"]}
