"""Политики подсказок SAM, доступные и в производстве: без разметки на входе.

`auto` — SAM сам по себе: сетка точек по тайлу, из каждой — лучшая из трёх масок; остаются уверенные
маски разумной площади со светлой внутренностью. Семантики «это плита» у SAM нет, поэтому эта
политика заведомо собирает и помещения, и рамки — это и есть честный SAM-only baseline.

`coarse` — уточнитель: грубая маска малого U-Net промта 10 (его замороженный порог) → связные
области → рамка и самая уверенная точка каждой → SAM по рамке с точкой → объединение масок.
Отверстия SAM оставляет сам: маска по рамке их не заливает.

Объединение масок — максимум логитов на сетке SAM (256×256), затем одно увеличение до тайла:
объединение увеличенных по одной масок на CPU стоило десятки секунд на тайл.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.nn import functional

from quantor_vision.sam.prompts import components, grid_points
from quantor_vision.sam.segmenter import MaskBatch, Segmenter, upscale

POLICIES = ("auto", "coarse")


@dataclass(frozen=True, slots=True)
class AutoConfig:
    grid_per_side: int = 16
    min_score: float = 0.85
    min_area_fraction: float = 0.02
    max_area_fraction: float = 0.9
    min_white_fraction: float = 0.9
    chunk: int = 64


@dataclass(frozen=True, slots=True)
class CoarseConfig:
    min_area_px: int = 4096
    max_components: int = 8
    min_score: float = 0.5


def _best(batch: MaskBatch) -> tuple[torch.Tensor, torch.Tensor]:
    """Для каждой подсказки — маска с наибольшей оценкой из трёх вариантов SAM."""
    index = batch.scores.argmax(dim=1)
    rows = torch.arange(batch.scores.shape[0])
    return batch.logits[rows, index], batch.scores[rows, index]


def _low_res_white(image: torch.Tensor, size: tuple[int, int]) -> torch.Tensor:
    """Доля светлых пикселей изображения в каждой клетке сетки масок SAM."""
    white = (image > 0.8).float().unsqueeze(0)
    return functional.adaptive_avg_pool2d(white, size)[0, 0]


def auto_predict(segmenter: Segmenter, image: torch.Tensor, config: AutoConfig) -> torch.Tensor:
    """Фильтры и объединение — на сетке масок SAM, увеличение до тайла — одно на тайл."""
    size = image.shape[-1]
    embedding = segmenter.embed(image)
    points = grid_points(size, config.grid_per_side)
    union: torch.Tensor | None = None
    white: torch.Tensor | None = None
    for start in range(0, len(points), config.chunk):
        logits, scores = _best(
            segmenter.from_points(embedding, points[start : start + config.chunk])
        )
        if white is None:
            white = _low_res_white(image, (logits.shape[-2], logits.shape[-1]))
        for mask_logits, score in zip(logits, scores, strict=True):
            if float(score) < config.min_score:
                continue
            inside = mask_logits > 0
            fraction = float(inside.float().mean())
            if not config.min_area_fraction <= fraction <= config.max_area_fraction:
                continue
            if float(white[inside].mean()) < config.min_white_fraction:
                continue
            union = mask_logits if union is None else torch.maximum(union, mask_logits)
    if union is None:
        return torch.zeros(1, size, size)
    return upscale(union, size).float().unsqueeze(0)


def coarse_predict(
    segmenter: Segmenter,
    image: torch.Tensor,
    coarse_probability: torch.Tensor,
    *,
    coarse_threshold: float,
    config: CoarseConfig,
) -> torch.Tensor:
    size = image.shape[-1]
    found = components(
        coarse_probability,
        threshold=coarse_threshold,
        min_area_px=config.min_area_px,
        max_components=config.max_components,
    )
    if not found:
        return torch.zeros(1, size, size)
    embedding = segmenter.embed(image)
    logits, scores = _best(
        segmenter.from_boxes(
            embedding,
            [component.box for component in found],
            [component.point for component in found],
        )
    )
    kept = logits[scores >= config.min_score]
    if kept.shape[0] == 0:
        return torch.zeros(1, size, size)
    # Объединение — максимум логитов на сетке SAM, затем одно увеличение до тайла.
    return upscale(kept.max(dim=0).values, size).float().unsqueeze(0)
