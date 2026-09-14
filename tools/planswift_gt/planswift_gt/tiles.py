"""Тайлы: сетка, преобразование координат и отбор — без знания разметки там, где она запрещена.

Преобразование каждого тайла хранится явно: рабочий растр — это исходный растр с целым шагом
уменьшения, тайл — окно рабочего растра с возможной заливкой справа и снизу.

```text
page_norm  x_n ∈ [0, 1]          x_n = (x0 + u) · downsample / source_width
tile px    u ∈ [0, tile_px)      u   = x_n · source_width / downsample − x0
qwen       q ∈ 0..1000           q   = round(u / tile_px · 1000), u = q / 1000 · tile_px
```

Координаты Qwen отсчитываются от ровно того изображения, которое видит модель, — тайла вместе с
заливкой.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TileTransform:
    downsample: int
    source_width: int
    source_height: int
    working_width: int
    working_height: int
    x0: int
    y0: int
    tile_px: int

    @property
    def valid_width(self) -> int:
        return max(0, min(self.tile_px, self.working_width - self.x0))

    @property
    def valid_height(self) -> int:
        return max(0, min(self.tile_px, self.working_height - self.y0))

    def page_to_tile(self, x_norm: float, y_norm: float) -> tuple[float, float]:
        return (
            x_norm * self.source_width / self.downsample - self.x0,
            y_norm * self.source_height / self.downsample - self.y0,
        )

    def tile_to_page(self, u: float, v: float) -> tuple[float, float]:
        return (
            (self.x0 + u) * self.downsample / self.source_width,
            (self.y0 + v) * self.downsample / self.source_height,
        )

    def to_qwen(self, u: float, v: float, scale: int = 1000) -> tuple[int, int]:
        def clamp(value: float) -> int:
            return int(min(scale, max(0, round(value / self.tile_px * scale))))

        return clamp(u), clamp(v)

    def qwen_to_page(self, qx: int, qy: int, scale: int = 1000) -> tuple[float, float]:
        return self.tile_to_page(qx / scale * self.tile_px, qy / scale * self.tile_px)

    def record(self) -> dict[str, object]:
        return {
            "downsample": self.downsample,
            "source_size": [self.source_width, self.source_height],
            "working_size": [self.working_width, self.working_height],
            "origin_working_px": [self.x0, self.y0],
            "tile_px": self.tile_px,
            "valid_size": [self.valid_width, self.valid_height],
            "padding": {
                "right": self.tile_px - self.valid_width,
                "bottom": self.tile_px - self.valid_height,
            },
            "formula": {
                "tile_to_page_norm": "x_n = (x0 + u) * downsample / source_width",
                "qwen_to_tile": "u = q / 1000 * tile_px",
            },
        }


def grid_origins(width: int, height: int, tile_px: int, overlap_px: int) -> list[tuple[int, int]]:
    """Сетка окон по размеру рабочего растра. Разметку не принимает — её здесь знать нельзя."""
    stride = tile_px - overlap_px

    def axis(size: int) -> list[int]:
        if size <= tile_px:
            return [0]
        count = math.ceil((size - tile_px) / stride) + 1
        return [min(index * stride, size - tile_px) for index in range(count)]

    return [(x, y) for y in axis(height) for x in axis(width)]


def stable_fraction(*parts: object) -> float:
    """Детерминированное «случайное» число в [0, 1) из seed и идентификаторов."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def tile_id(
    project_key: str, page_guid: str, x0: int, y0: int, tile_px: int, downsample: int
) -> str:
    """Непрозрачный идентификатор: ни имени листа, ни метки в имени файла тайла."""
    raw = f"{project_key}|{page_guid}|{x0}|{y0}|{tile_px}|{downsample}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def crop(
    pixels: bytes | bytearray, width: int, height: int, x0: int, y0: int, size: int, pad: int
) -> bytes:
    fill = bytes((pad,))
    rows: list[bytes] = []
    for y in range(y0, y0 + size):
        if y >= height:
            rows.append(fill * size)
            continue
        start = y * width + x0
        line = bytes(pixels[start : start + max(0, min(size, width - x0))])
        rows.append(line + fill * (size - len(line)))
    return b"".join(rows)
