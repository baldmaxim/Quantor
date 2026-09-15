"""Подсказки для SAM без разметки.

Каждая функция получает только то, что есть и в производственном прогоне: изображение тайла или
вероятность от другой модели. Разметку сюда передать нельзя — у функций нет такого параметра.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import torch
from torch.nn import functional


@dataclass(frozen=True, slots=True)
class Component:
    # Рамка (x0, y0, x1, y1) и точка внутри — в пикселях тайла.
    box: tuple[float, float, float, float]
    point: tuple[float, float]
    area_px: int


def grid_points(size: int, per_side: int) -> list[tuple[float, float]]:
    """Равномерная сетка точек по тайлу — подсказка «автоматического» режима SAM."""
    step = size / per_side
    return [(step * (i + 0.5), step * (j + 0.5)) for j in range(per_side) for i in range(per_side)]


def components(
    probability: torch.Tensor,
    *,
    threshold: float,
    stride: int = 4,
    min_area_px: int = 4096,
    max_components: int = 8,
) -> list[Component]:
    """Связные области грубой маски → рамка и самая уверенная точка каждой области.

    Считается на уменьшенной в `stride` раз маске (max-pool): на тайле 1 024 px это 256×256, и
    обход в ширину укладывается в доли секунды. Области меньше `min_area_px` пикселей тайла и сверх
    `max_components` крупнейших отбрасываются — это настройки политики, выбираемые на val.
    """
    pooled_probability = functional.max_pool2d(probability.unsqueeze(0), stride)[0, 0]
    mask = (pooled_probability >= threshold).tolist()
    height, width = len(mask), len(mask[0]) if mask else 0
    seen = [[False] * width for _ in range(height)]
    found: list[Component] = []
    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y][start_x] or seen[start_y][start_x]:
                continue
            queue = deque([(start_y, start_x)])
            seen[start_y][start_x] = True
            cells: list[tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                cells.append((y, x))
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((ny, nx))
            area = len(cells) * stride * stride
            if area < min_area_px:
                continue
            ys = [y for y, _ in cells]
            xs = [x for _, x in cells]
            best_y, best_x = max(
                cells, key=lambda cell: (float(pooled_probability[cell]), -cell[0], -cell[1])
            )
            found.append(
                Component(
                    box=(
                        min(xs) * stride,
                        min(ys) * stride,
                        (max(xs) + 1) * stride,
                        (max(ys) + 1) * stride,
                    ),
                    point=((best_x + 0.5) * stride, (best_y + 0.5) * stride),
                    area_px=area,
                )
            )
    found.sort(key=lambda component: (-component.area_px, component.box))
    return found[:max_components]
