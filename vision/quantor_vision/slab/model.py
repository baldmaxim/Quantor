"""Малый U-Net с нуля: без предобученных весов и без чужой архитектурной библиотеки.

Базовая ширина 16 и четыре уровня — порядка 1,9 млн параметров: дёшево в инференсе и помещается
в 8 ГБ на тайле 1 024 px. Поиск архитектуры промтом не предусмотрен.
"""

from __future__ import annotations

import torch
from torch import nn


def _block(inputs: int, outputs: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(inputs, outputs, 3, padding=1, bias=False),
        nn.BatchNorm2d(outputs),
        nn.ReLU(inplace=True),
        nn.Conv2d(outputs, outputs, 3, padding=1, bias=False),
        nn.BatchNorm2d(outputs),
        nn.ReLU(inplace=True),
    )


class TinyUNet(nn.Module):
    def __init__(self, base: int = 16, depth: int = 4) -> None:
        super().__init__()
        self.base = base
        self.depth = depth
        widths = [base * 2**level for level in range(depth + 1)]
        self.down = nn.ModuleList([_block(1, widths[0])])
        self.down.extend(_block(widths[i], widths[i + 1]) for i in range(depth))
        self.pool = nn.MaxPool2d(2)
        self.up = nn.ModuleList(
            nn.ConvTranspose2d(widths[i + 1], widths[i], 2, stride=2)
            for i in reversed(range(depth))
        )
        self.merge = nn.ModuleList(_block(widths[i] * 2, widths[i]) for i in reversed(range(depth)))
        self.head = nn.Conv2d(widths[0], 1, 1)

    @property
    def name(self) -> str:
        return f"tiny-unet-b{self.base}-d{self.depth}"

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips: list[torch.Tensor] = []
        for index, block in enumerate(self.down):
            x = block(x if index == 0 else self.pool(x))
            skips.append(x)
        x = skips.pop()
        for up, merge in zip(self.up, self.merge, strict=True):
            x = up(x)
            x = merge(torch.cat([x, skips.pop()], dim=1))
        logits: torch.Tensor = self.head(x)
        return logits


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())
