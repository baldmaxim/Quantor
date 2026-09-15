"""SAM 2.1 через `transformers` с официальными весами Meta на Hugging Face.

Пакет `sam2` с PyPI не используется: под этим именем опубликован сторонний форк, а не код Meta.
Официальные веса `facebook/sam2.1-hiera-*` лежат в формате `transformers` (Apache-2.0) и грузятся
по закреплённой ревизии; SHA-256 файла весов пишется в запись прогона.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import torch
from torch.nn import functional

from quantor_vision import runrecord

# Ревизии проверены 2026-09-15 (HF API, license apache-2.0); vision/licenses/decisions.json.
MODELS: dict[str, tuple[str, str]] = {
    "tiny": ("facebook/sam2.1-hiera-tiny", "de431c4043854a71d8101e17995dfe596bf101a5"),
    "small": ("facebook/sam2.1-hiera-small", "ee5bba1d82bb8749febdf90f45e84b687142ba03"),
    "base-plus": ("facebook/sam2.1-hiera-base-plus", "b7320756a13354e7530a63935656d35b2f91a290"),
}


@dataclass(frozen=True, slots=True)
class MaskBatch:
    # Логиты масок N×K×h×w низкого разрешения и оценки качества N×K.
    logits: torch.Tensor
    scores: torch.Tensor


class Segmenter(Protocol):
    """То, что нужно политикам: эмбеддинг тайла и маски по точкам или рамкам."""

    def embed(self, image: torch.Tensor) -> object: ...

    def from_points(self, embedding: object, points: list[tuple[float, float]]) -> MaskBatch: ...

    def from_boxes(
        self,
        embedding: object,
        boxes: list[tuple[float, float, float, float]],
        points: list[tuple[float, float]],
    ) -> MaskBatch: ...

    def provenance(self) -> dict[str, str]: ...


def upscale(logits: torch.Tensor, size: int) -> torch.Tensor:
    """Логиты маски h×w → булева маска size×size (тайл без полей: вход SAM равен тайлу)."""
    return (
        functional.interpolate(
            logits.unsqueeze(0).unsqueeze(0).float(), size=(size, size), mode="bilinear"
        )[0, 0]
        > 0
    )


class Sam2Segmenter:
    def __init__(self, size: str, device: torch.device) -> None:
        from huggingface_hub import hf_hub_download
        from transformers import Sam2Model, Sam2Processor

        self.model_id, self.revision = MODELS[size]
        self.device = device
        self.processor = Sam2Processor.from_pretrained(self.model_id, revision=self.revision)
        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        model = Sam2Model.from_pretrained(self.model_id, revision=self.revision, dtype=dtype)
        # Перенос через torch.nn.Module.to: у обёртки transformers иная сигнатура для типов.
        torch.nn.Module.to(model, device)
        torch.nn.Module.train(model, False)
        self.model = model
        weights = hf_hub_download(self.model_id, "model.safetensors", revision=self.revision)
        self.weights_sha256 = runrecord.sha256_file(Path(weights))
        self.dtype = dtype

    def embed(self, image: torch.Tensor) -> object:
        rgb = (image.clamp(0, 1) * 255).to(torch.uint8).repeat(3, 1, 1)
        inputs = self.processor(images=rgb, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device, self.dtype)
        return self.model.get_image_embeddings(pixel_values)

    def _decode(self, embedding: object, **prompts: torch.Tensor) -> MaskBatch:
        outputs = self.model(image_embeddings=embedding, multimask_output=True, **prompts)
        logits = outputs.pred_masks[0].float().cpu()
        scores = outputs.iou_scores[0].float().cpu()
        return MaskBatch(logits, scores)

    def from_points(self, embedding: object, points: list[tuple[float, float]]) -> MaskBatch:
        inputs = self.processor(
            images=None,
            input_points=[[[[x, y]] for x, y in points]],
            input_labels=[[[1] for _ in points]],
            original_sizes=[[1024, 1024]],
            return_tensors="pt",
        )
        return self._decode(
            embedding,
            input_points=inputs["input_points"].to(self.device),
            input_labels=inputs["input_labels"].to(self.device),
        )

    def from_boxes(
        self,
        embedding: object,
        boxes: list[tuple[float, float, float, float]],
        points: list[tuple[float, float]],
    ) -> MaskBatch:
        inputs = self.processor(
            images=None,
            input_boxes=[[list(box) for box in boxes]],
            input_points=[[[[x, y]] for x, y in points]],
            input_labels=[[[1] for _ in points]],
            original_sizes=[[1024, 1024]],
            return_tensors="pt",
        )
        return self._decode(
            embedding,
            input_boxes=inputs["input_boxes"].to(self.device),
            input_points=inputs["input_points"].to(self.device),
            input_labels=inputs["input_labels"].to(self.device),
        )

    def provenance(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "weights_file": "model.safetensors",
            "weights_sha256": self.weights_sha256,
            "dtype": str(self.dtype),
        }
