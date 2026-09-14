"""Пиксельные метрики маски плиты и ошибка площади.

Все метрики — только по допустимой области тайла (без заливки). IoU и Dice — суммарные по набору,
а не среднее по тайлам: пустые тайлы иначе давали бы IoU 1 и прятали промахи на плитах.
Boundary F1 — по границам маски с допуском в пикселях. Ошибка площади — в пространстве пикселей
рабочего растра: на одном листе масштаб общий, и доля ошибки площади совпадает с долей ошибки
физической площади.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import torch
from torch.nn import functional


def boundary(mask: torch.Tensor) -> torch.Tensor:
    """Пиксели маски, у которых есть сосед снаружи в окрестности 3×3 (эрозия max-pool)."""
    eroded = -functional.max_pool2d(-mask, kernel_size=3, stride=1, padding=1)
    return (mask - eroded).clamp(min=0)


def dilate(mask: torch.Tensor, radius: int) -> torch.Tensor:
    return functional.max_pool2d(mask, kernel_size=2 * radius + 1, stride=1, padding=radius)


@dataclass(slots=True)
class MaskMetrics:
    tolerance_px: int = 2
    intersection: float = 0.0
    union: float = 0.0
    predicted: float = 0.0
    truth: float = 0.0
    boundary_hit_pred: float = 0.0
    boundary_pred: float = 0.0
    boundary_hit_truth: float = 0.0
    boundary_truth: float = 0.0
    tile_area_errors: list[float] = field(default_factory=list)

    def update(self, prediction: torch.Tensor, truth: torch.Tensor, valid: torch.Tensor) -> None:
        """`prediction`, `truth` — 0/1 float N×1×H×W, `valid` — bool той же формы."""
        v = valid.float()
        p = prediction * v
        t = truth * v
        self.intersection += float((p * t).sum())
        self.union += float(((p + t) > 0).float().sum())
        self.predicted += float(p.sum())
        self.truth += float(t.sum())

        pb, tb = boundary(p) * v, boundary(t) * v
        self.boundary_pred += float(pb.sum())
        self.boundary_truth += float(tb.sum())
        self.boundary_hit_pred += float((pb * dilate(tb, self.tolerance_px)).sum())
        self.boundary_hit_truth += float((tb * dilate(pb, self.tolerance_px)).sum())

        for index in range(p.shape[0]):
            gt_area = float(t[index].sum())
            if gt_area > 0:
                self.tile_area_errors.append(abs(float(p[index].sum()) - gt_area) / gt_area)

    def summary(self) -> dict[str, float | int | None]:
        precision = self.boundary_hit_pred / self.boundary_pred if self.boundary_pred else 0.0
        recall = self.boundary_hit_truth / self.boundary_truth if self.boundary_truth else 0.0
        errors = sorted(self.tile_area_errors)
        return {
            "iou": self.intersection / self.union if self.union else 1.0,
            "dice": 2 * self.intersection / (self.predicted + self.truth)
            if self.predicted + self.truth
            else 1.0,
            "boundary_f1": 2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0,
            "boundary_tolerance_px": self.tolerance_px,
            "raw_area_error_total": abs(self.predicted - self.truth) / self.truth
            if self.truth
            else None,
            "tile_area_error_median": statistics.median(errors) if errors else None,
            "tile_area_error_p90": errors[min(len(errors) - 1, int(0.9 * len(errors)))]
            if errors
            else None,
            "tiles_with_slab": len(errors),
        }


def page_area_errors(pages: dict[str, tuple[float, float]]) -> dict[str, float | int | None]:
    """Ошибка нетто-площади по листу: `pages[guid] = (площадь прогноза, площадь истины)`."""
    errors = sorted(abs(pred - truth) / truth for pred, truth in pages.values() if truth > 0)
    return {
        "pages_with_slab": len(errors),
        "page_area_error_median": statistics.median(errors) if errors else None,
        "page_area_error_p90": errors[min(len(errors) - 1, int(0.9 * len(errors)))]
        if errors
        else None,
        "page_area_error_max": errors[-1] if errors else None,
    }
