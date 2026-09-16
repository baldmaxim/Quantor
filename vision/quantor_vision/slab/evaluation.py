"""Общая оценка прогноза плиты: одна и та же для малого U-Net (промт 10) и SAM (промт 11).

Сравнение моделей честно, только если метрики считает один код: тайлы той же части, та же
допустимая область, та же сшивка листа и тот же порог по вероятности. Здесь нет ни модели, ни
разметки в прогнозе: `predict` получает только изображение тайла, а истина используется лишь для
подсчёта метрик после прогноза.
"""

from __future__ import annotations

import json
import math
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import torch

from quantor_vision import runrecord
from quantor_vision.png import SIGNATURE
from quantor_vision.slab.data import SlabTiles, TileRef
from quantor_vision.slab.metrics import MaskMetrics, page_area_errors

# Прогноз тайла: вероятность плиты 1×H×W на CPU, значения 0..1. Бинарная маска — тоже вероятность.
Predictor = Callable[[TileRef, torch.Tensor], torch.Tensor]


@dataclass(frozen=True, slots=True)
class EvaluationOutput:
    result: dict[str, object]
    predictions: list[dict[str, str]]


def write_mask(path: Path, mask: torch.Tensor) -> None:
    height, width = mask.shape
    # Без numpy: у колёс torch он не обязательная зависимость.
    pixels = bytes((mask > 0).to(torch.uint8).mul(255).flatten().tolist())
    raw = b"".join(b"\0" + pixels[y * width : (y + 1) * width] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    path.write_bytes(
        SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def evaluate_predictor(
    dataset: SlabTiles,
    predict: Predictor,
    *,
    threshold: float,
    device: torch.device,
    predictions_dir: Path,
) -> EvaluationOutput:
    metrics = MaskMetrics()
    predictions_dir.mkdir(parents=True, exist_ok=True)
    hashes: list[dict[str, str]] = []
    latencies: list[float] = []
    areas: dict[str, tuple[float, float]] = {}
    uncovered = 0
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    # Лист за листом: в памяти суммы одного листа, а не всех (у сборки v2 это десятки гигабайт).
    order = sorted(
        range(len(dataset.tiles)),
        key=lambda index: (dataset.tiles[index].page_key, dataset.tiles[index].tile_id),
    )
    page_key: str | None = None
    page: dict[str, torch.Tensor] = {}

    def close_page() -> None:
        nonlocal uncovered
        if page_key is None:
            return
        covered = page["count"] > 0
        uncovered += int((~covered).sum())
        mask = (page["sum"] / page["count"].clamp(min=1)) >= threshold
        areas[page_key] = (float((mask & covered).sum()), float((page["truth"] * covered).sum()))

    with torch.no_grad():
        for index in order:
            tile = dataset.tiles[index]
            x, y, valid = dataset[index]
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            started = time.perf_counter()
            probability = predict(tile, x)
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            latencies.append((time.perf_counter() - started) * 1000)

            prediction = (probability >= threshold).float()
            metrics.update(prediction.unsqueeze(0), y.unsqueeze(0), valid.unsqueeze(0))
            path = predictions_dir / f"{tile.tile_id}.png"
            write_mask(path, prediction[0])
            hashes.append({"tile_id": tile.tile_id, "sha256": runrecord.sha256_file(path)})

            # Сшивка листа: вероятности окон складываются и делятся на число покрытий.
            if tile.page_key != page_key:
                close_page()
                page_key = tile.page_key
                height, width = tile.working_size[1], tile.working_size[0]
                page = {
                    "sum": torch.zeros(height, width),
                    "count": torch.zeros(height, width),
                    "truth": torch.zeros(height, width),
                }
            x0, y0 = tile.origin
            h, w = tile.valid_height, tile.valid_width
            page["sum"][y0 : y0 + h, x0 : x0 + w] += probability[0, :h, :w]
            page["count"][y0 : y0 + h, x0 : x0 + w] += 1
            page["truth"][y0 : y0 + h, x0 : x0 + w] = torch.maximum(
                page["truth"][y0 : y0 + h, x0 : x0 + w], y[0, :h, :w]
            )
        close_page()
    hashes.sort(key=lambda item: item["tile_id"])

    ordered = sorted(latencies)
    result: dict[str, object] = {
        "frozen_threshold": threshold,
        "tiles": len(dataset),
        "pixel": metrics.summary(),
        "page": {**page_area_errors(areas), "uncovered_pixels": uncovered},
        "latency_ms_per_tile": {
            "median": ordered[len(ordered) // 2] if ordered else None,
            "p90": ordered[min(len(ordered) - 1, math.floor(0.9 * len(ordered)))]
            if ordered
            else None,
        },
        "peak_memory_mib": round(torch.cuda.max_memory_allocated(device) / 2**20, 1)
        if device.type == "cuda"
        else None,
        "device": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
    }
    return EvaluationOutput(result, hashes)


def save_outputs(
    run_dir: Path, split: str, output: EvaluationOutput, extra: dict[str, object]
) -> dict[str, object]:
    result = {**extra, "split": split, **output.result}
    (run_dir / f"{split}-predictions.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in output.predictions), encoding="utf-8"
    )
    (run_dir / f"{split}-metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
