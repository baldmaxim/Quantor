"""Сшивка масок тайлов в маску листа — детерминированно и без двойного счёта перекрытий.

Пиксель листа покрыт одним или несколькими тайлами (перекрытие сетки 128 px). Он — плита, если
доля покрывающих его тайлов, назвавших его плитой, не меньше `vote_threshold`; при пороге 0,5
ничья двух тайлов решается в пользу плиты. Результат не зависит от порядка тайлов, а дубли в
перекрытии сливаются в одну область ещё до векторизации. Непокрытые пиксели — не плита.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch

from quantor_vision.png import read_gray


@dataclass(frozen=True, slots=True)
class TileMask:
    path: Path
    origin: tuple[int, int]
    valid_width: int
    valid_height: int


def read_mask(path: Path) -> torch.Tensor:
    width, height, pixels = read_gray(path)
    return torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(height, width) > 127


def stitch(
    tiles: list[TileMask], width: int, height: int, vote_threshold: float
) -> tuple[torch.Tensor, int]:
    """Маска листа bool H×W и число непокрытых пикселей."""
    votes = torch.zeros(height, width, dtype=torch.int16)
    count = torch.zeros(height, width, dtype=torch.int16)
    for tile in tiles:
        mask = read_mask(tile.path)
        x0, y0 = tile.origin
        h, w = tile.valid_height, tile.valid_width
        votes[y0 : y0 + h, x0 : x0 + w] += mask[:h, :w].to(torch.int16)
        count[y0 : y0 + h, x0 : x0 + w] += 1
    covered = count > 0
    page = covered & (votes.to(torch.float32) >= vote_threshold * count.to(torch.float32))
    return page, int((~covered).sum())
