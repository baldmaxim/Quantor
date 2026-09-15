"""Замороженный DINOv2 + лёгкая голова сегментации плиты (решение владельца О-6 / Р-8).

Аналог лучшего сигнала SU10 по плитам — замороженный DINOv3 как грубый локатор (OOF IoU 0,58), но
на весах с лицензией Apache-2.0. Энкодер не обучается и не сохраняется: он закреплён ревизией и
SHA-256 файла весов; в `best.pt` лежит только голова (≈ 0,85 млн параметров при ширине 256).

```text
тайл 1×H×W (яркость 0..1) → заливка до кратного 14 белым → 3 канала, нормировка ImageNet
→ DINOv2 (без градиента, bf16) → токены патчей C×(H/14)×(W/14)
→ голова: 1×1 → GELU → 3×3 → GELU → 1×1 → билинейно до размера тайла → логиты плиты
```

Шаг патча 14 px ограничивает точность границы: это локатор, а не контур; контур — задача SAM или
векторизации (промты 11, 16).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Self

import torch
from torch import nn
from torch.nn import functional

from quantor_vision import runrecord

PATCH = 14
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True, slots=True)
class PinnedEncoder:
    repo_id: str
    revision: str
    weights_sha256: str
    embed_dim: int


ENCODERS: dict[str, PinnedEncoder] = {
    "large": PinnedEncoder(
        "facebook/dinov2-large",
        "47b73eefe95e8d44ec3623f8890bd894b6ea2d6c",
        "399fba97a95f22c36834418bc69373364a99af3a1153da1c0fb31db567c92e23",
        1024,
    ),
    "base": PinnedEncoder(
        "facebook/dinov2-base",
        "f9e44c814b77203eaa57a6bdbbd535f21ede1415",
        "d73036b56966966d07975d696bde331762f37297e2f095de8cea0040c3aa0841",
        768,
    ),
}


class DinoProbe(nn.Module):
    """`backbone(pixel_values=…)` возвращает объект с `last_hidden_state` N×(1+T)×C (CLS первым)."""

    def __init__(self, backbone: nn.Module, embed_dim: int, head_width: int = 256) -> None:
        super().__init__()
        self.backbone = backbone
        self.backbone.requires_grad_(False)
        self.embed_dim = embed_dim
        self.head_width = head_width
        self.head = nn.Sequential(
            nn.Conv2d(embed_dim, head_width, 1),
            nn.GELU(),
            nn.Conv2d(head_width, head_width, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(head_width, 1, 1),
        )
        self.register_buffer("mean", torch.tensor(IMAGENET_MEAN).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(IMAGENET_STD).view(1, 3, 1, 1))

    @property
    def name(self) -> str:
        return f"dinov2-probe-c{self.embed_dim}-h{self.head_width}"

    def train(self, mode: bool = True) -> Self:
        # Энкодер всегда в режиме оценки: обучается только голова.
        super().train(mode)
        self.backbone.eval()
        return self

    def features(self, x: torch.Tensor) -> torch.Tensor:
        """Признаки патчей N×C×gh×gw для тайлов N×1×H×W — без градиента."""
        _, _, height, width = x.shape
        padded = functional.pad(x, (0, (-width) % PATCH, 0, (-height) % PATCH), value=1.0)
        mean = self.get_buffer("mean").to(padded.dtype)
        std = self.get_buffer("std").to(padded.dtype)
        rgb = (padded.expand(-1, 3, -1, -1) - mean) / std
        encoder_weight = next(self.backbone.parameters(), None)
        if encoder_weight is not None:
            rgb = rgb.to(encoder_weight.dtype)
        with torch.no_grad():
            output = self.backbone(pixel_values=rgb)
        tokens: torch.Tensor = output.last_hidden_state[:, 1:, :]
        rows, columns = padded.shape[2] // PATCH, padded.shape[3] // PATCH
        return tokens.transpose(1, 2).reshape(x.shape[0], tokens.shape[2], rows, columns)

    def decode(self, features: torch.Tensor, height: int, width: int) -> torch.Tensor:
        logits: torch.Tensor = self.head(features.to(next(self.head.parameters()).dtype))
        upsampled = functional.interpolate(
            logits,
            size=(features.shape[2] * PATCH, features.shape[3] * PATCH),
            mode="bilinear",
            align_corners=False,
        )
        return upsampled[:, :, :height, :width]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decode(self.features(x), x.shape[2], x.shape[3])


def load_encoder(size: str, device: torch.device) -> tuple[nn.Module, str]:
    """Закреплённый DINOv2 из Hugging Face; хеш файла весов сверяется до использования."""
    from huggingface_hub import hf_hub_download
    from transformers import Dinov2Model

    pinned = ENCODERS[size]
    path = hf_hub_download(pinned.repo_id, "model.safetensors", revision=pinned.revision)
    digest = runrecord.sha256_file(Path(path))
    if digest != pinned.weights_sha256:
        raise ValueError(f"SHA-256 весов {pinned.repo_id} не совпадает с закреплённым")
    dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
    model = Dinov2Model.from_pretrained(pinned.repo_id, revision=pinned.revision, dtype=dtype)
    module: nn.Module = model
    module.to(device)
    module.eval()
    initialization = (
        f"{pinned.repo_id}@{pinned.revision} model.safetensors sha256:{digest} (заморожен)"
    )
    return module, initialization
